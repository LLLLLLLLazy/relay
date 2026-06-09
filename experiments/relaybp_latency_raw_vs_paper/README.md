# Relay-BP raw-vs-paper latency experiment

This folder is the follow-up experiment after the initial paper-calibrated
estimate.  The rule here is stricter:

1. Do not use paper calibration as the default reported latency.
2. Always report raw CPU-derived FPGA latency:
   `raw_avg_iterations * 24 ns / rounds`.
3. Also report paper-calibrated latency as a secondary diagnostic column.
4. Explicitly check whether gross `144_12_12` raw iterations are close to the
   paper's 20 average iterations.
5. If the raw check fails, try closer FPGA-reference proxy modes instead of
   silently scaling the answer.

Run:

```bash
.venv/bin/python experiments/relaybp_latency_raw_vs_paper/run_experiment.py
```

The default experiment runs gross `144_12_12` X/Z at `p=0.001`, 1000 shots,
with these modes:

- `fp64_continuous`: repository float Relay-BP, continuous gamma.
- `fp64_beta8_gamma`: float Relay-BP with paper-style beta-int gamma grid
  `beta_int in [3,10]`, `gamma = 1 - beta_int/8`.
- `i64_scale2_int4_proxy`: repository integer Relay-BP with message scale 2
  and magnitude clip 15. This is only a repo-level proxy because the binding
  does not expose the paper's separate message scale `S=2` and memory scale
  `M=8`.
- `i64_scale8_wide_proxy`: repository integer Relay-BP with scale 8 and clip
  127, preserving memory-strength resolution better but no longer modeling
  `int4` message clipping.

The true paper FPGA reference still contains gateware-specific arithmetic,
especially the low-logic memory-strength multiply and sliding-window reference
implementation.  These proxy modes are useful to diagnose the gap, but they are
not a substitute for the authors' custom integer/windowing reference model.

## Paper-alignment switches

The experiment exposes the paper-sensitive parameters explicitly:

| Paper parameter | Switch |
| --- | --- |
| Relay-BP solution count `S` | `--relay-solutions 1` or `--stop-nconv 1` |
| `beta_int in [3,10]`, `M=8` | `--gamma-mode beta_int --beta-int-low 3 --beta-int-high 10 --memory-strength-scale 8` |
| `alpha(t)=1-2^-t` | `--alpha-mode paper_ramp` |
| closest exposed `int4.2.8` proxy | `--paper-int4-2-8-proxy` |

Shortcut:

```bash
--paper-low-latency-params
```

sets `S=1`, `beta_int in [3,10]`, `M=8`, and the paper alpha ramp.
The stronger

```bash
--paper-int4-2-8-proxy
```

also sets the I64 log-domain scale to 2 and clipping to 15.  This still does
not reproduce the full FPGA reference because the relay Python binding does not
expose the paper's low-logic memory-strength multiply or separate all hardware
integer paths.

## Current gross check

The best current repo-level proxy is `i64_scale8_wide_proxy`.  It does not
paper-scale the raw iteration count before the gross check.

With 5000 shots on `144_12_12` X/Z:

- raw average iterations: 21.139
- raw latency: 42.279 ns/round
- paper reference: 20 iterations, 40 ns/round
- relative error: 5.70%, so the raw check passes the 10% tolerance

This is the reason the `i64_scale8_wide_proxy` numbers below are treated as the
current usable estimates.  The `paper_calibrated_*` columns remain diagnostics,
not the primary result.

With the low-latency Relay-BP-1 shortcut:

```bash
.venv/bin/python experiments/relaybp_latency_raw_vs_paper/run_experiment.py \
  --codes BB144 \
  --modes i64_scale8_wide_proxy \
  --shots 1000 \
  --paper-low-latency-params \
  --output-csv experiments/relaybp_latency_raw_vs_paper/results_gross_paper_low_latency_i64_scale8_1000.csv
```

the gross code raw average is 4.844 iterations, or 9.688 ns/round.  This should
be compared with the paper's Relay-BP-1 low-latency statement of less than 10
iterations, not with the separate 20-iteration / 40 ns/round gross check.

## Gong-generated BB144 comparison

The relay-native `144_12_12` inputs under `tests/testdata/bicycle_bivariate/`
are left untouched.  A separate Gong-generated `144_12_12` input was generated
under `generated_bicycle_bivariate/`:

```bash
.venv/bin/python experiments/relaybp_latency_raw_vs_paper/generate_gong_bb_stim.py \
  --codes BB144
```

Run command for the 40 ns gross-runtime comparison:

```bash
.venv/bin/python experiments/relaybp_latency_raw_vs_paper/run_experiment.py \
  --testdata-dir experiments/relaybp_latency_raw_vs_paper/generated_bicycle_bivariate \
  --codes BB144 \
  --modes i64_scale8_wide_proxy \
  --shots 5000 \
  --skip-basis-filter \
  --output-csv experiments/relaybp_latency_raw_vs_paper/results_gong_bb144_i64_scale8_5000.csv
```

Measured at `p=0.001`, 5000 shots:

| Input | Basis | Raw avg iter | Raw ns/round |
| --- | --- | ---: | ---: |
| relay-native | X | 21.1530 | 42.306 |
| relay-native | Z | 21.6732 | 43.346 |
| Gong-generated | X | 19.6762 | 39.352 |
| Gong-generated | Z | 20.3766 | 40.753 |

The Gong-generated `144_12_12` average is 20.0264 iterations, or
40.053 ns/round, which is almost exactly the paper's 20-iteration /
40 ns/round gross-runtime target.

With `--paper-low-latency-params`, the Gong-generated `144_12_12` average is
4.277 iterations, or 8.554 ns/round.

## Requested BB sizes

Command used for the requested list:

