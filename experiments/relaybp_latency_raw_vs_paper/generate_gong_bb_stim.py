#!/usr/bin/env python3
"""Generate BB memory Stim circuits with Gong et al.'s circuit builder.

The generated files are kept under this experiment folder instead of being
mixed into relay's checked-in testdata.  The filename format intentionally
matches run_experiment.py's glob pattern.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import types
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class GongCodeSpec:
    label: str
    n: int
    k: int
    distance: int
    l: int
    m: int
    a_terms: tuple[tuple[int, int], tuple[int, int], tuple[int, int]]
    b_terms: tuple[tuple[int, int], tuple[int, int], tuple[int, int]]
    a_poly: str
    b_poly: str


CODE_SPECS = {
    "72_12_6": GongCodeSpec(
        label="72_12_6",
        n=72,
        k=12,
        distance=6,
        l=6,
        m=6,
        a_terms=((3, 0), (0, 1), (0, 2)),
        b_terms=((0, 3), (1, 0), (2, 0)),
        a_poly="x^3+y+y^2",
        b_poly="y^3+x+x^2",
    ),
    "90_8_10": GongCodeSpec(
        label="90_8_10",
        n=90,
        k=8,
        distance=10,
        l=15,
        m=3,
        a_terms=((9, 0), (0, 1), (0, 2)),
        b_terms=((0, 0), (2, 0), (7, 0)),
        a_poly="x^9+y+y^2",
        b_poly="1+x^2+x^7",
    ),
    "108_8_10": GongCodeSpec(
        label="108_8_10",
        n=108,
        k=8,
        distance=10,
        l=9,
        m=6,
        a_terms=((3, 0), (0, 1), (0, 2)),
        b_terms=((0, 3), (1, 0), (2, 0)),
        a_poly="x^3+y+y^2",
        b_poly="y^3+x+x^2",
    ),
    "144_12_12": GongCodeSpec(
        label="144_12_12",
        n=144,
        k=12,
        distance=12,
        l=12,
        m=6,
        a_terms=((3, 0), (0, 1), (0, 2)),
        b_terms=((0, 3), (1, 0), (2, 0)),
        a_poly="x^3+y+y^2",
        b_poly="y^3+x+x^2",
    ),
    "288_12_18": GongCodeSpec(
        label="288_12_18",
        n=288,
        k=12,
        distance=18,
        l=12,
        m=12,
        a_terms=((3, 0), (0, 2), (0, 7)),
        b_terms=((0, 3), (1, 0), (2, 0)),
        a_poly="x^3+y^2+y^7",
        b_poly="y^3+x+x^2",
    ),
    "360_12_24": GongCodeSpec(
        label="360_12_24",
        n=360,
        k=12,
        distance=24,
        l=30,
        m=6,
        a_terms=((9, 0), (0, 1), (0, 2)),
        b_terms=((0, 3), (25, 0), (26, 0)),
        a_poly="x^9+y+y^2",
        b_poly="y^3+x^25+x^26",
    ),
    "648_12_30": GongCodeSpec(
        label="648_12_30",
        n=648,
        k=12,
        distance=30,
        l=18,
        m=18,
        a_terms=((3, 0), (0, 13), (12, 2)),
        b_terms=((0, 3), (7, 12), (14, 6)),
        a_poly="x^3+y^13+x^12*y^2",
        b_poly="y^3+x^7*y^12+x^14*y^6",
    ),
    "756_16_34": GongCodeSpec(
        label="756_16_34",
        n=756,
        k=16,
        distance=34,
        l=21,
        m=18,
        a_terms=((3, 0), (0, 10), (0, 17)),
        b_terms=((0, 5), (3, 0), (19, 0)),
        a_poly="x^3+y^10+y^17",
        b_poly="y^5+x^3+x^19",
    ),
}

CODE_ALIASES = {
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


def split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def normalize_code_label(code: str) -> str:
    return CODE_ALIASES.get(code, CODE_ALIASES.get(code.upper(), code))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sliding-window-decoder-dir",
        type=Path,
        default=Path("/private/tmp/SlidingWindowDecoder"),
    )
    parser.add_argument("--codes", default="BB90,BB108")
    parser.add_argument("--bases", default="X,Z")
    parser.add_argument("--error-rate", type=float, default=0.001)
    parser.add_argument("--rounds", type=int, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).with_name("generated_bicycle_bivariate"),
    )
    return parser.parse_args()


def import_gong_builders(sliding_window_decoder_dir: Path):
    if not sliding_window_decoder_dir.exists():
        raise FileNotFoundError(
            f"SlidingWindowDecoder repo not found: {sliding_window_decoder_dir}"
        )

    src_dir = sliding_window_decoder_dir / "src"
    package = types.ModuleType("src")
    package.__path__ = [str(src_dir)]
    sys.modules["src"] = package

    def load_module(module_name: str):
        spec = importlib.util.spec_from_file_location(
            f"src.{module_name}", src_dir / f"{module_name}.py"
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load src.{module_name} from {src_dir}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"src.{module_name}"] = module
        spec.loader.exec_module(module)
        return module

    load_module("utils")
    codes_q = load_module("codes_q")
    build_circuit_module = load_module("build_circuit")
    return (
        codes_q.create_circulant_matrix,
        codes_q.css_code,
        build_circuit_module.build_circuit,
    )


def create_bivariate_bicycle_code_from_terms(create_circulant_matrix, css_code, spec: GongCodeSpec):
    import numpy as np
    from scipy.sparse import identity, kron

    n2 = spec.l * spec.m
    S_l = create_circulant_matrix(spec.l, [-1])
    S_m = create_circulant_matrix(spec.m, [-1])
    x = kron(S_l, identity(spec.m, dtype=int))
    y = kron(identity(spec.l, dtype=int), S_m)
    eye = identity(n2, dtype=int)

    def monomial(x_pow: int, y_pow: int):
        x_part = eye if x_pow == 0 else x**x_pow
        y_part = eye if y_pow == 0 else y**y_pow
        return x_part @ y_part

    a_list = [monomial(x_pow, y_pow) for x_pow, y_pow in spec.a_terms]
    b_list = [monomial(x_pow, y_pow) for x_pow, y_pow in spec.b_terms]
    A = sum(a_list).toarray() % 2
    B = sum(b_list).toarray() % 2
    hx = np.hstack((A, B))
    hz = np.hstack((B.T, A.T))
    code = css_code(hx, hz, name_prefix="BB", check_css=True)
    if code.N != spec.n or code.K != spec.k:
        raise ValueError(
            f"{spec.label}: generated [[{code.N},{code.K},?]], "
            f"expected n={spec.n}, k={spec.k}"
        )
    return code, a_list, b_list


def format_error_rate(error_rate: float) -> str:
    return f"{error_rate:.6f}".rstrip("0").rstrip(".")


def output_path(output_dir: Path, spec: GongCodeSpec, basis: str, rounds: int, error_rate: float) -> Path:
    return output_dir / (
        f"circuit=bicycle_bivariate_{spec.label}_memory_{basis},"
        f"distance={spec.distance},rounds={rounds},"
        f"error_rate={format_error_rate(error_rate)},"
        f"noise_model=gong_uniform_circuit,basis=CX,"
        f"A={spec.a_poly},B={spec.b_poly}.stim"
    )


def main() -> int:
    args = parse_args()
    create_circulant_matrix, css_code, build_circuit = import_gong_builders(
        args.sliding_window_decoder_dir
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for requested_code in split_csv(args.codes):
        code_label = normalize_code_label(requested_code)
        if code_label not in CODE_SPECS:
            known = ", ".join(sorted(CODE_SPECS))
            raise ValueError(f"Unsupported code {requested_code!r}. Known: {known}")
        spec = CODE_SPECS[code_label]
        if spec.n != 2 * spec.l * spec.m:
            raise ValueError(f"{spec.label}: n != 2*l*m")

        code, a_list, b_list = create_bivariate_bicycle_code_from_terms(
            create_circulant_matrix, css_code, spec
        )
        rounds = args.rounds if args.rounds is not None else spec.distance
        for basis in split_csv(args.bases):
            if basis not in ("X", "Z"):
                raise ValueError(f"Unsupported basis {basis!r}")
            circuit = build_circuit(
                code,
                a_list,
                b_list,
                args.error_rate,
                rounds,
                z_basis=(basis == "Z"),
            )
            path = output_path(args.output_dir, spec, basis, rounds, args.error_rate)
            path.write_text(str(circuit))
            dem = circuit.detector_error_model(decompose_errors=False)
            print(
                f"wrote {path} "
                f"detectors={dem.num_detectors} observables={dem.num_observables}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
