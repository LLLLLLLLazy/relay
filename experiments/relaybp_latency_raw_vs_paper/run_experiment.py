#!/usr/bin/env python3
"""Relay-BP raw FPGA-latency experiment.

This experiment deliberately does not replace CPU-measured iteration counts with
paper-calibrated counts.  It reports both:

* raw_cpu_latency_ns_per_round = raw_avg_iterations * 24 ns / rounds
* paper_calibrated_latency_ns_per_round, as a secondary diagnostic

It also checks whether the gross [[144,12,12]] raw iteration count is close to
the paper's 20 average iterations.
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

REPO_ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(REPO_ROOT / ".cache" / "matplotlib"))
(REPO_ROOT / ".cache" / "matplotlib").mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(REPO_ROOT / "tests"))

import numpy as np
import relay_bp
import stim
from relay_bp.stim.sinter.check_matrices import CheckMatrices
from testdata import filter_detectors_by_basis


PAPER_ITERATION_NS = 24.0
PAPER_GROSS_AVG_ITERATIONS = 20.0
PAPER_RELAY1_MAX_AVG_ITERATIONS = 10.0

CODE_ALIASES = {
    "18": "18_4_3",
    "BB18": "18_4_3",
    "72": "72_12_6",
    "BB72": "72_12_6",
    "90": "90_8_10",
    "BB90": "90_8_10",
    "108": "108_8_10",
    "BB108": "108_8_10",
    "144": "144_12_12",
    "BB144": "144_12_12",
    "288": "288_12_18",
    "BB288": "288_12_18",
    "360": "360_12_24",
    "BB360": "360_12_24",
    "648": "648_12_30",
    "BB648": "648_12_30",
    "756": "756_16_34",
    "BB756": "756_16_34",
}


@dataclass(frozen=True)
class Case:
    code: str
    basis: str
    path: Path
    rounds: int


@dataclass
class Result:
    mode: str
    code: str
    basis: str
    rounds: int
    shots: int
    relay_solutions: int
    gamma_mode: str
    beta_int_low: int | None
    beta_int_high: int | None
    memory_strength_scale: int | None
    alpha_mode: str
    alpha_value: float | None
    i64_data_scale_value: float | None
    i64_max_data_value: float | None
    success_rate: float
    raw_avg_iterations: float
    raw_median_iterations: float
    raw_p90_iterations: float
    raw_p99_iterations: float
    raw_max_iterations: int
    raw_cpu_window_latency_ns: float
    raw_cpu_latency_ns_per_round: float
    paper_calibrated_avg_iterations: float | None
    paper_calibrated_window_latency_ns: float | None
    paper_calibrated_latency_ns_per_round: float | None
    gross_iteration_scale: float | None
    detectors: int
    error_variables: int
    edges: int
    max_check_degree: int
    max_variable_degree: int
    cpu_decode_seconds: float


@dataclass(frozen=True)
class MissingInput:
    requested_code: str
    resolved_code: str
    basis: str
    error_rate: str
    reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--testdata-dir",
        type=Path,
        default=REPO_ROOT / "tests" / "testdata" / "bicycle_bivariate",
    )
    parser.add_argument("--codes", default="144_12_12")
    parser.add_argument("--bases", default="X,Z")
    parser.add_argument("--error-rate", default="0.001")
    parser.add_argument("--shots", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--pre-iter", type=int, default=80)
    parser.add_argument("--num-sets", type=int, default=600)
    parser.add_argument("--set-max-iter", type=int, default=60)
    parser.add_argument(
        "--stop-nconv",
        "--relay-solutions",
        dest="stop_nconv",
        type=int,
        default=5,
        help=(
            "Relay-BP S parameter: stop after this many converged solutions. "
            "The paper's low-latency Relay-BP-1 setting corresponds to 1."
        ),
    )
    parser.add_argument("--gamma0", type=float, default=0.125)
    parser.add_argument("--gamma-low", type=float, default=-0.24)
    parser.add_argument("--gamma-high", type=float, default=0.66)
    parser.add_argument(
        "--gamma-mode",
        choices=("continuous", "beta_int"),
        default="continuous",
        help=(
            "Use continuous random gamma values, or paper-style beta_int "
            "quantization where gamma = 1 - beta_int / M."
        ),
    )
    parser.add_argument("--memory-strength-scale", type=int, default=8)
    parser.add_argument("--beta-int-low", type=int, default=3)
    parser.add_argument("--beta-int-high", type=int, default=10)
    parser.add_argument(
        "--alpha-mode",
        choices=("paper_ramp", "one", "constant"),
        default="paper_ramp",
        help=(
            "paper_ramp uses alpha(t)=1-2^-t; one disables scaling; "
            "constant uses --alpha-value."
        ),
    )
    parser.add_argument("--alpha-value", type=float, default=1.0)
    parser.add_argument("--alpha-iteration-scaling-factor", type=float, default=1.0)
    parser.add_argument(
        "--i64-data-scale-value",
        type=float,
        default=None,
        help="Override I64 log-domain scale S. int4.2.8 proxy uses S=2.",
    )
    parser.add_argument(
        "--i64-max-data-value",
        type=float,
        default=None,
        help="Override I64 clipping magnitude. int4 proxy previously used 15.",
    )
    parser.add_argument(
        "--paper-low-latency-params",
        action="store_true",
        help=(
            "Shortcut for the paper low-latency Relay-BP-1 settings: "
            "S=1, beta_int in [3,10] with M=8, and paper alpha ramp."
        ),
    )
    parser.add_argument(
        "--paper-int4-2-8-proxy",
        action="store_true",
        help=(
            "Shortcut for the closest exposed int4.2.8 I64 proxy: "
            "--paper-low-latency-params plus I64 S=2 and clip=15. "
            "This is still a proxy, not the paper's full FPGA arithmetic."
        ),
    )
    parser.add_argument("--gross-tolerance", type=float, default=0.10)
    parser.add_argument(
        "--modes",
        default="fp64_continuous,fp64_beta8_gamma,i64_scale2_int4_proxy,i64_scale8_wide_proxy",
        help=(
            "Comma-separated modes: fp64_continuous, fp64_beta8_gamma, "
            "i64_scale2_int4_proxy, i64_scale8_wide_proxy"
        ),
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=Path(__file__).with_name("results.csv"),
    )
    parser.add_argument(
        "--missing-csv",
        type=Path,
        default=None,
        help="CSV path for requested code/basis inputs that were not found.",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Skip missing code/basis inputs and record them in --missing-csv.",
    )
    parser.add_argument(
        "--skip-basis-filter",
        action="store_true",
        help=(
            "Do not call filter_detectors_by_basis. Use only for inputs that are "
            "already generated as single-basis memory circuits."
        ),
    )
    args = parser.parse_args()
    apply_parameter_shortcuts(args)
    return args


def apply_parameter_shortcuts(args: argparse.Namespace) -> None:
    if args.paper_int4_2_8_proxy:
        args.paper_low_latency_params = True
        args.i64_data_scale_value = 2.0
        args.i64_max_data_value = 15.0

    if args.paper_low_latency_params:
        args.stop_nconv = 1
        args.gamma_mode = "beta_int"
        args.memory_strength_scale = 8
        args.beta_int_low = 3
        args.beta_int_high = 10
        args.alpha_mode = "paper_ramp"


def split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def normalize_code_label(code: str) -> str:
    normalized = CODE_ALIASES.get(code, CODE_ALIASES.get(code.upper()))
    if normalized is not None:
        return normalized
    upper = code.upper()
    if upper.startswith("BB") and upper[2:].isdigit():
        return upper[2:]
    return code


def find_case(testdata_dir: Path, code: str, basis: str, error_rate: str) -> Case:
    pattern = (
        f"circuit=bicycle_bivariate_{code}_memory_{basis},"
        f"*error_rate={error_rate},*.stim"
    )
    paths = sorted(testdata_dir.glob(pattern))
    if len(paths) != 1:
        raise ValueError(f"Expected one path for {pattern!r}, found {len(paths)}")
    rounds_match = re.search(r"rounds=(\d+)", paths[0].name)
    if rounds_match is None:
        raise ValueError(f"Could not parse rounds from {paths[0].name}")
    return Case(code=code, basis=basis, path=paths[0], rounds=int(rounds_match.group(1)))


def load_case(case: Case, *, skip_basis_filter: bool = False) -> tuple[stim.Circuit, CheckMatrices]:
    circuit = stim.Circuit.from_file(case.path)
    if not skip_basis_filter:
        circuit = filter_detectors_by_basis(circuit, case.basis)
    matrices = CheckMatrices.from_dem(circuit.detector_error_model(decompose_errors=False))
    return circuit, matrices


def matrix_stats(check_matrix) -> tuple[int, int, int, int, int]:
    csr = check_matrix.tocsr()
    csc = check_matrix.tocsc()
    check_degrees = np.diff(csr.indptr)
    variable_degrees = np.diff(csc.indptr)
    return (
        int(check_matrix.shape[0]),
        int(check_matrix.shape[1]),
        int(check_matrix.nnz),
        int(check_degrees.max(initial=0)),
        int(variable_degrees.max(initial=0)),
    )


def quantized_beta_gammas(
    *,
    num_sets: int,
    num_errors: int,
    seed: int,
    beta_int_low: int,
    beta_int_high: int,
    memory_strength_scale: int,
) -> np.ndarray:
    """Generate paper-style beta_int values, then gamma=1-beta_int/M."""
    rng = np.random.default_rng(seed)
    beta_int = rng.integers(
        beta_int_low,
        beta_int_high + 1,
        size=(num_sets, num_errors),
        dtype=np.int16,
    )
    return 1.0 - beta_int.astype(np.float64) / float(memory_strength_scale)


def alpha_config(args: argparse.Namespace) -> tuple[float | None, float]:
    if args.alpha_mode == "paper_ramp":
        return 0.0, args.alpha_iteration_scaling_factor
    if args.alpha_mode == "one":
        return None, args.alpha_iteration_scaling_factor
    if args.alpha_mode == "constant":
        return args.alpha_value, args.alpha_iteration_scaling_factor
    raise ValueError(f"Unknown alpha mode: {args.alpha_mode}")


def explicit_gammas_for_mode(
    mode: str,
    matrices: CheckMatrices,
    args: argparse.Namespace,
    seed: int,
) -> np.ndarray | None:
    if args.gamma_mode != "beta_int" and mode != "fp64_beta8_gamma":
        return None
    return quantized_beta_gammas(
        num_sets=args.num_sets,
        num_errors=matrices.check_matrix.shape[1],
        seed=seed,
        beta_int_low=args.beta_int_low,
        beta_int_high=args.beta_int_high,
        memory_strength_scale=args.memory_strength_scale,
    )


def i64_params(
    args: argparse.Namespace,
    *,
    default_data_scale_value: float,
    default_max_data_value: float,
) -> tuple[float, float]:
    data_scale_value = (
        default_data_scale_value
        if args.i64_data_scale_value is None
        else args.i64_data_scale_value
    )
    max_data_value = (
        default_max_data_value
        if args.i64_max_data_value is None
        else args.i64_max_data_value
    )
    return data_scale_value, max_data_value


def effective_gamma_mode(mode: str, args: argparse.Namespace) -> str:
    if args.gamma_mode == "beta_int" or mode == "fp64_beta8_gamma":
        return "beta_int"
    return "continuous"


def effective_i64_params(mode: str, args: argparse.Namespace) -> tuple[float | None, float | None]:
    if mode == "i64_scale2_int4_proxy":
        return i64_params(
            args,
            default_data_scale_value=2.0,
            default_max_data_value=15.0,
        )
    if mode == "i64_scale8_wide_proxy":
        return i64_params(
            args,
            default_data_scale_value=8.0,
            default_max_data_value=127.0,
        )
    return None, None


def build_decoder(mode: str, matrices: CheckMatrices, args: argparse.Namespace, seed: int):
    alpha, alpha_iteration_scaling_factor = alpha_config(args)
    explicit_gammas = explicit_gammas_for_mode(mode, matrices, args, seed)
    base_kwargs = dict(
        check_matrix=matrices.check_matrix,
        error_priors=matrices.error_priors,
        alpha=alpha,
        alpha_iteration_scaling_factor=alpha_iteration_scaling_factor,
        gamma0=args.gamma0,
        pre_iter=args.pre_iter,
        num_sets=args.num_sets,
        set_max_iter=args.set_max_iter,
        gamma_dist_interval=(args.gamma_low, args.gamma_high),
        explicit_gammas=explicit_gammas,
        stop_nconv=args.stop_nconv,
        stopping_criterion="nconv",
        seed=args.seed,
    )

    if mode == "fp64_continuous":
        return relay_bp.RelayDecoderF64(**base_kwargs)

    if mode == "fp64_beta8_gamma":
        return relay_bp.RelayDecoderF64(**base_kwargs)

    if mode == "i64_scale2_int4_proxy":
        data_scale_value, max_data_value = i64_params(
            args,
            default_data_scale_value=2.0,
            default_max_data_value=15.0,
        )
        return relay_bp.RelayDecoderI64(
            **base_kwargs,
            data_scale_value=data_scale_value,
            max_data_value=max_data_value,
        )

    if mode == "i64_scale8_wide_proxy":
        data_scale_value, max_data_value = i64_params(
            args,
            default_data_scale_value=8.0,
            default_max_data_value=127.0,
        )
        return relay_bp.RelayDecoderI64(
            **base_kwargs,
            data_scale_value=data_scale_value,
            max_data_value=max_data_value,
        )

    raise ValueError(f"Unknown mode: {mode}")


def run_one(case: Case, mode: str, args: argparse.Namespace, row_index: int) -> Result:
    circuit, matrices = load_case(case, skip_basis_filter=args.skip_basis_filter)
    detectors, error_variables, edges, max_check_degree, max_variable_degree = matrix_stats(
        matrices.check_matrix
    )

    sampler = circuit.compile_detector_sampler(seed=args.seed + row_index)
    sampled_detectors, _sampled_observables = sampler.sample(
        args.shots, separate_observables=True
    )
    syndromes = sampled_detectors.astype(np.uint8)
    if matrices.syndrome_bias is not None:
        syndromes = (syndromes + matrices.syndrome_bias) % 2

    decoder = build_decoder(mode, matrices, args, seed=args.seed + 10_000 + row_index)
    start = time.perf_counter()
    decoded = decoder.decode_detailed_batch(syndromes)
    cpu_decode_seconds = time.perf_counter() - start

    iterations = np.array([item.iterations for item in decoded], dtype=np.float64)
    successes = np.array([item.success for item in decoded], dtype=np.bool_)
    raw_window_latency = float(iterations.mean() * PAPER_ITERATION_NS)
    gamma_mode = effective_gamma_mode(mode, args)
    beta_int_low = args.beta_int_low if gamma_mode == "beta_int" else None
    beta_int_high = args.beta_int_high if gamma_mode == "beta_int" else None
    memory_strength_scale = args.memory_strength_scale if gamma_mode == "beta_int" else None
    i64_data_scale_value, i64_max_data_value = effective_i64_params(mode, args)
    return Result(
        mode=mode,
        code=case.code,
        basis=case.basis,
        rounds=case.rounds,
        shots=args.shots,
        relay_solutions=args.stop_nconv,
        gamma_mode=gamma_mode,
        beta_int_low=beta_int_low,
        beta_int_high=beta_int_high,
        memory_strength_scale=memory_strength_scale,
        alpha_mode=args.alpha_mode,
        alpha_value=args.alpha_value if args.alpha_mode == "constant" else None,
        i64_data_scale_value=i64_data_scale_value,
        i64_max_data_value=i64_max_data_value,
        success_rate=float(successes.mean()),
        raw_avg_iterations=float(iterations.mean()),
        raw_median_iterations=float(np.median(iterations)),
        raw_p90_iterations=float(np.quantile(iterations, 0.90)),
        raw_p99_iterations=float(np.quantile(iterations, 0.99)),
        raw_max_iterations=int(iterations.max(initial=0)),
        raw_cpu_window_latency_ns=raw_window_latency,
        raw_cpu_latency_ns_per_round=raw_window_latency / case.rounds,
        paper_calibrated_avg_iterations=None,
        paper_calibrated_window_latency_ns=None,
        paper_calibrated_latency_ns_per_round=None,
        gross_iteration_scale=None,
        detectors=detectors,
        error_variables=error_variables,
        edges=edges,
        max_check_degree=max_check_degree,
        max_variable_degree=max_variable_degree,
        cpu_decode_seconds=cpu_decode_seconds,
    )


def add_paper_calibrated_columns(results: list[Result]) -> dict[str, tuple[float, bool]]:
    checks: dict[str, tuple[float, bool]] = {}
    modes = sorted({result.mode for result in results})
    for mode in modes:
        gross = [
            result
            for result in results
            if result.mode == mode and result.code == "144_12_12"
        ]
        if not gross:
            continue
        gross_avg = sum(result.raw_avg_iterations * result.shots for result in gross) / sum(
            result.shots for result in gross
        )
        scale = PAPER_GROSS_AVG_ITERATIONS / gross_avg
        checks[mode] = (gross_avg, scale)
        for result in results:
            if result.mode != mode:
                continue
            result.gross_iteration_scale = scale
            result.paper_calibrated_avg_iterations = result.raw_avg_iterations * scale
            result.paper_calibrated_window_latency_ns = (
                result.paper_calibrated_avg_iterations * PAPER_ITERATION_NS
            )
            result.paper_calibrated_latency_ns_per_round = (
                result.paper_calibrated_window_latency_ns / result.rounds
            )
    return checks


def write_csv(path: Path, results: list[Result]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(Result.__dataclass_fields__.keys()))
        writer.writeheader()
        for result in results:
            writer.writerow(result.__dict__)


def write_missing_csv(path: Path, missing: list[MissingInput]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(MissingInput.__dataclass_fields__.keys()))
        writer.writeheader()
        for item in missing:
            writer.writerow(item.__dict__)


def print_summary(results: list[Result], checks: dict[str, tuple[float, float]], tolerance: float) -> None:
    for mode, (gross_avg, scale) in sorted(checks.items()):
        gross_results = [
            result
            for result in results
            if result.mode == mode and result.code == "144_12_12"
        ]
        relay_solutions = gross_results[0].relay_solutions if gross_results else None
        raw_latency = gross_avg * PAPER_ITERATION_NS / 12.0
        if relay_solutions == 1:
            status = "PASS" if gross_avg < PAPER_RELAY1_MAX_AVG_ITERATIONS else "FAIL"
            print(
                f"{mode}: gross_raw_avg_iterations={gross_avg:.3f}, "
                f"gross_raw_latency={raw_latency:.3f} ns/round, "
                f"relay_bp_1_reference=<10 iterations, "
                f"scale_if_calibrated_to_20={scale:.6f}, "
                f"raw_check={status}"
            )
            continue

        rel_error = abs(gross_avg - PAPER_GROSS_AVG_ITERATIONS) / PAPER_GROSS_AVG_ITERATIONS
        status = "PASS" if rel_error <= tolerance else "FAIL"
        print(
            f"{mode}: gross_raw_avg_iterations={gross_avg:.3f}, "
            f"gross_raw_latency={raw_latency:.3f} ns/round, "
            f"relative_error={rel_error:.2%}, scale_if_calibrated={scale:.6f}, "
            f"raw_check={status}"
        )

    print()
    print(
        "mode                       code        basis  raw_iter  raw_ns/round  "
        "cal_ns/round  success"
    )
    for result in results:
        calibrated_latency = (
            "NA"
            if result.paper_calibrated_latency_ns_per_round is None
            else f"{result.paper_calibrated_latency_ns_per_round:.3f}"
        )
        print(
            f"{result.mode:26} {result.code:10} {result.basis:>5} "
            f"{result.raw_avg_iterations:9.3f} "
            f"{result.raw_cpu_latency_ns_per_round:13.3f} "
            f"{calibrated_latency:>12} "
            f"{result.success_rate:8.3f}"
        )


def main() -> int:
    args = parse_args()
    cases: list[Case] = []
    missing: list[MissingInput] = []
    for requested_code in split_csv(args.codes):
        resolved_code = normalize_code_label(requested_code)
        for basis in split_csv(args.bases):
            try:
                cases.append(find_case(args.testdata_dir, resolved_code, basis, args.error_rate))
            except ValueError as exc:
                if not args.allow_missing:
                    raise
                missing.append(
                    MissingInput(
                        requested_code=requested_code,
                        resolved_code=resolved_code,
                        basis=basis,
                        error_rate=args.error_rate,
                        reason=str(exc),
                    )
                )
    modes = split_csv(args.modes)

    results: list[Result] = []
    row_index = 0
    for mode in modes:
        for case in cases:
            print(f"running mode={mode} code={case.code} basis={case.basis}", file=sys.stderr)
            results.append(run_one(case, mode, args, row_index))
            row_index += 1

    checks = add_paper_calibrated_columns(results)
    write_csv(args.output_csv, results)
    missing_csv = args.missing_csv or args.output_csv.with_name(
        args.output_csv.stem + "_missing_inputs.csv"
    )
    if missing:
        write_missing_csv(missing_csv, missing)
    print_summary(results, checks, args.gross_tolerance)
    if missing:
        print()
        print("missing requested inputs:")
        for item in missing:
            print(
                f"{item.requested_code} -> {item.resolved_code} {item.basis}: "
                f"{item.reason}"
            )
    print(f"\nwrote {args.output_csv}")
    if missing:
        print(f"wrote {missing_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
