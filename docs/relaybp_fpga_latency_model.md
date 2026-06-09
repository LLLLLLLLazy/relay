# Relay-BP FPGA latency model

This note documents the estimator in `tools/estimate_relaybp_fpga_latency.py`.

## Paper facts used

The arXiv source for `2510.21600` states that the decoder uses a fully parallel
message-passing architecture: one compute unit is assigned to every variable
node and every check node, and FPGA wiring implements the graph connectivity.
Each check-node unit and variable-node unit completes in one decoder clock
cycle, so a flooding-schedule BP iteration takes two decoder cycles.

For the gross `[[144,12,12]]` split X/Z decoder, the resource table reports a
12 ns decoder cycle. Therefore one BP iteration is:

```text
2 cycles/iteration * 12 ns/cycle = 24 ns/iteration
```

The paper's 40 ns/round latency follows from its p=0.001 gross-code contour:

```text
20 average BP iterations * 24 ns/iteration / 12 syndrome rounds = 40 ns/round
```

## What the script simulates

The script uses the repository's Rust-backed Python Relay-BP decoder to decode
sampled syndrome windows on CPU and collect per-shot BP iteration counts. It
then maps iteration counts onto FPGA time using the paper's fully parallel
latency rule.

Because the local decoder is the repository's floating-point implementation,
while the paper's validation uses a custom integer/windowing FPGA reference
model, the script reports two iteration columns:

- `raw_avg_iterations`: direct CPU Relay-BP measurements.
- `calibrated_avg_iterations`: raw measurements scaled so the selected gross
  `[[144,12,12]]` calibration set matches the paper's 20 average iterations and
  40 ns/round.

That calibration is deliberately explicit. It lets the gross-code result match
the paper exactly, then applies the same scale factor to other BB-code sizes.

## Default command

From a clean checkout, first install the local Rust/Python package and Stim
extras:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[stim]"
```

Then run:

```bash
.venv/bin/python tools/estimate_relaybp_fpga_latency.py \
  --shots 1000 \
  --output-csv docs/relaybp_fpga_latency_estimates.csv
```

Defaults match the paper's split X/Z setting as closely as this repository
allows: detector-basis filtering, `gamma0=0.125`, `T0=80`, `Tr=60`,
`R=600`, `gamma in [-0.24,0.66]`, alpha ramping, and calibration to the
gross-code 24 ns/BP-iteration and 40 ns/round report.

The estimator also reports detector, error-variable, and edge counts. These are
resource-pressure indicators for the fully parallel FPGA design; they are not
extra latency cycles in the idealized architecture.

## 1000-shot p=0.001 snapshot

The saved CSV snapshot is `docs/relaybp_fpga_latency_estimates.csv`.

```text
code          basis  raw_iter  calibrated_iter  ns/window  ns/round
18_4_3        X       6.989       5.724          137.379    45.793
18_4_3        Z       7.086       5.804          139.285    46.428
72_12_6       X      11.368       9.311          223.454    37.242
72_12_6       Z      11.371       9.313          223.513    37.252
144_12_12     X      24.286      19.891          477.376    39.781
144_12_12     Z      24.553      20.109          482.624    40.219
288_12_18     X      45.137      36.968          887.232    49.291
288_12_18     Z      47.279      38.722          929.336    51.630
```

The X/Z aggregate for `144_12_12` is exactly 20 calibrated iterations,
480 ns/window, and 40 ns/round.
