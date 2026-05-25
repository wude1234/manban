# Exploration Results Log

本文件记录已经验证过的探索发现、无效方向和下一步启发。原始 `demo/results/`
目录体积大且被 `.gitignore` 忽略，因此这里提交可复盘的轻量摘要；本机仍可按文中
路径查看完整 step/summary 文件。

## 2026-05-26 Snapshot

当前在 0509 数据上的最好 score profile 已更新为 v98：

```text
score_result_root = demo/results/grid_agentic_algo/20260526_001234_v98_submission_profile_check
score_profile = score_v98_root_idle_trap_teacher_315688
preset = submission_score_v98
```

| profile | 用途 | score | penalty | tokens | failed |
| --- | --- | ---: | ---: | ---: | ---: |
| `score_v98_root_idle_trap_teacher_315688` | 当前本地冲分/teacher 研究 | 315688.45 | 12865 | 0 | 0 |
| `score_v94_d001_step103_teacher_315167` | 历史稳定基线 | 315167.70 | 13165 | 0 | 0 |
| `official_clean_agentic_planner` | 官方合规方向 | 275973.46 | 17565 | 0 | 0 |

v98 单司机净收益：

| driver | net | penalty |
| --- | ---: | ---: |
| D001 | 18732.78 | 900 |
| D002 | 34189.64 | 0 |
| D003 | 35363.97 | 2000 |
| D004 | 39516.78 | 1500 |
| D005 | 28505.81 | 0 |
| D006 | 37010.05 | 5200 |
| D007 | 32527.88 | 0 |
| D008 | 36051.86 | 800 |
| D009 | 20051.77 | 900 |
| D010 | 33737.91 | 1565 |

## v98 Root-Order Idle Trap Distillation

v95-v97 证明了长等待 step 本身局部饱和：强制 query、单步替换、两步 sequence 在 D001/D005/D009 都没有正收益。v98 改成追溯“进入等待坑之前的真实订单”，新增 `analyze_idle_traps.py` 来生成：

```text
wait_step
previous_action
root_order_step
root_order_cargo
pickup/haul ratio
wait_minutes
root_trap_score
```

这次验证的关键发现：

| driver | root step | original | winner | delta | penalty change | finding |
| --- | ---: | --- | --- | ---: | ---: | --- |
| D001 | 106 | cargo208674 | wait180 | +146.10 | -300 | 月末低价值尾单不接，主动等 180 分钟换更好的收益/休息结构 |
| D009 | 190 | cargo475223 | cargo192513 | +200.31 | 0 | home/reposition 长等不是修 wait，而是修回家链之前的订单 |
| D010 | 43 | cargo50832 | cargo352638 | +174.34 | 0 | 第 10 天超长等待来自前置订单的后继状态价值差 |
| D005 | 107/116/120/125 | rule | rule | 0.00 | 0 | D005 尾部看似低效，但当前链路在可见候选中仍局部最优 |

组合验证：

```text
grid = hot_v98_root_idle_trap_teacher
score = 315688.45
penalty = 12865
result_dir = demo/results/grid_agentic_algo/20260526_000807_v98_root_idle_trap_combo/01_hot_v98_root_idle_trap_teacher
submission_profile_check = demo/results/grid_agentic_algo/20260526_001234_v98_submission_profile_check/01_submission_score_v98
```

算法启发：

```text
long_idle_step 本身常常已经是局部最优或无货可选。
真正的决策价值在 root_order 的 after_state：
  接完这单后，司机会不会被送进低机会时间窗/低后继区域/偏好返家链？

下一版 clean/agentic 算法应学习：
  V(after_unload_state) - idle_trap_risk
而不是把“弱区域/强区域”当主规则。
```

## 2026-05-25 Snapshot

当前在 0509 数据上的两套 profile 已做复现：

```text
score_result_root = demo/results/grid_agentic_algo/20260525_213043_v94_submission_profile_check
score_profile = score_v94_d001_step103_teacher_315167
clean_profile = official_clean_agentic_planner
```

| profile | 用途 | score | penalty | tokens | failed |
| --- | --- | ---: | ---: | ---: | ---: |
| `score_v94_d001_step103_teacher_315167` | 本地冲分/teacher 研究 | 315167.70 | 13165 | 0 | 0 |
| `official_clean_agentic_planner` | 官方合规方向 | 275973.46 | 17565 | 0 | 0 |

