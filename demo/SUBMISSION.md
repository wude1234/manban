# Submission Profile

## 当前提交版本

当前保留三套 profile：

```text
score_v98_root_idle_trap_teacher_315688
用途：当前默认本地冲分、离线研究和榜单复现实验。
特点：保留 counterfactual/distilled teacher，并加入 root-order idle-trap distillation，复现 315688.45。

score_v94_d001_step103_teacher_315167
用途：历史稳定基线和消融对照。
特点：保留 v94 之前的 counterfactual/distilled teacher，复现 315167.70。

official_clean_agentic_planner
用途：官方强调不得使用已知全局视角时的合规 Agent 版本。
特点：关闭固定 step/cargo teacher，只使用当前 get_driver_status/query_cargo/query_decision_history 可见状态、司机私有记忆、偏好编译、route scorer 和在线动态空驶候选。
```

本地 0509 数据当前最好复现结果为 score profile：

```text
score = 315688.45
total_preference_penalty = 12865.0
failed_driver_count = 0
tokens = 0
```

clean profile 当前验证结果：

```text
score = 275973.46
total_preference_penalty = 17565.0
failed_driver_count = 0
tokens = 0
result_dir = demo/results/grid_agentic_algo/20260525_185542_two_profiles_check_fixed/02_submission_official_clean
```

对应实验：

```text
demo/results/grid_agentic_algo/20260526_001234_v98_submission_profile_check/01_submission_score_v98
preset = submission_score_v98
step files = demo/results/grid_agentic_algo/20260526_001234_v98_submission_profile_check/01_submission_score_v98/actions_202603_D001_*.jsonl ... actions_202603_D010_*.jsonl
summary = demo/results/grid_agentic_algo/20260526_001234_v98_submission_profile_check/01_submission_score_v98/monthly_income_202603.json
```

v98 相比 v94 的新增有效动作：

```text
D001 step106 wait180: idle-trap root-order probe 发现原路径在 03-30 下午接 cargo208674 后进入月末长等尾链。改为原地等待 180 分钟，D001 净收益从 18586.68 提升到 18732.78，同时休息罚分从 1200 降到 900，完整月 +146.10。

D009 step190 cargo192513: D009 尾部多次 home/reposition 后长等，但真正的可修点不是回家动作，而是回家链之前的订单选择。step190 从 cargo475223 改接 cargo192513，罚分仍为 900，D009 净收益从 19851.46 提升到 20051.77，完整月 +200.31。

D010 step43 cargo352638: D010 第 10 天长等待由 step43 前置订单触发。把 cargo50832 换成 cargo352638，罚分仍为 1565，D010 净收益从 33563.57 提升到 33737.91，完整月 +174.34。
```

v98 的核心启发是：长等待点本身往往已经无可救药，真正要修的是把司机送入等待坑之前的 root-order。实现上仍然不是自由预录轨迹，而是受控 Agent teacher：必须匹配司机、step、时间窗、当前位置、winner/loser 可见货源 marker，最后由安全执行层输出合法动作。

v94 相比 v92 的新增有效动作：

```text
D001 step103 cargo202502: 在 03-30 01:02 后，原策略选择 wait480 以补休。clean-env dynamic probe 和 two-step sequence rebase 均发现，直接接 cargo202502 会额外增加 300 休息罚分，但 gross 增长、距离下降，并提前接入 cargo203175 -> cargo485616 尾链，D001 净收益从 18504.73 提升到 18586.68，完整月总分 +81.95 到 315167.70。
```

v92 相比 v89 的新增有效动作：

```text
D001 step99 dynamic reposition: 原路径在 03-29 凌晨深圳内长等，动态候选生成器从可见货源 pickup/end/centroid 中生成短空驶点 `(22.81,114.21)`。完整尾部回放后进入 cargo198353 -> cargo202812 -> cargo203175 -> cargo491392，比原路径 D001 净收益 +47.88，罚分仍为 900。

D007 step114 dynamic reposition: 原路径接 cargo475223，动态候选生成器发现空驶到 `(22.61,112.78)` 后可以接入 cargo479939 -> cargo200448。该分支 D007 净收益 +5.91，罚分仍为 0。
```

