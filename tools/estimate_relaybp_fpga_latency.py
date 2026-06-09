#!/usr/bin/env python3
"""Estimate Relay-BP FPGA latency from CPU Relay-BP iteration counts.

The model follows the FPGA architecture described in arXiv:2510.21600:
one fully-parallel CNU phase plus one fully-parallel VNU phase make a BP
iteration.  The gross-code split X/Z decoder closes timing at 12 ns per
decoder cycle, i.e. 24 ns per BP iteration.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(REPO_ROOT / ".cache" / "matplotlib"))
(REPO_ROOT / ".cache" / "matplotlib").mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(REPO_ROOT / "tests"))

import numpy as np
import relay_bp
import stim
from relay_bp.stim.sinter.check_matrices import CheckMatrices
from testdata import filter_detectors_by_basis


@dataclass
class RunConfig:
    code: str
    basis: str
    circuit_path: Path
    rounds: int
    error_rate: str


@dataclass
class EstimateRow:
    code: str
    basis: str
    rounds: int
    shots: int
    raw_avg_iterations: float
    median_iterations: float
    p90_iterations: float
    p99_iterations: float
    max_iterations: int
    success_rate: float
    cpu_decode_seconds: float
    detectors: int
    error_variables: int
    edges: int
    max_check_degree: int
    max_variable_degree: int
    avg_check_degree: float
    avg_variable_degree: float
    calibrated_avg_iterations: float | None = None
    window_latency_ns: float | None = None
    latency_ns_per_round: float | None = None
    edge_ratio_vs_calibration: float | None = None
    detector_ratio_vs_calibration: float | None = None
    variable_ratio_vs_calibration: float | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CPU-simulate Relay-BP iteration counts and estimate FPGA latency."
    )
    parser.add_argument(
        "--testdata-dir",
        type=Path,
        default=REPO_ROOT / "tests" / "testdata" / "bicycle_bivariate",
    )
    parser.add_argument(
        "--codes",
        default="18_4_3,72_12_6,144_12_12,288_12_18",
        help="Comma-separated BB code labels N_K_D from stored test circuits.",
    )
    parser.add_argument(
        "--bases",
        default="X,Z",
        help="Comma-separated memory bases. Use X,Z for the paper's split decoder.",
    )
    parser.add_argument("--error-rate", default="0.001")
    parser.add_argument("--shots", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--no-basis-filter",
        action="store_true",
        help="Do not filter detectors by X/Z basis before extracting matrices.",
    )
    parser.add_argument("--gamma0", type=float, default=0.125)
    parser.add_argument("--pre-iter", type=int, default=80)
    parser.add_argument("--num-sets", type=int, default=600)
    parser.add_argument("--set-max-iter", type=int, default=60)
    parser.add_argument("--stop-nconv", type=int, default=5)
    parser.add_argument("--gamma-low", type=float, default=-0.24)
    parser.add_argument("--gamma-high", type=float, default=0.66)
    parser.add_argument(
        "--alpha-ramp",
        dest="alpha_ramp",
        action="store_true",
        default=True,
        help="Use alpha=1-2^-t scaling, matching the paper's CNU description.",
    )
    parser.add_argument(
        "--no-alpha-ramp",
        dest="alpha_ramp",
        action="store_false",
        help="Disable alpha ramping and use alpha=1.",
    )
    parser.add_argument(
        "--paper-iteration-ns",
        type=float,
        default=24.0,
        help="Gross-code split X/Z BP iteration time from the FPGA paper.",
    )
    parser.add_argument(
        "--paper-round-ns",
        type=float,
        default=40.0,
        help="Gross-code paper latency target per syndrome round.",
    )
    parser.add_argument(
        "--calibrate-code",
        default="144_12_12",
        help="Code used to calibrate CPU iteration counts to the paper.",
    )
    parser.add_argument(
        "--calibrate-basis",
        default="all",
        help="Basis used for calibration, or 'all' to aggregate selected bases.",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        help="Optional CSV output path.",
    )
    return parser.parse_args()


def split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def find_circuit(testdata_dir: Path, code: str, basis: str, error_rate: str) -> RunConfig:
    pattern = (
        f"circuit=bicycle_bivariate_{code}_memory_{basis},"
        f"*error_rate={error_rate},*.stim"
    )
    matches = sorted(testdata_dir.glob(pattern))
    if len(matches) != 1:
        raise ValueError(
            f"Expected one circuit for code={code} basis={basis} p={error_rate}, "
            f"found {len(matches)} with pattern {pattern!r}."
        )

    name = matches[0].name
    rounds_match = re.search(r"rounds=(\d+)", name)
    if rounds_match is None:
        raise ValueError(f"Could not parse rounds from {name}")
    return RunConfig(
        code=code,
        basis=basis,
        circuit_path=matches[0],
        rounds=int(rounds_match.group(1)),
        error_rate=error_rate,
    )


def build_check_matrices(config: RunConfig, basis_filter: bool) -> tuple[stim.Circuit, CheckMatrices]:
    circuit = stim.Circuit.from_file(config.circuit_path)
    if basis_filter and config.basis in {"X", "Z"}:
        circuit = filter_detectors_by_basis(circuit, config.basis)
    dem = circuit.detector_error_model(decompose_errors=False)
    return circuit, CheckMatrices.from_dem(dem)


def matrix_stats(check_matrix) -> tuple[int, int, int, int, int, float, float]:
    csr = check_matrix.tocsr()
    csc = check_matrix.tocsc()
    check_degrees = np.diff(csr.indptr)
    variable_degrees = np.diff(csc.indptr)
    return (
        check_matrix.shape[0],
        check_matrix.shape[1],
        int(check_matrix.nnz),
        int(check_degrees.max(initial=0)),
        int(variable_degrees.max(initial=0)),
        float(check_degrees.mean()) if check_degrees.size else 0.0,
        float(variable_degrees.mean()) if variable_degrees.size else 0.0,
    )


def estimate_one(config: RunConfig, args: argparse.Namespace, row_index: int) -> EstimateRow:
    circuit, matrices = build_check_matrices(config, basis_filter=not args.no_basis_filter)
    (
        detectors,
        error_variables,
        edges,
        max_check_degree,
        max_variable_degree,
        avg_check_degree,
        avg_variable_degree,
    ) = matrix_stats(matrices.check_matrix)

    sampler = circuit.compile_detector_sampler(seed=args.seed + row_index)
    sampled_detectors, _sampled_observables = sampler.sample(
        args.shots, separate_observables=True
    )
    syndromes = sampled_detectors.astype(np.uint8)
    if matrices.syndrome_bias is not None:
        syndromes = (syndromes + matrices.syndrome_bias) % 2

    decoder = relay_bp.RelayDecoderF64(
        matrices.check_matrix,
        error_priors=matrices.error_priors,
        alpha=0.0 if args.alpha_ramp else None,
        alpha_iteration_scaling_factor=1.0,
        gamma0=args.gamma0,
        pre_iter=args.pre_iter,
        num_sets=args.num_sets,
        set_max_iter=args.set_max_iter,
        gamma_dist_interval=(args.gamma_low, args.gamma_high),
        stop_nconv=args.stop_nconv,
        stopping_criterion="nconv",
        seed=args.seed,
    )

    start = time.perf_counter()
    results = decoder.decode_detailed_batch(syndromes)
    cpu_decode_seconds = time.perf_counter() - start
    iterations = np.array([result.iterations for result in results], dtype=np.float64)
    successes = np.array([result.success for result in results], dtype=np.bool_)

    return EstimateRow(
        code=config.code,
        basis=config.basis,
        rounds=config.rounds,
        shots=args.shots,
        raw_avg_iterations=float(iterations.mean()),
        median_iterations=float(np.median(iterations)),
        p90_iterations=float(np.quantile(iterations, 0.90)),
        p99_iterations=float(np.quantile(iterations, 0.99)),
        max_iterations=int(iterations.max(initial=0)),
        success_rate=float(successes.mean()),
        cpu_decode_seconds=cpu_decode_seconds,
        detectors=detectors,
        error_variables=error_variables,
        edges=edges,
        max_check_degree=max_check_degree,
        max_variable_degree=max_variable_degree,
        avg_check_degree=avg_check_degree,
        avg_variable_degree=avg_variable_degree,
    )


def apply_paper_calibration(
    rows: list[EstimateRow], args: argparse.Namespace
) -> tuple[float, float, EstimateRow]:
    calibration_rows = [
        row
        for row in rows
        if row.code == args.calibrate_code
        and (args.calibrate_basis == "all" or row.basis == args.calibrate_basis)
    ]
    if not calibration_rows:
        raise ValueError(
            f"No rows matched calibration target code={args.calibrate_code} "
            f"basis={args.calibrate_basis}."
        )

    calibration_rounds = calibration_rows[0].rounds
    paper_avg_iterations = (
        args.paper_round_ns * calibration_rounds / args.paper_iteration_ns
    )
    raw_avg_iterations = sum(
        row.raw_avg_iterations * row.shots for row in calibration_rows
    ) / sum(row.shots for row in calibration_rows)
    iteration_scale = paper_avg_iterations / raw_avg_iterations

    calibration_reference = calibration_rows[0]
    for row in rows:
        row.calibrated_avg_iterations = row.raw_avg_iterations * iteration_scale
        row.window_latency_ns = row.calibrated_avg_iterations * args.paper_iteration_ns
        row.latency_ns_per_round = row.window_latency_ns / row.rounds
        row.edge_ratio_vs_calibration = row.edges / calibration_reference.edges
        row.detector_ratio_vs_calibration = row.detectors / calibration_reference.detectors
        row.variable_ratio_vs_calibration = (
            row.error_variables / calibration_reference.error_variables
        )

    return paper_avg_iterations, iteration_scale, calibration_reference


def print_summary(
    rows: list[EstimateRow],
    args: argparse.Namespace,
    paper_avg_iterations: float,
    iteration_scale: float,
) -> None:
    calibration_rounds = next(
        row.rounds
        for row in rows
        if row.code == args.calibrate_code
        and (args.calibrate_basis == "all" or row.basis == args.calibrate_basis)
    )
    print(
        "Calibration: "
        f"{args.calibrate_code}/{args.calibrate_basis}, "
        f"paper_avg_iterations={paper_avg_iterations:.3f}, "
        f"paper_iteration_ns={args.paper_iteration_ns:.3f}, "
        f"iteration_scale={iteration_scale:.6f}"
    )
    print(
        "The calibrated gross-code aggregate is "
        f"{args.paper_round_ns:.3f} ns/round by construction "
        f"({paper_avg_iterations:.3f} iterations * "
        f"{args.paper_iteration_ns:.3f} ns / {calibration_rounds} rounds)."
    )
    print()

    columns = [
        "code",
        "basis",
        "rounds",
        "raw_iter",
        "cal_iter",
        "ns/window",
        "ns/round",
        "success",
        "edges",
        "edge_ratio",
    ]
    widths = [12, 5, 6, 9, 9, 10, 9, 8, 8, 10]
    print(" ".join(name.rjust(width) for name, width in zip(columns, widths)))
    for row in rows:
        values = [
            row.code,
            row.basis,
            str(row.rounds),
            f"{row.raw_avg_iterations:.3f}",
            f"{row.calibrated_avg_iterations:.3f}",
            f"{row.window_latency_ns:.3f}",
            f"{row.latency_ns_per_round:.3f}",
            f"{row.success_rate:.3f}",
            str(row.edges),
            f"{row.edge_ratio_vs_calibration:.3f}",
        ]
        print(" ".join(value.rjust(width) for value, width in zip(values, widths)))


def write_csv(rows: list[EstimateRow], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(EstimateRow.__dataclass_fields__.keys())
    with output_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def main() -> int:
    args = parse_args()
    configs = [
        find_circuit(args.testdata_dir, code, basis, args.error_rate)
        for code in split_csv(args.codes)
        for basis in split_csv(args.bases)
    ]

    rows = []
    for row_index, config in enumerate(configs):
        print(
            f"Running {config.code}/{config.basis} from "
            f"{config.circuit_path.name}...",
            file=sys.stderr,
            flush=True,
        )
        rows.append(estimate_one(config, args, row_index))

    paper_avg_iterations, iteration_scale, _calibration_reference = (
        apply_paper_calibration(rows, args)
    )
    print_summary(rows, args, paper_avg_iterations, iteration_scale)

    if args.output_csv is not None:
        write_csv(rows, args.output_csv)
        print(f"\nWrote {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
