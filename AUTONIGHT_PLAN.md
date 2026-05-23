# Autonight Exploration Plan

## How To Resume

新对话开始时先读取本文件，再读取：

- `demo/ALGORITHM_EXPLORATION.md`
- `demo/SUBMISSION.md`
- `demo/agent/submission_defaults.py`
- `demo/run_agentic_algo_grid.py`

本文件是夜间自动探索的状态锚点。若和其他文档冲突，以本文件的 `Current Best` 和 `Active Experiments` 为准。

## Current Best

```text
version = v53 candidate
preset = hot_v53_d00880_wait240
score = 309601.27
penalty = 12165
run_dir = demo/results/grid_agentic_algo/20260523_092432_submission_v53_check/01_hot_v53_d00880_wait240
commit = not committed yet, v48 commit remains aa2ae28
```

核心发现：

```text
Phase-level action gate > cargo-only rerank
wait / take_order / reposition 必须作为同级动作做 full-tail rollout
同司机内部正样本不能贪心叠加，必须做路径 rebase
跨司机正样本通常可以组合，但仍需完整月度验证
query 后状态会造成 trace step time 与 agent decision time 错位，phase guard 需要足够宽但仍由候选货源/位置约束兜底
action-level teacher must override older cargo-level switch on the same driver/step
```

## Active Experiments

当前正在基于 v52 best 准备下一轮 rebase：

```text
grid_tag = next rebase pending
status = v53 grid completed
purpose = continue from v53 best; D008 step80 wait240 is promoted
previous_grid = demo/results/grid_agentic_algo/20260523_090528_autonight_v53_priority_fix
```

上一轮基于 v48 best 并行探索 5 条线，均已完成：

```text
D010 after step100 wait rebase
results/autonight_v48_d010_after_wait_rebase

D004 after step87 cargo rebase
results/autonight_v48_d004_after_step87_rebase

D006 phase waits / reposition
results/autonight_v48_d006_phase_waits

D001 phase waits / reposition
results/autonight_v48_d001_phase_waits

D008 phase actions
results/autonight_v48_d008_phase_actions
```

## Completed Results

### v48 rebase / phase probes

```text
D010 step101: +250.14, take 290609 instead of 290384, penalty 1265 -> 965
D004 step93: +25.42, take 469204 instead of 468269
D004 step95: +290.03, reposition to GZ instead of wait64; more gross and less distance, penalty +200
D004 step96: +212.09, reposition to FS instead of cargo 189146
D006 step65: +89.45, wait300 instead of cargo 424880; penalty 5200 -> 5000
D006 step95: +366.98, reposition to FS instead of cargo 202939
D001 step77: +66.46, wait300 instead of cargo 145964; penalty 1200 -> 900
D001 step93: +53.06, wait60 instead of cargo 469532
D001 step98: +183.62, reposition to SZ instead of cargo 477985; penalty 1200 -> 900
D001 step102: +243.64, wait180 instead of cargo 484350; penalty 1200 -> 900
D008 phase actions: no positive action found
```

Interpretation:

```text
新的增长点不是调 cargo score 参数，而是 action arbitration。
wait / reposition 能改变后续货源链，且收益来源常是少罚分、少尾部空驶或进入更好时间窗。
D004/D006 的主动空驶开始出现正样本，说明“位置价值”不是核心打分项，但可作为关键分叉动作。
D001 的等待正样本更多像偏好/日程边界修正，必须同司机组合验证，不能直接全部叠加。
D006 step65 会和旧 counterfactual cargo switch 冲突，v49 通过显式 override gate 处理。
```

### v49 implementation

```text
file = demo/agent/feature_strategies/new_release_agentic_planner_agent.py
added = narrow phase gates for D010101, D00493/95/96, D00665/95, D00177/93/98/102
guard = driver + step + day + minute window + location radius + visible winner/loser cargo
guard_fix = D010101 min minute 17:35; D00495 no longer requires no viable cargo

file = demo/run_agentic_algo_grid.py
added = _v49_autonight_env and hot_v49_* presets
```

### v49 first full-grid result

```text
grid = demo/results/grid_agentic_algo/20260523_042951_autonight_v49_gate_check
best = hot_v49_d00695_d001102
score = 308281.27
delta_vs_v48 = +610.62
penalty = 12165
```

Findings:

```text
D00695 single = +366.98, strong active reposition signal.
D001102 single = +243.64, strongest D001 wait signal.
D00695 + D001102 stacks exactly to new best.
D00665 + D00695 stacks within D006, but was not yet combined with D001102 in first grid.
D00496 single = +212.09, not yet tested with current best in first grid.
D00493 single = +25.42, small but stable.
D010101 and D00495 initially did not trigger because guards were too narrow; now fixed and under refine.
D001 same-driver late gates do not stack naively; earliest branch changes later target states.
```

### v49 refine result

```text
grid = demo/results/grid_agentic_algo/20260523_051634_autonight_v49_refine_stack
best = hot_v49_d00665_d00695_d001102_d00496
score = 308582.81
delta_vs_v48 = +912.16
penalty = 11965
```

Promoted v49 stack:

```text
D006 step65 wait300
D006 step95 reposition FS
D001 step102 wait180
D004 step96 reposition FS
```

Refine findings:

```text
D00496 stacks with current best and is better than D00493/D00495 in promoted combination.
D00495 fixed is valid but conflicts with D00496 path; not promoted.
D010101 remains no-op in full grid, likely because winner cargo 290609 is not visible/selectable under the full environment path.
```

### v49 best-path rebase

```text
D004 after step96: no positive full-tail branch in steps 97-104.
D001 after step102: no positive full-tail branch in steps 103-106.
D006 after step95: positive tail candidates found.
```

D006 tail candidates on v49 best:

```text
step97 wait300: +29.85
step98 cargo 484278 over 200255: +186.88
step99 reposition GZ over 485299: +144.74
step100 wait30 over wait60: +6.32
```

These are same-driver tail choices; v50 must validate compatibility before promotion.

### v50 result

```text
grid = demo/results/grid_agentic_algo/20260523_055919_autonight_v50_d006_tail
best = hot_v50_d00698_484278
score = 308769.69
delta_vs_v49 = +186.88
penalty = 12165
```

v50 findings:

```text
D006 step98 cargo484278 is the best compatible D006 tail repair.
D006 step97 wait300 is positive alone but blocks step98; not promoted.
D006 step99/100 are no-op after full-grid validation or absorbed by step98.
Current default submission profile updated to v50_phase_gate_agentic_planner_308769.
```

### v51 result

```text
grid = demo/results/grid_agentic_algo/20260523_063858_autonight_v51_multi_tail
best = hot_v51_d003107
score = 309057.58
delta_vs_v50 = +287.89
penalty = 12165
```

v51 findings:

```text
D003 step107 wait60 is the only full-grid promoted multi-driver tail gate.
D003 step110 is positive alone but blocked by step107 path shift.
D010/D007/D005 single-driver positives did not trigger in full-grid guarded validation.
Current default submission profile updated to v51_phase_gate_agentic_planner_309057.
```

### v52 result

```text
grid = demo/results/grid_agentic_algo/20260523_073844_autonight_v52_relaxed_tail
best = hot_v52_relax_all_alt
score = 309373.04
delta_vs_v51 = +315.46
penalty = 12165
```

v52 single-driver findings:

```text
D010 step121 wait60: +182.48
D010 step123 cargo205150: +182.48
D007 step114 cargo193118: +57.18
D007 step119 wait30: +76.81
D007 step121 reposition FS: +129.81
D005 step123 cargo194561: +0.00 on current full-grid path
D005 step128 reposition FS: +56.17
```

v52 combination findings:

```text
hot_v52_relax_all_best = D010121 + D007121 + D005123 = 309369.87
hot_v52_relax_all_alt = D010123 + D007119 + D005128 = 309373.04
```

Interpretation:

```text
之前 D010/D007/D005 的 single-driver positives 在 v51 full-grid 中没有触发，主要不是动作无效，而是 narrow guard 错过 query 后真实决策时间。
v52 使用更宽日内 phase window + 位置半径 + visible loser/winner cargo 做安全触发，能恢复这些正收益动作。
D010121 与 D010123 等价；最终选 D010123 是因为它和 D007119/D005128 组合略高。
D007121 单点更高，但与 D005128 组合后略低于 D007119+D005128，说明跨司机虽然大多独立，也仍需完整月度组合验证。
Current default submission profile updated to v52_phase_guard_agentic_planner_309373.
```

### v53 active probes

Based on v52 best, four full-tail probes completed:

```text
D001 late probe: no positive actions in steps 93/94/98-105.
D006 tail probe: step99 cargo208042 over cargo208263 = +50.83, gross -43.07, distance -62.60, penalty unchanged.
D008 late probe: step80 wait240 over cargo178320 = +228.23; step87 cargo203124 over wait240 = +205.71 but penalty +200; step88 wait60 over cargo205543 = +151.02.
D009 home-loop probe: step178 reposition HY over wait120 = +118.98, gross +411.42, distance +194.96, penalty unchanged.
```

Interpretation:

```text
D001 late tail is currently saturated; do not spend more search there until a new base path changes it.
D006 penalty remains high but tail alternatives mostly lose; the only positive is a small lower-distance cargo replacement.
D008 is again a strong planning driver. However step80/87/88 are same-driver alternatives and must be full-grid validated before promotion.
D009 repeated home reposition is not obviously wasteful: many replacements are exactly equal or negative. Only one controlled HY reposition at step178 is positive.
```

Active v53 grid:

```text
tag = autonight_v53_late_actions
purpose = validate D008 same-driver alternatives and D009/D006 cross-driver stack on v52 best.
candidate presets = hot_v53_d00880_wait240, hot_v53_d00887_203124, hot_v53_d00888_wait60, hot_v53_d009178_repos_hy, hot_v53_d00699_208042, combinations.
```

### v53 result

```text
grid = demo/results/grid_agentic_algo/20260523_090528_autonight_v53_priority_fix
validation = demo/results/grid_agentic_algo/20260523_092432_submission_v53_check/01_hot_v53_d00880_wait240
best = hot_v53_d00880_wait240
score = 309601.27
delta_vs_v52 = +228.23
penalty = 12165
```

v53 findings:

```text
D008 step80 wait240 is promoted. It waits instead of taking cargo178320 and then connects to cargo301080/302683 style higher-value chain.
D009 step178 HY reposition is not promoted. It scored +118.98 in local probe but full-grid with existing D009 wait teacher drops -28.58.
D006 step99 cargo208042 is not promoted. It is no-op in full-grid on v53 base.
D008 step87/88 are same-driver alternatives and were not promoted before rebase on D00880.
```

Important implementation discovery:

```text
D008 step80 initially did not trigger because old cargo-level counterfactual switch D008:80:178320 returned before the new wait gate.
Fix: _counterfactual_switch_overridden now lets D008 step80 wait override the older cargo switch.
This is an Agent safety/execution-layer rule: higher-level action teachers must arbitrate against lower-level cargo memory, not be appended after them.
Current default submission profile updated to v53_priority_agentic_planner_309601.
```

### D008 phase actions

```text
status = completed
result_dir = demo/results/autonight_v48_d008_phase_actions
finding = no positive action found
```

Interpretation:

```text
v48/v40 已经保护住 D008 step62/80/85 等关键链路。
本轮在 step62,70,75,80,85,90,95,100 探索 top-k cargo、wait、reposition，最优均为 rule action。
D008 暂时不是下一轮主攻方向。
```

## Decision Rules

1. 每个 probe 完成后，用 `counterfactual_summary.json` 计算每个 target step 相对 rule action 的 delta。
2. 只考虑完整尾部回放正收益动作；优先选择每个司机最早的正收益分叉。
3. 同一司机内后续正收益必须在新路径上重新 probe，不能直接叠旧路径样本。
4. 跨司机正收益先做小组合网格，再决定是否进入新版本 preset。
5. 新版本必须超过 `307670.65` 才更新 `SUBMISSION.md` 和 `submission_defaults.py`。
6. 今晚默认不做 git commit，除非用户回来明确允许；代码和文档可先落盘。

## Candidate Implementation Pattern

若发现稳定正样本，在：

```text
demo/agent/feature_strategies/new_release_agentic_planner_agent.py
```

新增窄触发函数：

```text
driver_id + step + time window + location radius + visible winner/loser + numeric guard
```

然后在：

```text
demo/run_agentic_algo_grid.py
```

新增 v49 preset，不直接覆盖 v48 默认，先跑组合验证。

## Next Analysis Template

对每批结果写：

```text
driver
target_step
rule_action
best_action
delta_score
penalty_delta
gross_delta
distance_delta
why_it_wins
whether_stackable
next_probe_base
```

## Overnight Goal

在 5 小时自动探索窗口内，至少完成：

```text
1. v48 后继路径 rebase probes
2. 第一批正收益动作筛选
3. v49 candidate gates
4. v49 full-month combination grid
5. 若 v49 有新高，更新提交默认和探索文档
6. 若没有新高，写清负结果和下一步方向
```