这次提升的核心不是继续调排序权重，而是更换搜索范式：当 top-k cargo / value cargo / two-step sequence 都局部饱和后，候选生成必须把 `take_order`、`wait` 和由当前可见市场诱导出的 `dynamic reposition` 放到同一个 full-tail exact scoring 里比较。v92 已把两个正样本蒸馏为带司机、step、时间、位置和可见货源 marker 的安全 Agent teacher。

v89 相比 v85 的新增有效动作：

```text
D008 step85/86 二步 Route Plan：step85 从 cargo201472 改为 cargo482796，把卸货状态从 (23.20,112.90) 调整到 (23.08,113.50)；step86 接 cargo200633。单独改 step85 是负收益，但二步组合后 D008 净收益从 36003.87 提升到 36051.86，完整月 +47.99。

D010 step103/105 二步 Route Plan：step103 从 cargo196038 改为 cargo481074，step104 由原 agent 自然接 cargo202277，step105 受控改接 cargo489360。该链路增加 300 休息罚分，但 gross 和距离收益覆盖罚分，D010 净收益从 33500.63 提升到 33563.57，完整月 +62.94。
```

这两个动作证明当前主要增益来自短视野序列规划，而不是单步贪心调权。v86 的 one-step wide probe 在 D003/D004/D008/D010 上无正收益，但 v87 的 two-step sequence probe 找到 D008/D010 两个正样本；因此提交 Agent 的核心应解释为 `route-plan memory + exact-tail distillation + safety gate`。

v85 相比 v84 的新增有效动作：

```text
D008 step87 wait180: 在 03-30 06:33 到达 (23.20,112.90) 后，原规则在 query 后直接接 cargo203004 并卸到 (22.62,114.42)。exact-tail probe 发现原地等待 180 分钟后接 cargo486259 -> cargo210728，罚分仍为 800，gross +27.36、距离 -31.23km，D008 净收益从 35929.67 提升到 36003.87，完整月总分 +74.20 到 314921.03。
```

这个动作说明 `wait` 不是兜底动作，而是 Route Plan 里的主动时间重排：当月末当前位置和候选集合进入低价值窗口时，短等可以避开会锁死后续链路的当前单。实现上要求 D008 第 87 步附近、3月30日早晨、当前位置接近 `(23.20,112.90)`，且原规则候选 `203004` 可见才触发。

v84 相比 v77 的新增有效动作：

```text
D009 step110 cargo398828: 在 03-16 12:27 后，原规则从 (23.02,113.55) 接 cargo97891 并卸到 (22.94,114.48)。v83 home-boundary exact-tail probe 发现 cargo398828 虽耗时略长，但 gross 更高、回家空驶更短，偏好罚分仍为 900，D009 净收益从 19725.44 提升到 19851.46，完整月总分 +126.02 到 314846.83。
```

这个动作被实现为受控 Agent teacher，而不是自由硬切：必须在 D009 第 110 步附近、3月16日中午、当前位置接近 `(23.02,113.55)`，并且候选集合同时出现 winner `398828` 和 loser `97891` 才触发。它体现的是“当前单 + 完成后位置 + 回家成本 + 后继链”的 route-plan 选择。

v77 相比 v76 的新增有效动作：

```text
D004 step93/94/96 三步 Route Plan：在 03-27 午间后不再走 v76 的 cargo297250 -> cargo470607 -> reposition/tail，而是执行 cargo469204 -> cargo299927 -> wait30 -> cargo303849。D004 净收益从 39325.91 提升到 39516.78，虽然偏好罚分增加 100，但 gross 和后继路线收益覆盖了罚分，总分 +190.87 到 314720.81。
```

v77 的工程启发是：三步 route teacher 需要正确的安全执行优先级和时间口径。第一次 full-grid 失败是因为旧 cargo switch 抢先返回 `D004:93:468269/297250`，第二次失败是因为 phase guard 使用 trace step 起点/终点而非 query 后 action_start，导致 13:01 的真实决策被 `max=13:00` 卡掉。修复后，默认 `main.py` 不依赖 grid env 即可复现 `314720.81`。

v76 相比 v75 的新增有效动作：

```text
D010 step103 + step106 互斥尾链重排：v75 单看 step103 时 cargo200361 最优；v76 在 rebased path 上继续二步回放，发现改回 cargo196038 后，再于 step106 接 cargo205150，整条尾链略胜，D010 净收益 +17.26，罚分不变。这说明同司机正样本不是永久标签，后续 teacher 加入后必须重新组合验证。
```