score profile 保留 full-tail 反事实回放蒸馏出的固定 teacher，用来做当前榜单最高收益验证。
clean profile 关闭固定 step/cargo/action teacher，只使用当前可观测状态、司机 memory、
route-plan scorer、偏好保护和在线动态空驶候选，是后续“不能用已知全局视角”时的主线。

## Current Best Breakdown

`score_v94_d001_step103_teacher_315167` 单司机净收益：

| driver | net | penalty |
| --- | ---: | ---: |
| D001 | 18586.68 | 1200 |
| D002 | 34189.64 | 0 |
| D003 | 35363.97 | 2000 |
| D004 | 39516.78 | 1500 |
| D005 | 28505.81 | 0 |
| D006 | 37010.05 | 5200 |
| D007 | 32527.88 | 0 |
| D008 | 36051.86 | 800 |
| D009 | 19851.46 | 900 |
| D010 | 33563.57 | 1565 |

## v95-v97 Value Dataset And Saturation Probe

本轮新增两个离线分析工具：

```text
demo/build_value_dataset.py
demo/analyze_value_dataset.py
```

它们把历史 `dynamic_summary.json`、`sequence_summary.json`、`beam_summary.json` 汇总成
`demo/results/value_dataset/value_dataset.jsonl` 和 `value_analysis.md`。当前已汇总：

```text
total_rows = 10919
labeled_dynamic_sequence_rows = 10804
positive_rows = 28
neutral_rows = 688
negative_rows = 10088
above_current_v94_driver_score = 0
```

核心发现：

1. 历史所有正样本都已经被当前 v94 吸收，没有任何分支超过当前对应司机净收益。继续在旧正样本附近加 teacher 已无边际收益。
2. 正样本极稀疏：D005/D009/D002/D003/D006 目前全是 `0` 个正样本；D001/D007/D010 的正样本也主要是已经提交的旧 teacher。
3. `dynamic_reposition` 的正样本率最高，但也只有约 `1.4%`，说明主动空驶只能作为候选生成器，不能作为泛化策略直接打开。
4. beam proxy 对 D009/D010/D006/D008/D001 严重高估，继续加宽 beam 不会自动冲高分，必须先修 preference/rest/fragmentation/value proxy。

为了验证“是不是 pre-query 休息/回家规则挡住了市场信息”，新增了 `--force-query-on-target`：

```text
dynamic_candidate_probe.py --force-query-on-target
sequence_counterfactual_probe.py --force-query-on-target
```

它只在被 probe 的目标 step 关闭 pre-query wait/reposition，强制先 `query_cargo`，prefix 和 tail 仍使用原策略。v96/v97 对 D001/D005/D009 的长等待/低效率热点测试结果：

| driver | probe | steps/pairs | best delta | finding |
| --- | --- | --- | ---: | --- |
| D001 | dynamic force-query | 95,100 | 0.00 | 月末长休息链已经最优，短等/空驶/top cargo 全负 |
| D001 | sequence force-query | 81:87,87:95,95:100 | 0.00 | 两步重排仍不超过 v94 |
| D005 | dynamic force-query | 92,107 | 0.00 | 当前低效率订单局部仍最优 |
| D005 | sequence force-query | 92:107,107:120,120:126 | 0.00 | 中后段路径重排无正收益 |
| D009 | dynamic force-query | 186,189 | 0.00 | 尾部夜间/回家规则附近是等价或负收益 |
| D009 | sequence force-query | 23:51,164:169,177:184,186:189 | 0.00 | 长等待节奏不能通过局部两步修复 |

这轮启发很重要：当前问题不是“某个等待点没看货”，而是司机已经被更早动作送入了低价值状态。
下一步高收益方向应从“修尾部动作”切到“修进入等待坑之前的动作”：

```text
state before long idle
+ previous cargo destination
+ next visible market after arrival
+ rest/preference debt
+ remaining month phase
=> value(after_state)
```

也就是学习 `V(after_state)`，再在接单时比较：

```text
current_net + V(after_unload_state) - preference_risk_delta - idle_trap_risk
```