```bash
.venv/bin/python experiments/relaybp_latency_raw_vs_paper/run_experiment.py \
  --codes BB72,BB90,BB108,BB144,BB288,BB360,BB648,BB756 \
  --modes i64_scale8_wide_proxy \
  --allow-missing \
  --output-csv experiments/relaybp_latency_raw_vs_paper/results_requested_bb_i64_scale8.csv
```

The relay repository's local `tests/testdata/bicycle_bivariate` inputs currently
contain only `72_12_6`, `144_12_12`, and `288_12_18` from this requested set.
The missing entries are written to
`results_requested_bb_i64_scale8_missing_inputs.csv`.

Measured at `p=0.001`, 1000 shots:

| Code | Basis | Rounds | Raw avg iter | Raw ns/round | Paper-cal ns/round |
| --- | --- | ---: | ---: | ---: | ---: |
| BB72 (`72_12_6`) | X | 6 | 10.508 | 42.032 | 39.385 |
| BB72 (`72_12_6`) | Z | 6 | 10.690 | 42.760 | 40.067 |
| BB144 (`144_12_12`) | X | 12 | 20.820 | 41.640 | 39.018 |
| BB144 (`144_12_12`) | Z | 12 | 21.868 | 43.736 | 40.982 |
| BB288 (`288_12_18`) | X | 18 | 38.190 | 50.920 | 47.714 |
| BB288 (`288_12_18`) | Z | 18 | 38.990 | 51.987 | 48.713 |

For this requested-list run, the gross `144_12_12` raw average is 21.344
iterations, or 42.688 ns/round.  That is 6.72% above the paper's 40 ns/round and
passes the 10% raw check.

Input status for the full requested set:

| Requested | Resolved label | Status |
| --- | --- | --- |
| BB72 | `72_12_6` | measured |
| BB90 | `90_8_10` | measured with Gong-generated `.stim` circuits |
| BB108 | `108_8_10` | measured with Gong-generated `.stim` circuits |
| BB144 | `144_12_12` | measured |
| BB288 | `288_12_18` | measured |
| BB360 | `360_12_24` | measured with generated `.stim` circuits |
| BB648 | `648_12_30` | measured with generated `.stim` circuits |
| BB756 | `756_16_34` | measured with generated `.stim` circuits |

## Gong-generated BB90 and BB108

`BB90` and `BB108` inputs were generated from Gong et al.'s
`SlidingWindowDecoder` circuit builder, using `p=0.001` and `rounds=d=10`.
The generated circuits are under `generated_bicycle_bivariate/`.

Generation command:

```bash
.venv/bin/python experiments/relaybp_latency_raw_vs_paper/generate_gong_bb_stim.py \
  --codes BB90,BB108
```

Run command:

```bash
.venv/bin/python experiments/relaybp_latency_raw_vs_paper/run_experiment.py \
  --testdata-dir experiments/relaybp_latency_raw_vs_paper/generated_bicycle_bivariate \
  --codes BB90,BB108 \
  --modes i64_scale8_wide_proxy \
  --output-csv experiments/relaybp_latency_raw_vs_paper/results_gong_bb90_bb108_i64_scale8.csv
```

Measured at `p=0.001`, 1000 shots:

| Code | Basis | Rounds | Raw avg iter | Raw window ns | Raw ns/round |
| --- | --- | ---: | ---: | ---: | ---: |
| BB90 (`90_8_10`) | X | 10 | 13.311 | 319.464 | 31.946 |
| BB90 (`90_8_10`) | Z | 10 | 14.436 | 346.464 | 34.646 |
| BB108 (`108_8_10`) | X | 10 | 15.901 | 381.624 | 38.162 |
| BB108 (`108_8_10`) | Z | 10 | 16.407 | 393.768 | 39.377 |

These rows intentionally do not include `paper_calibrated_*` values because the
Gong-generated input directory for this run contains only BB90 and BB108, not a
same-source BB144 gross check.  The primary latency remains the raw value.

## Generated BB360, BB648, and BB756

`BB360`, `BB648`, and `BB756` were generated into the same
`generated_bicycle_bivariate/` directory.  The generated files are already
single-basis `memory_X` or `memory_Z` circuits, so the large-code run uses
`--skip-basis-filter` to avoid an expensive detector sensitivity pass.

Generation command:

```bash
.venv/bin/python experiments/relaybp_latency_raw_vs_paper/generate_gong_bb_stim.py \
  --codes BB360,BB648,BB756
```

Run command:

```bash
.venv/bin/python experiments/relaybp_latency_raw_vs_paper/run_experiment.py \
  --testdata-dir experiments/relaybp_latency_raw_vs_paper/generated_bicycle_bivariate \
  --codes BB360,BB648,BB756 \
  --modes i64_scale8_wide_proxy \
  --shots 1000 \
  --skip-basis-filter \
  --output-csv experiments/relaybp_latency_raw_vs_paper/results_gong_bb360_bb648_bb756_i64_scale8.csv
```

Measured at `p=0.001`, 1000 shots:

| Code | Basis | Rounds | Raw avg iter | Raw window ns | Raw ns/round |
| --- | --- | ---: | ---: | ---: | ---: |
| BB360 (`360_12_24`) | X | 24 | 46.287 | 1110.888 | 46.287 |
| BB360 (`360_12_24`) | Z | 24 | 47.643 | 1143.432 | 47.643 |
| BB648 (`648_12_30`) | X | 30 | 68.392 | 1641.408 | 54.714 |
| BB648 (`648_12_30`) | Z | 30 | 70.370 | 1688.880 | 56.296 |
| BB756 (`756_16_34`) | X | 34 | 75.385 | 1809.240 | 53.213 |
| BB756 (`756_16_34`) | Z | 34 | 79.423 | 1906.152 | 56.063 |