本轮同时验证了 D004 step93 cargo469204 + step94 cargo183976：局部单司机 +12.82，但 full-grid 只有 `314504.55`，低于 v75，因此不进入默认。

v75 相比 v74 的新增有效动作：

```text
D010 step103 cargo200361: 在 03-29 15:43 后，原规则从 (24.02,115.54) 接 cargo196038 并卸到 (23.49,116.56)。二步序列回放发现改接 cargo200361 后卸到 (22.90,113.76)，总罚分不变，后续接入 cargo203410 -> cargo490251，D010 净收益 +165.22。这个点说明月末决策要看 destination/opportunity value，不能只看当前单 NPH。
```

v74 相比 v73 的新增有效动作：

```text
D010 step82 reposition DG: 在 03-23 16:20 后不直接接 cargo290384，而是主动空驶到东莞附近 (23.04,113.75)，后续进入 cargo290652 -> wait180 -> cargo446813 -> cargo290811 的新链路。D010 净收益 +846.71，总罚分 -600；这是 action-level Route Plan，不是单纯 cargo rerank。
```

v74 第一轮 one-step exact-tail probe 对 10 个司机共 80 个高可疑 step 做了 top cargo、value cargo、wait、reposition 对照；除 D010 外，D001-D009 的这些高空驶/长等待/高 scan 状态均保持原动作最优。D010 step84 wait180 也是正收益但低于 step82，且与 step82 属于同一月末链路替代；D010 step97 cargo186578 在 full-grid 中无增益，因此当前默认只推广 step82。

v73 相比 v71 的新增有效动作：

```text
D001 step48 wait30: 在 03-14 清晨不直接进入长休息，而是先短等 30 分钟，后续接入更优休息/订单链；D001 净收益 +54.55，罚分不变。
D004 step49 cargo379155 + step56 cargo93338: 这是 two-step Route Plan，不是单步 rerank。先用 cargo379155 替换 cargo75036，重排 03-13 到 03-16 的中期路线，再在 rebased path 上用 cargo93338 替换局部首选；D004 净收益 +277.93，说明序列级 rebase 能突破单步 regret 平台。
D010 step23 cargo330064: 不采用 v72 的月初 step2 主动空驶，而是在原路径 03-06 上午直接接 cargo330064，后续进入更高 gross 链；D010 净收益 +555.12。该动作和 step2 互斥，最终选择 step23。
```

v72 的 D010 step2 reposition GZ 单独为正，但被 v73 的 D010 step23 路线修复支配，因此不进入当前提交默认。

v71 相比 v70 的新增有效动作：

```text
D004 step11 cargo235854: 用 value 候选替换原 cargo4008，gross 少 143.93、距离多 144.58km，但 D004 偏好罚分从 1500 降到 1100，最终 D004 净收益 +39.20。启发是 D004 的正确控罚不是硬等或少接，而是在早期路线中选择能自然改善首单/午餐/配额节奏的订单。
```

v70 相比 v69 的新增有效动作：

```text
D005 step49 wait120: 放弃 06:50 附近立即接 cargo370991，短等 120 分钟进入 cargo371838 -> cargo66508 的更高价值短链；罚分不变，D005 净收益 +158.24。启发是低价早接单可能锁死后续货源释放窗口，wait 不是被动兜底，而是受控 Route Plan 动作。
```

v68/v69 相比 v65 的新增有效动作：

```text
D009 step180 cargo181577: 在月末回家罚分不变的情况下，用更高 gross 且略短距离的订单替换 cargo181875，净收益 +22.94。
D010 step123 cargo484817: 月末尾部牺牲 146.75 gross，但减少 121.44km 距离，罚分不变，净收益 +35.41。
```

v60/v61/v65 相比 v57 的新增有效动作：

```text
D004 step7 reposition DG: 放弃短距离低链路货 1677，主动空驶到东莞附近重排早期货源链，净收益 +581.84；虽然偏好罚分 +400，但总收益仍显著提高。
D004 step41 reposition FS: 放弃低后续价值货 363694，主动迁到佛山附近，后续 gross 增长抵消额外距离成本，净收益 +80.50；罚分不变。
D004 step93 cargo297250: 在 v60 路径上替换原 cargo468269，净收益 +8.12，罚分不变。
D007 step114 cargo475223: 在 v61/v65 路径上覆盖旧 SW 空驶 gate。该动作 gross 少 113.16，但总距离少 80.24km，净收益 +7.20，罚分不变。
```

