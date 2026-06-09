# Relay-BP FPGA 延迟 CPU 模拟结果汇总

本文档汇总本轮 Relay-BP FPGA 延迟估计实验。目标是用 CPU 跑
Relay-BP 行为模型，估计 FPGA 上的 `ns/round`，并检查论文中的
`gross code` 是否能和 `40 ns/round` 对上。

这里的 `gross code` 不是形容词，而是论文里的码名，指
`[[144,12,12]]` bivariate bicycle code。论文也把它放在 Kookaburra
memory experiment 的上下文中讨论。

## 结论摘要

- 当前最可信的主结果列是 `raw_cpu_latency_ns_per_round`。
- `paper_calibrated_latency_ns_per_round` 只是诊断列。
- 使用 `i64_scale8_wide_proxy` 模式时，gross code `144_12_12` 的 raw 结果
  已经接近论文值，不是通过缩放凑出来的。
- 5000-shot gross code 校验结果：
  - raw 平均迭代数：`21.139`
  - raw 延迟：`42.279 ns/round`
  - 论文参考：`20 iterations`，`40 ns/round`
  - 相对误差：`5.70%`
- 因此当前模型可以作为后续 BB code size 的近似延迟估计基线。
- BB90 和 BB108 已用 Gong 代码中的 Stim circuit 生成器补齐输入并完成测试。
- BB360 和 BB756 的 Gong 参数已找到，但还没有生成/测试；BB648 还缺 A/B 参数。

## 实验口径

统一设置：

- 物理错误率：`p = 0.001`
- window size：按 `W = d` 处理
- FPGA iteration time：`24 ns/iteration`
- 主要 decoder 模式：`i64_scale8_wide_proxy`
- 每个测试项：`1000 shots`，gross code 稳定性检查额外跑了 `5000 shots`

raw 延迟公式：

```text
raw_cpu_window_latency_ns = raw_avg_iterations * 24 ns
raw_cpu_latency_ns_per_round = raw_avg_iterations * 24 ns / rounds
```

论文校准列的定义：

```text
scale = 20 / gross_144_raw_avg_iterations
paper_calibrated = raw_latency * scale
```

也就是说，paper-calibrated 列回答的是：
“如果强制让 gross code 等于论文的 20 iterations / 40 ns/round，其他数值会是多少？”
它不能作为独立预测结果。严谨口径应优先看 raw。

## 论文对齐检查

论文的关键口径是：

- sliding window 的 `W` 固定为裸码距 `d`
- gross code 使用 `W = 12`
- gross code 的 split X/Z Relay-BP decoder 每个 BP iteration 是 `24 ns`
- 在 `p = 10^-3` 时平均大约 `20 iterations`
- 因此 `20 * 24 ns / 12 = 40 ns/round`

本实验的 5000-shot gross code raw 检查：

| Code | Basis | Rounds | Raw avg iter | Raw window ns | Raw ns/round |
| --- | --- | ---: | ---: | ---: | ---: |
| BB144 | X | 12 | 21.1066 | 506.558 | 42.213 |
| BB144 | Z | 12 | 21.1720 | 508.128 | 42.344 |

X/Z 加权平均：

```text
raw_avg_iterations = 21.139
raw_latency = 42.279 ns/round
relative_error_to_40ns = 5.70%
```

这个结果说明 raw 模型本身已经接近论文，不需要默认 scale iteration count。

## 已测结果

### relay 原生输入

这些输入来自 relay 仓库本身的 `tests/testdata/bicycle_bivariate`。

命令：

```bash
.venv/bin/python experiments/relaybp_latency_raw_vs_paper/run_experiment.py \
  --codes BB72,BB90,BB108,BB144,BB288,BB360,BB648,BB756 \
  --modes i64_scale8_wide_proxy \
  --allow-missing \
  --output-csv experiments/relaybp_latency_raw_vs_paper/results_requested_bb_i64_scale8.csv
```

relay 原生输入里，目标列表中只有 BB72、BB144、BB288 有 `.stim` 输入。

| Code | Basis | Rounds | Raw avg iter | Raw window ns | Raw ns/round | Paper-cal ns/round |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| BB72 | X | 6 | 10.508 | 252.192 | 42.032 | 39.385 |
| BB72 | Z | 6 | 10.690 | 256.560 | 42.760 | 40.067 |
| BB144 | X | 12 | 20.820 | 499.680 | 41.640 | 39.018 |
| BB144 | Z | 12 | 21.868 | 524.832 | 43.736 | 40.982 |
| BB288 | X | 18 | 38.190 | 916.560 | 50.920 | 47.714 |
| BB288 | Z | 18 | 38.990 | 935.760 | 51.987 | 48.713 |