`official_clean_agentic_planner` 的主要短板：

| driver | clean net | clean penalty | 现象 |
| --- | ---: | ---: | --- |
| D001 | 8608.38 | 5000 | 休息/机会窗口处理失败，是 clean 版最大缺口 |
| D004 | 33403.28 | 2400 | 缺少 schedule-aware route teacher，配额与后继链路没有被正确规划 |
| D006 | 30918.95 | 5200 | 罚分和 gross 链路仍在互相冲突，不能简单强制休息 |
| D007 | 27713.42 | 0 | 缺少高价值路径修复和动态空驶链 |
| D010 | 30138.34 | 1265 | 早期/尾部 route repair 尚未泛化 |

## v92 Dynamic Reposition Findings

v78-v89 之后，单步 top-k、value-k、wait、固定热点空驶基本进入平台期。v92 的新角度是：

```text
不再只重排已有 cargo 候选，
而是从当前可见货源的 pickup/end cluster 中生成在线 reposition 候选，
再用 full-tail 回放验证它是否真的改善月度路径。
```

已验证的正收益点：

| driver | step | action | score delta | penalty | 原始路径 |
| --- | ---: | --- | ---: | ---: | --- |
| D001 | 99 | reposition 到 `(22.81, 114.21)` | +47.88 | 900 | `demo/results/autonight_v92_D001_dynamic/dynamic_summary.md` |
| D007 | 114 | reposition 到 `(22.61, 112.78)` | +5.91 | 0 | `demo/results/autonight_v92_D007_dynamic_wide/dynamic_summary.md` |

D001 的启发：该步 rule 原本选择 `wait480`，但在线聚类生成的短空驶能进入更好的后继窗口。
这不是“强区域/弱区域”本身决定的，而是当前时间、当前位置、可见货源释放窗口和后续候选链
共同决定。

D007 的启发：收益很小但稳定，说明动态空驶可以作为 route-plan 的候选生成器。它真正的价值
不是泛泛地去热点，而是在关键尾部让后续 `cargo479939 -> cargo200448` 这类链路更顺。

负向/无效发现：

```text
D002 dynamic probe: no positive
D006 dynamic probe: no positive
D009 dynamic probe: no positive
D010 old dynamic probe: 早期结果受 persistent strategy state bug 影响，不作为有效发现
```

## Algorithm-Level Interpretation

1. 未来收益不能靠全局预知，只能用当前可见信息估计状态价值。
   目前最有效的 teacher 本质是 `V(after_state)` 的离线标签：一个动作当前可能不是最高 NPH，
   但完成后的位置、时间和偏好状态更好。

2. “强区域/弱区域”不是核心判据，只是状态价值的一部分。
   区域价值必须和时间窗、候选密度、空驶成本、司机偏好风险一起算；否则 broad market bonus
   会破坏已经验证的高收益链。

3. 单步 cargo rerank 已基本饱和。
   后续提升主要来自候选空间改变：wait 作为主动动作、reposition 作为主动动作、两步/三步
   route rebase、以及同司机路径互斥分支选择。

4. 司机必须独立画像。
   D004/D006 是偏好风险与收益链权衡；D009 多数时候值得支付回家罚分；D001/D010 更依赖
   时间窗口和休息/家事边界；D007/D008 更容易从尾部 route repair 获益。

5. LLM 的合理位置不是自由决策。
   Flash 应用于偏好解析、near-tie critic、轨迹总结和启发式生成；最终动作仍由确定性 scorer、
   calculator 和 safety executor 输出。

## Clean Profile Gap

当前 clean 版和 score 版差距约 `39112.29`，不是一个阈值能补齐。需要把 score profile 的固定
teacher 蒸馏成不含 step/cargo/id 的状态模式：

```text
driver_profile
+ time_window
+ location_region
+ visible_candidate_cluster
+ score_gap
+ destination_opportunity_value
+ preference_risk_delta
+ remaining_month_phase
```

优先蒸馏方向：