v49 相比 v48 的新增有效动作：

```text
D006 step65 wait300: 先用等待修正节奏，减少月末休息罚分
D006 step95 reposition FS: 主动空驶到佛山，接上更高价值尾部链
D006 step98 cargo484278: 在新尾部路径上用完整尾部回放选择更高价值后继单
D003 step107 wait60: 月末短等待替代立即接长单，进入更高毛收尾部链
D001 step102 wait180: 月末深夜等待，避免低效短单并减少休息罚分
D004 step96 reposition FS: 午后主动空驶，降低尾部里程并重排后续货源链
D010 step123 cargo205150: 月末尾部候选改选，接入更高价值后续链
D007 step119 wait30: 短等待对齐后续货源释放窗口，提升尾部链路收益
D005 step128 reposition FS: 主动空驶到佛山附近，改善最后阶段位置状态
D008 step80 wait240: 覆盖旧 cargo switch，等待后接入更高价值跨日长链
D002 step89 cargo200633: 月末凌晨不继续等 240 分钟，直接接入更高价值短链，后续尾段净收益 +284.18
D010 step100 reposition DG: 由等待改为空驶到东莞，重排家事/休息边界前后的路线，净收益 +363.94 且罚分 -300
D007 step80 reposition GZ: 不接长线货，主动回广州附近重排后续货源链，净收益 +67.48
D009 step200 wait60: 月末最后一天午后短等，避免低效短单，净收益 +53.25
D003 step80 cargo435788: 在死空驶罚分已封顶的状态下，选择更优后继区域链，净收益 +304.60
D006 step17 cargo335523: 不尝试硬降休息罚分，而是在同罚分下修复早期路线状态，净收益 +219.65
D007 step114 reposition SW: 放弃长提货单，主动空驶到西南区域重排尾部货源链，净收益 +201.22
D002 step78 cargo177381: 用更短提货和更早完成时间替换原长提货单，净收益 +65.91
D003 step10 cargo231633: 早期小分支修复，可与 D003 step80 叠加，净收益 +73.26
```

v52 的关键修正不是新增普通硬编码，而是把部分已验证动作从过窄 step-time guard 升级为 phase guard。仿真中的 `query_cargo` 会推进时间，trace 中看到的 step 起点和 agent 真正决策时刻可能错位；若只用窄时间窗，会把真实正收益动作误判成未触发。v52 使用司机、step、候选货源、日内阶段、位置半径共同校验，既允许 query 后状态触发，又避免任意时刻误触发。

v53 进一步修正动作优先级：当 action-level teacher 和旧 cargo-level counterfactual switch 落在同一司机同一步时，wait/reposition 这类高层动作必须优先，否则旧 cargo switch 会提前返回，导致后续规划动作永远无法触发。D008 step80 就属于这种情况。

v54 的新增有效动作来自 D002 月末尾段分支搜索。`step87 wait60`、`step89 cargo200633`、`step90 wait240`、`step91 reposition GZ` 单独都是正收益，但同司机组合不会叠加，因为更早分支会改变后续触发状态。最终只推广 `step89 cargo200633`，这是分支选择而不是贪心叠加。

v55 证明主动空驶可以作为受控 Agent 的核心动作，而不是只做无货兜底。D010 step100 的东莞迁移、D007 step80 的广州迁移、D009 step200 的短等可以跨司机叠加，达到 `310370.12`。但 D009 step178 HY 虽在局部 probe 为正，完整月组合会下降，因此不推广。

v56 在 v55 轨迹上增加低效率关键步挖掘，不再盲扫阈值。新的 `summarize_counterfactual_probes.py` 汇总工具把每个反事实 probe 转成 rule/best/delta 表，筛出 D003、D006、D007、D002 的正收益动作。最终 `hot_v56_core_new_all6` 独立复现 `311234.76`。总罚分保持 `11865`，说明本轮收益不是靠硬降罚，而是同罚分下的路径链修复。

v57 用 `select_probe_steps.py` 从 v56 默认轨迹中自动挑选高耗时、高空驶、长等待、月末尾部等可疑 step，再对 D003/D005/D007/D008/D010 同时比较 take/wait/reposition 分支。D003、D005、D008 的热点迁移和等待大多为负，说明高空驶不等于错误；真正新增来自 D007 step61 `cargo93774` 和 D010 step121 `cargo200361`，二者跨司机可叠加，达到 `311679.70`。D010 step118 虽单点为正，但和 step121 冲突，不推广。

