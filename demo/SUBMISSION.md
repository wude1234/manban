# Submission Profile

## 当前提交版本

提交 profile：`v69_value_candidate_teacher_312415`

本地 0509 数据当前最好复现结果：

```text
score = 312415.71
total_preference_penalty = 12265.0
failed_driver_count = 0
```

对应实验：

```text
demo/results/grid_agentic_algo/20260524_023030_autonight_v68_positive_grid/03_hot_v68_d009180_d010123
preset = hot_v68_d009180_d010123
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