| priority | target | 原因 |
| --- | --- | --- |
| P0 | D001 休息/机会窗口 | clean 版 D001 掉分最大，说明休息调度不是普通 fallback |
| P0 | D004 schedule-aware route plan | 多个高分 teacher 来自配额、时间窗和后继链联合优化 |
| P1 | D010 route repair | 早期和尾部动作高度路径依赖，适合做 two-step gated rollout |
| P1 | D007/D008 tail repair | 已多次出现 wait/reposition 改变尾部链路的收益 |
| P2 | D006 rest-risk model | 不能强制休息，需要边际罚分成本模型 |

## What To Commit Versus What To Keep Local

已提交/应提交：

```text
demo/agent/**
demo/run_agentic_algo_grid.py
demo/SUBMISSION.md
demo/ALGORITHM_EXPLORATION.md
demo/EXPLORATION_RESULTS.md
AUTONIGHT_PLAN.md
```

不默认提交：

```text
demo/results/**
demo/server/data/**
demo/agent_agentic_backup/**
```

原因：`results` 和数据目录可能很大，且多为本机实验产物；团队同步时更需要的是可复现实验配置、
高分 preset、发现摘要和下一步方向。如果要给队友完整复查某一轮，可单独打包对应
`result_root`。

## Next Exploration

下一轮不是继续盲扫全局阈值，而是做两条线并行：

```text
score line:
  继续用 full-tail probe 找正收益 teacher，目标是继续冲当前数据高分。

clean line:
  把 teacher 解释为状态价值规则，验证是否能在 official_clean_agentic_planner 上涨分。
```

推荐优先级：

1. 对 D001 clean 的低机会窗口做 state-rule 蒸馏，判断何时主动短空驶/短等待优于长休息。
2. 对 D004 的 step11、49->56、93/94/96 三类 teacher 提取 schedule-aware 配额规则。
3. 对 D007/D008 月末尾部做 online dynamic reposition + gated rollout，而不是固定坐标。
4. 对 D010 早期 route repair 做 two-step branch selector，避免和已有路径互斥。
5. 记录每次正负样本的 `winner/loser/delta/penalty_delta/destination_value`，逐步形成 regret table。

## v93 Clean-Env Dynamic Probe

本轮先修复了一个重要 harness 问题：`counterfactual_rollout_probe.py` 原先总会把
`BASE_ENV` 混入 preset，而且直接加载 strategy 时不会触发 `agent.submission_defaults`。
这会导致 `submission_score_v92` 在 probe 里没有真正展开 v92 teacher，表现为 rule branch
无法复现 driver baseline。修复后，smoke check：

```text
D003 step100 rule branch = 35363.97
delta_vs_baseline = 0.0
```

因此后续 v93 结果口径有效。

本轮有效探索：

```text
profile = submission_score_v92
method = dynamic candidate generation from visible market
branches = top cargo + deep cargo + event waits + pickup/end/centroid reposition
drivers = D003,D004,D005,D008,D010
```

结果汇总：

| driver | steps | ok branches | best delta | positive branches | result |
| --- | --- | ---: | ---: | ---: | --- |
| D003 | 100,87,111 | 37 | 0.00 | 0 | `demo/results/autonight_v93_cleanenv_D003_dynamic/dynamic_summary.md` |
| D004 | 99,59,58 | 69 | 0.00 | 0 | `demo/results/autonight_v93_cleanenv_D004_dynamic/dynamic_summary.md` |
| D005 | 92,120,107 | 53 | 0.00 | 0 | `demo/results/autonight_v93_cleanenv_D005_dynamic/dynamic_summary.md` |
| D008 | 82,81,76 | 72 | 0.00 | 0 | `demo/results/autonight_v93_cleanenv_D008_dynamic/dynamic_summary.md` |
| D010 | 2,103,53 | 72 | 0.00 | 0 | `demo/results/autonight_v93_cleanenv_D010_dynamic/dynamic_summary.md` |

启发：

1. v92 后的高疑点局部状态已经很稳。对这些 step 增加深层 cargo、短等待、visible-market
   reposition 都没有超过当前 rule/teacher 分支。
2. D010 step103 再次证明“少罚分不等于高收益”。`cargo196038/200361` 罚分更低，但完整
   月度收益低于 v92 的 `cargo481074`，说明当前路径主动支付 300 罚分换更高 gross/路线价值是合理的。
3. D008 step81/82、D004 step99 的动态空驶大多只是增加距离或破坏月末链路，不能把
   “可见市场 cluster” 直接当作强区域规则。