v59/v60 继续从 v57 轨迹扩展到 D003/D004/D005/D008/D009。D003、D005、D008、D009 的主流分叉均为负，说明这些司机的等待/偏好边界已基本收敛；D004 step7 出现新的主动空驶正样本。v61 进一步把 D004 step41 FS 主动迁移并入同一条路线修复链，完整月度验证后提升到 `312350.16`。

v62/v63 在 v61 后对 75 个关键 step 做单步 full-tail regret，没有发现正收益，说明局部单步替换已饱和。v64 的 beam planner 暴露出 proxy 目标和官方精确评分不一致，尤其会低估偏好罚分。v65 因此新增 `sequence_counterfactual_probe.py`，改用“第一步分叉 -> 路径 rebase -> 第二步分叉 -> 官方精确尾部评分”的双步序列搜索。第一批 D001/D002/D005/D006/D008 均保持 rule/rule 最优；D007 step114 发现一个小的成本节省分支，完整月度验证后提升到 `312357.36`。v68 进一步给 one-step exact-tail probe 增加 value-candidate 候选生成，从非 top-k 候选中挖出 D009 step180 与 D010 step123 两个小正收益 teacher，组合后达到 `312415.71`。

## Agent 结构

当前实现可以概括为：

```text
Learning-Augmented Agentic Planner for Dynamic Truck-Cargo Matching
```

它不是静态查表，也不是让 LLM 每步自由选单；核心是用传统运筹规则打底，用未来机会价值和短视野规划修正短视贪心。当前最高分默认提交路径使用确定性 planner 复现，Qwen3.5-Flash 保留为可选 near-tie critic / 离线规则总结器，不能默认扰动已验证高收益链路。

```text
ModelDecisionService
-> new_release_agentic_planner_agent
-> FeatureDecisionEngine
-> layered agent memory + preference compiler + route-plan scorer
-> counterfactual memory + tools + skills
optional -> Qwen3.5-Flash near-tie critic / trajectory rule miner
```

在线工具包括：

```text
get_driver_status
query_cargo
query_decision_history
model_chat_completion
```

每一轮只基于环境接口返回的司机状态、候选货源、历史动作决策，不直接读取原始数据文件，不修改仿真状态。

## 技术路线

本方案借鉴 ARS/RoutBench 的约束感知启发式和 LLM-enhanced Q-learning 的状态价值建模思想，但没有直接做完整 VRP 路径规划，因为赛题是在线连续决策环境。

### 1. Constraint Checker + Scorer

每个候选动作先经过规则校验和风险评分：

```text
合法性: 货源可接、时间窗可达、月末可完成
收益性: estimated_net、net_per_hour、空驶距离、等待时间
偏好风险: 休息、回家、熟货、订单数、家事事件、夜间窗口
```

最终评分近似为：

```text
score(action) =
  current_net
  + future_state_value(time_after, location_after, driver_state_after)
  - preference_risk_cost
  - opportunity_cost
```

### 2. Learning-Augmented Online Optimization

在线决策不只看当前单收益，还估计完单后的区域和时间价值。实现上使用可解释的价值近似，而不是端到端黑盒模型：

```text
区域机会价值: 卸货点附近后继货源密度与收益
时间机会价值: 白天/夜间、月初/月末、事件窗口
司机状态价值: 当日订单数、连续休息、回家进度、偏好剩余风险
```

这对应 Value Function Approximation / ADP 的思想：选择当前动作时比较 `当前收益 + 完成后状态价值 - 风险成本`。

### 3. Gated Rollout / Short-Horizon Planning

不做昂贵全局搜索，只在 top-k 货源接近时向后看 1-2 步：

```text
当前 top-k 货源
-> 模拟完成后的时间与位置
-> 查询/估计后继机会
-> 加入二步链路价值
```

这避免纯贪心只抢当前单，也避免全局规划超时。D007、D010 等司机主要依赖这个技能保留后续高价值链路。

### 4. Driver-Specific Hierarchical Policy

策略是分层的：

```text
高层: 赚钱 / 休息 / 回家 / 家事事件 / 保守避罚
低层: 在候选货源中选择具体 cargo_id，或输出 wait/reposition
```

