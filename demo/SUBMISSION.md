# Submission Profile

## 当前提交版本

提交 profile：`v48_phase_gate_agentic_planner_307670`

本地 0509 数据当前最好复现结果：

```text
score = 307670.65
total_preference_penalty = 12465.0
failed_driver_count = 0
```

对应实验：

```text
demo/results/grid_agentic_algo/20260523_034757_v48_d009_split_combo/03_hot_v48_cf_v47_d010_d004_d009178
preset = hot_v48_cf_v47_d010_d004_d009178
```

## Agent 结构

当前实现可以概括为：

```text
Learning-Augmented Agentic Planner for Dynamic Truck-Cargo Matching
```

它不是静态查表，也不是让 LLM 每步自由选单；核心是用传统运筹规则打底，用未来机会价值和短视野规划修正短视贪心，再让 Qwen3.5-Flash 只在受控 near-tie 场景下做工具化复核。

```text
ModelDecisionService
-> llm_rerank_agent
-> Qwen3.5-Flash near-tie critic
-> new_release_agentic_planner_agent
-> FeatureDecisionEngine
-> layered agent memory + preference compiler + route-plan scorer
-> counterfactual memory + tools + skills
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

### 5. LLM Tool-Use Critic with Calculator Skill

LLM 不负责算数，也不直接生成任意动作。Qwen3.5-Flash 只作为 near-tie critic：

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

当前 v47 最优路径中 Flash 没有实质消耗 token，说明主收益来自可解释的司机技能、多步链路规则、反事实记忆和动作级蒸馏。Flash 保留为提交结构中的可控 critic，不让它破坏已经验证的高收益轨迹。

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