4. 下一步不应继续在同一批 top suspicious steps 上扩分支。更高价值方向是：
   clean profile 蒸馏、同司机更深 sequence rebase、以及从 score/clean 差异最大司机 D001/D004
   提取状态规则。

## v94 Higher-Score Exploration

本轮目标是继续冲高分，先补跑 v93 未覆盖司机，再切到 two-step sequence rebase：

```text
dynamic drivers = D001,D002,D006,D007,D009
sequence drivers = D001,D002,D007
validated score preset = submission_score_v94
validated result = demo/results/grid_agentic_algo/20260525_213043_v94_submission_profile_check/01_submission_score_v94
```

动态候选结果：

| driver | best delta | positive branches | finding |
| --- | ---: | ---: | --- |
| D001 | +81.95 | 4 | step103 `cargo202502` 是新正收益点 |
| D002 | 0.00 | 0 | 月末/长途高疑点局部已稳 |
| D006 | 0.00 | 0 | 偏好罚分仍值得支付，强改休息/空驶无收益 |
| D007 | 0.00 | 0 | v92 后尾部动态空驶已无新增 |
| D009 | 0.00 | 0 | 多个 wait/reposition 只是等价 no-op 或负收益 |

sequence rebase 结果：

| driver | best delta | finding |
| --- | ---: | --- |
| D001 | +81.95 | 与 dynamic 相同，来自 `pair_100_103/f01_wait_480__s03_cargo_202502` |
| D002 | 0.00 | 无新增 |
| D007 | 0.00 | 无新增 |

v94 的核心启发：

1. D001 step103 证明“休息偏好也不能硬满足”。原策略在 03-30 01:02 后 `wait480`，罚分较低；
   改接 `cargo202502` 会额外增加 300 休息罚分，但 gross 和后续短链收益覆盖罚分，总分 +81.95。
2. 这不是当前单贪心，而是月末尾链价值：`cargo202502 -> cargo203175 -> cargo485616` 比长休息后
   再进入尾链更好。
3. v94 也进一步确认 D002/D006/D007/D009 的高疑点状态已局部饱和；下一步要找更早的 route-plan
   重排或转向 clean-profile 状态规则蒸馏，而不是继续在同一批 step 加 deep cargo。

## Why Small Teacher Gains Are Saturating

当前从 `315167.70` 追到 `340000+` 的差距是两万级，不能靠每次 `+50/+100` 的窄
teacher 点堆出来。v95 诊断显示真正瓶颈在搜索目标函数，而不是人工试得不够多。

当前 v94 轨迹的结构性低效：

| driver | symptom |
| --- | --- |
| D001 | 等待约 12990 分钟，pickup/haul = 0.62，路线链价值低 |
| D005 | 等待约 13449 分钟，pickup/haul = 0.64，短货源链容易被低价值等待锁死 |
| D009 | 102 次 reposition、等待约 16504 分钟，回家/等待边界很多动作只是 no-op |

修复了 `offline_beam_planner.py` 的 profile 口径后，重新用 `submission_score_v94`
跑整段 beam smoke：

| driver | current net | beam best exact | finding |
| --- | ---: | ---: | --- |
| D001 | 18586.68 | 17172.81 | proxy 偏好 gross 链，忽略休息罚分和碎片等待，exact 反而下降 |
| D005 | 28505.81 | 25113.44 | proxy 诱导大量 60 分钟等待和低质量短链 |
| D009 | 19851.46 | -8187.98 | proxy 完全没有刻画回家/偏好罚分，路线崩坏 |

结论：

1. 宽 beam 本身不是答案。没有可靠 value/proxy，搜索越宽越可能找到“proxy 高但 exact 低”的坏路线。
2. 下一步高收益方向应该是 `preference-aware value function`，而不是继续手工加单点 teacher。
3. 具体实现应先从历史 exact-tail 结果拟合局部价值：`score_delta = f(driver, time, location, wait, pickup_ratio, destination_value, preference_state)`。
4. 再让 beam 用这个 value function 排序，而不是只用 `price - distance_cost - 0.02*wait`。
5. 一旦 value function 能让 beam 的 top candidates 至少不低于当前 rule，才值得扩大搜索宽度。