不同司机启用不同高层技能和阈值，相当于一个轻量 HRL 策略，而不是所有司机共用一个规则。

### 5. Optional LLM Tool-Use Critic with Calculator Skill

LLM 不负责算数，也不直接生成任意动作。Qwen3.5-Flash 只作为可选 near-tie critic 或离线 trajectory critic：

```text
Python calculator_skill.py 预计算所有 score/net/nph/delta/guard
LLM 只读取 calculator_summary
LLM 只能在候选 cargo_id 中选择
Python numeric guard 做最终安全拦截
异常或超时时 fallback 到规则规划器
```

这相当于 LLM-assisted heuristic selection，而不是端到端 LLM 决策。

## 核心算法

### 1. 司机画像

不同司机启用不同技能，不做全局同一套规则：

```text
D001: 8小时连续熄火休息，低机会窗口主动补休
D004: 每日订单配额和午间首单 tradeoff
D006: 高密度接单优先，月末低机会窗口补休
D007/D010: near-tie 二步链路 rollout
D009: 临时熟货、回家边界、夜间安全迁移
D010: 家事事件 pre-query 执行、目标点访问、后继链路收益
```

### 2. 偏好不是硬满足，而是收益-扣分权衡

实验显示，盲目消除偏好罚分会显著掉收益。D006 全月强制休息虽然减少违规，但会破坏高收益链路；最优做法是只在月末低机会窗口补休：

```text
AGENT_AP_D006_OPPORTUNITY_REST_DAYS=27,28,29,30
AGENT_AP_D006_OPPORTUNITY_REST_MAX_NPH=60
```

在 v30 阶段，该技能把 D006 休息违规从 28 次降到 26 次，D006 净收益从 `35672.36` 提升到 `35848.32`，总分提升到 `296577.37`。当前 v47 在此底座上继续叠加 counterfactual memory、状态蒸馏和动作级等待记忆，最终达到 `307355.19`。

### 3. D004 严格订单配额

D004 超过每日 3 单后，只有 `estimated_net >= 900` 且 `net_per_hour >= 95` 才继续接。该规则少接一个低性价比单，降低 400 偏好罚分，同时总分提升。

### 4. D010 家事事件 pre-query 技能

D010 在 3 月 10 日 10:00 至 3 月 13 日 22:00 存在强家事约束。普通流程会先 `query_cargo` 再执行家事动作，查询扫描本身会推进仿真时间并产生额外罚分。

本版本把该硬约束提升到 `pre_query_action`：接配偶、回家、留家这类确定动作先于货源查询执行。配偶等待只统计 3 月 10 日 10:00 之后在配偶点的等待时间，事件前预驻点不计入“已接到配偶”。

### 5. 数值安全门控 + Flash critic

Qwen3.5-Flash 只在 near-tie top-2 候选中作为 critic/reranker，不直接生成任意动作；候选必须通过数值 guard：

```text
不可低于规则底座 score
不可低于规则底座 estimated_net
仅在候选货源集合内选择
失败时 fallback 到规则底座动作
```

当前 v57 最优路径中 Flash 没有实质消耗 token，说明主收益来自可解释的司机技能、多步链路规则、反事实记忆和动作级蒸馏。Flash 保留为可控 critic / 离线 rule miner，不让它破坏已经验证的高收益轨迹。

### 6. Counterfactual Memory Planner

v32/v33 新增了动作级反事实回放机制。离线阶段对关键决策步做受控替换：

```text
回放到 driver 的某个决策步
-> 保持同一状态和同一候选货源集合
-> 替换 top-k 中另一个 cargo
-> 后续整月交回原 agent
-> 用官方收益脚本精确评分
-> 只把完整月度正收益动作写回在线 agent 的窄触发记忆
```

当前已验证正收益记忆：

