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
| BB360 | `360` | missing local `.stim` memory circuits |
| BB648 | `648` | missing local `.stim` memory circuits |
| BB756 | `756` | missing local `.stim` memory circuits |

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