按 X/Z 简单平均的 raw ns/round：

| Code | Avg raw ns/round |
| --- | ---: |
| BB72 | 42.396 |
| BB144 | 42.688 |
| BB288 | 51.453 |

注意：BB72 的 `ns/round` 不一定低于 BB144。BB72 的整窗延迟
约 `252-257 ns`，确实比 BB144 的 `500-525 ns` 小很多；但是除以
`rounds = W = d` 后，`ns/round` 数值会变得接近。

### Gong 生成输入

BB90 和 BB108 在 relay 原生输入中没有 `.stim` 文件。本轮用 Gong
代码中的 `SlidingWindowDecoder` 生成器补齐了这两个输入。

生成脚本：

```bash
.venv/bin/python experiments/relaybp_latency_raw_vs_paper/generate_gong_bb_stim.py \
  --codes BB90,BB108
```

测试命令：

```bash
.venv/bin/python experiments/relaybp_latency_raw_vs_paper/run_experiment.py \
  --testdata-dir experiments/relaybp_latency_raw_vs_paper/generated_bicycle_bivariate \
  --codes BB90,BB108 \
  --modes i64_scale8_wide_proxy \
  --output-csv experiments/relaybp_latency_raw_vs_paper/results_gong_bb90_bb108_i64_scale8.csv
```

参数：

| Code | l | m | A | B | d / rounds |
| --- | ---: | ---: | --- | --- | ---: |
| BB90 | 15 | 3 | `x^9 + y + y^2` | `1 + x^2 + x^7` | 10 |
| BB108 | 9 | 6 | `x^3 + y + y^2` | `y^3 + x + x^2` | 10 |

结果：

| Code | Basis | Rounds | Raw avg iter | Raw window ns | Raw ns/round |
| --- | --- | ---: | ---: | ---: | ---: |
| BB90 | X | 10 | 13.311 | 319.464 | 31.946 |
| BB90 | Z | 10 | 14.436 | 346.464 | 34.646 |
| BB108 | X | 10 | 15.901 | 381.624 | 38.162 |
| BB108 | Z | 10 | 16.407 | 393.768 | 39.377 |

按 X/Z 简单平均的 raw ns/round：

| Code | Avg raw ns/round |
| --- | ---: |
| BB90 | 33.296 |
| BB108 | 38.770 |

这些行没有同源 `paper_calibrated_*` 值，因为本次 Gong 输入目录只生成了
BB90 和 BB108，没有同时生成同来源的 BB144 gross code 校准点。为了避免混用来源，
这里保留 raw 结果为主。

## 未完成输入

当前目标列表状态：

| Code | 状态 |
| --- | --- |
| BB72 | relay 原生 `.stim` 已测 |
| BB90 | Gong 生成 `.stim` 已测 |
| BB108 | Gong 生成 `.stim` 已测 |
| BB144 | relay 原生 `.stim` 已测，并通过论文 gross code 检查 |
| BB288 | relay 原生 `.stim` 已测 |
| BB360 | Gong 代码有参数，但尚未生成/测试 |
| BB648 | 可能为 `[[648,12,30]]`，但仍缺 A/B 参数和 `.stim` 输入 |
| BB756 | Gong 代码有参数，但尚未生成/测试 |

已找到但尚未测试的 Gong 参数：

| Code | l | m | A | B | 距离注释 |
| --- | ---: | ---: | --- | --- | --- |
| BB360 | 30 | 6 | `x^9 + y + y^2` | `y^3 + x^25 + x^26` | `[[360,12,<=24]]` |
| BB756 | 21 | 18 | `x^3 + y^10 + y^17` | `y^5 + x^3 + x^19` | `[[756,16,<=34]]` |

BB360/BB756 的距离注释是 `<=24`、`<=34`，不像 BB90/108 那样明确写成
`d=10`。如果继续跑，需要先决定是否按 `W=24`、`W=34` 作为 rounds。

## 文件位置

- 实验脚本：`experiments/relaybp_latency_raw_vs_paper/run_experiment.py`
- Gong 输入生成脚本：`experiments/relaybp_latency_raw_vs_paper/generate_gong_bb_stim.py`
- relay 原生输入结果：`experiments/relaybp_latency_raw_vs_paper/results_requested_bb_i64_scale8.csv`
- Gong BB90/108 结果：`experiments/relaybp_latency_raw_vs_paper/results_gong_bb90_bb108_i64_scale8.csv`
- 5000-shot gross code 检查：`experiments/relaybp_latency_raw_vs_paper/results_gross_i64_scale8_5000.csv`
- Gong 生成的 `.stim`：`experiments/relaybp_latency_raw_vs_paper/generated_bicycle_bivariate/`