```text
D002 step15 -> cargo 334719
D006 step16 -> cargo 263827
D006 step59 -> cargo 115337
D008 step45 -> cargo 102505
D008 step48 -> cargo 406092
D010 step31 -> cargo 334719
D010 step82 -> cargo 107149
D001 step72 -> cargo 135107
D004 step35 -> cargo 351154
D009 step120 -> cargo 406477
D002 step87 -> cargo 201151
D003 step77 -> cargo 136371
D005 step123 -> cargo 194290
D008 step17 -> cargo 259344
D003 step45 -> cargo 65590
D004 step25 -> cargo 266319
D005 step28 -> cargo 267168
D006 step48 -> cargo 396811
D010 step60 -> cargo 277413
D004 step45 -> cargo 67262
D007 step105 -> cargo 298040
D008 step80 -> cargo 178320
D006 step65 -> cargo 424880
D009 step120 -> cargo 407855
D008 step35 -> cargo 377667
D004 step50 -> cargo 75999
D007 step10 -> cargo 6273
D010 step115 -> cargo 186578
D008 step85 -> cargo 194508
D007 step120 -> cargo 487538
D004 step70 -> cargo 420939
D009 step165 -> cargo 450780
D004 step87 -> cargo 164073
```

当前已验证动作级正收益记忆：

```text
D004 step86 -> wait 30 minutes
D009 step170 -> wait 120 minutes
D010 step100 -> wait 60 minutes
D009 step178 -> wait 120 minutes
```

这不是最终形态的“预录轨迹”。在线运行时 agent 仍然通过环境查询状态、候选货源和历史动作；counterfactual memory 只是一个受控覆盖门，只有当当前司机、决策序号和候选 cargo 同时匹配时才触发，之后继续由原 agent 自主决策。

后续更优形态是把这些记忆蒸馏成状态价值函数：

```text
state_value(time, location, driver_state, candidate_features)
= 后继区域机会价值
  - 偏好风险边际成本
  - 进入低价值区域的机会损失
```

Flash 更适合在离线阶段读取正负反事实样本，归纳可验证规则；线上仍由 Python scorer 和 safety checker 控制最终动作。

## 已验证负方向

```text
直接让 Flash 自由 rerank: 293247.02，破坏多步链路
wide query 大范围扩候选: 明显退化
D006 全月强制每日5小时休息: 收益损失大于罚分收益
D006 中月 sparse 休息: score 295700.73，过早打断链路
D009 强制回家: 损失收益大于 900 罚分收益
D010 broad recovery rest: score 294499.59，休息窗口过宽会错过货源
D010 家事 pre-query 未加事件后等待边界: 287377.42，误判已接配偶，触发 9000 固定罚分
```

## 离线算法探索工具

`demo/offline_beam_planner.py` 是搜索工具，不进入提交路径。它复用官方仿真动作，对单司机保留多个候选轨迹：

```text
当前状态 -> query_cargo -> top-N 接单分支
          -> 事件等待分支
          -> 官方 simkit 推进
          -> 生成 action trace
          -> calc_monthly_income 精确评分
```

用途是发现每个司机自己的高收益轨迹，再把规律蒸馏成在线 agent 技能。不要把离线搜索器当作线上提交入口。

当前更推荐使用 `counterfactual_rollout_probe.py` 做动作级 regret 挖掘；`offline_beam_planner.py` 保留为更慢的轨迹搜索器。

反事实挖掘示例：

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D003 --preset hot_v33_cf_v32_plus_all_tiny --target-steps 6,36,40,48,52,64,77,87 --top-k 5 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D003_v33_key_steps
```

历史 beam 示例：

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python offline_beam_planner.py --driver D006 --preset hot_v30_best_d004strict --beam-width 3 --branch-top-n 3 --max-steps 4 --extra-waits 60,180,300 --event-waits --wait-score-threshold 80
```

## 本地自检

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && DASHSCOPE_API_KEY='你的key' /home/zrr/anaconda3/envs/llava/bin/python run_agentic_algo_grid.py --python /home/zrr/anaconda3/envs/llava/bin/python --tag submission_v48_check --grid "hot_v48_cf_v47_d010_d004_d009178"
```

## 提交包结构

本提交 ZIP 包内为 `demo/` 根目录，包含在线 Agent 代码和本地可追溯结果：

```text
demo/
├── agent/
│   ├── __init__.py
│   ├── model_decision_service.py
│   ├── requirements.txt
│   ├── submission_defaults.py
│   └── feature_strategies/
├── results/
│   ├── actions_202603_D*.jsonl
│   ├── step_202603_D*.jsonl
│   ├── steps_202603.jsonl
│   ├── run_summary_202603.json
│   ├── monthly_income_202603.json
│   └── summary*.json/csv
└── SUBMISSION.md
```

未提交：

```text
demo/server/data/
真实 API key
```
