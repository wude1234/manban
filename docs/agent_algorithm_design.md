# Agent 算法设计：基于 0508/0509 探索发现

## 1. 当前已验证最好底座

0509 当前稳定最好：

```text
score = 314512.68
penalty = 12465.0
failed_driver_count = 0
```

对应策略底座：

```text
AGENT_STRATEGY = new_release_agentic_planner_agent
profile = hot_v75_d010_step103_200361
base = v30 driver-specific planner
upgrade = v32-v75 counterfactual memory + phase action gates + low-efficiency route repair + exact sequence probing + wait-as-route-plan teacher + schedule-aware value teacher + two-step route rebase + clean harness ablation + D010 active reposition and month-end destination-value repair
```

这个结果的意义不是最高分本身，而是说明：0508 上有效的司机独立规则迁移到 0509 后仍成立，且“轨迹记录 + 反事实回放 + 规则蒸馏”的 agentic harness 能继续从固定底座中挖出真实长期收益。v56/v57 的新增收益没有降低总罚分，而是在同罚分下修复 D003/D006/D007/D002/D010 的后继路线状态；v61/v65 进一步证明主动迁移和双步序列 rebase 可以在单步 regret 饱和后继续找到小的路线修复；v70 证明等待也可以是主动 Route Plan 动作，而不是无货兜底；v71 证明偏好风险可以通过早期订单选择自然修复，而不是硬控；v72/v73 证明双步 route rebase 和干净 ablation 能继续把互斥 teacher 选对；v74 证明高可疑动作必须经过 exact-tail 验证，真正的新增来自 D010 月末主动空驶重排路线。

## 2. 核心发现

### 2.1 有效方向

- 司机必须独立建模。全局收益权重、全局候选池扩大、全局控罚分都容易退化。
- 链路价值是主要增益来源。D001、D007、D009、D010 的提升来自“接完当前单后能不能接到更好的后继单”。
- 候选池大小不是越大越好。多个司机存在尖峰甜点，扩大候选池会引入远端噪声、扫描成本和错误选择。
- 减少罚分不是最终目标。很多降罚策略会牺牲更大的运费，总收益下降。
- 0508 到 0509 的稳定规律主要来自司机画像，而不是数据偶然性。
- 动作级 regret 是当前最有效的新方向。v32/v33 不再靠扫全局阈值，而是替换单个关键货源后回放整月，直接比较长期收益。
- 正收益点可以跨司机叠加。D001、D004、D009 的小收益点在线完整验证后可叠加到 v32 底座，说明多司机独立挖掘是合理的。
- 同司机内部存在路径依赖。D010 的某些单点替换单独有效，但组合后收益不线性，因此同一司机必须做完整组合验证。
- v34 证明 D002/D003/D005 是新的高收益空间。D003 step77、D005 step123、D002 step87 可以跨司机叠加，D008 step17 也能小幅增益但伴随更高罚分。
- 同司机不能贪心开启全部 positive memory。D002/D003/D005 的 pair/multi 均低于 top 单点，后续要做 per-driver regret subset selection。
- v35 证明 regret mining 未收敛。D003 step45、D004 step25、D005 step28、D006 step48、D010 step60 可以继续叠加到 v34，把分数推到 `301859.50`。
- v36 证明 D004 step45 是更稳的 D004 记忆点。它比 v35 继续 `+422.18`，同时总罚分从 `14265` 降到 `13965`。
- v37 证明 D007/D008 仍有高质量空间。D007 step105 与 D008 step80 可跨司机叠加，分数达到 `303285.96`，同时总罚分降到 `13565`。
- v38 证明 D006/D009 的二次反事实替换仍能叠加。D006 step65 与 D009 step120 把分数继续推到 `303592.37`，罚分保持 `13565`，说明当前方向还没有完全收敛。
- v55/v56 证明 `wait/reposition/take_order` 必须作为同级动作比较。v55 主动空驶把分数推到 `310370.12`；v56 再通过低效率关键步 full-tail 反事实，把分数推到 `311234.76`。
- v56 的核心增益不是降罚，而是 route repair：D003 step80、D006 step17、D007 step114、D002 step78、D003 step10 均在偏好罚分不变时提升整月净收益。
- v57 证明自动选点可以继续找到同罚分收益。D007 step61 `cargo93774` 与 D010 step121 `cargo200361` 可跨司机叠加，把分数推到 `311679.70`；D010 step118 虽单点为正，但与 step121 冲突。
- D004 的 v56 负结果说明“修罚分”不是万能方向。对高空驶/日程问题强行等或空驶会损失更多 gross，后续 D004 应转向更早的日内槽位规划。
- v61 证明 D004 早中期主动迁移是高收益路线修复。D004 step7 DG、step41 FS 和 step93 cargo297250 组合后达到 `312350.16`，收益来自后续 gross 增长与小距离成本之间的长期权衡。
- v65 证明单步 regret 饱和后仍可用精确双步序列搜索找到细小收益。D007 step114 改接 `cargo475223` 后 gross 下降但距离成本下降更多，完整月度提升到 `312357.36`。这类信号很小，但它说明 sequence-level route planner 比单步 reranker 更接近本题长期决策本质。
- v68/v69 证明 destination/opportunity value 适合作为候选生成器，而不是直接打分器。大多数 value 分支为负，但 exact-tail validation 找到 D009 step180 `cargo181577` 和 D010 step123 `cargo484817` 两个非 top-k 小正收益，组合后达到 `312415.71`。
- v70 证明短等待本身也需要进入动作级规划。D005 step49 `wait120` 放弃一个早期低链路订单，等待后进入更高价值短链，罚分不变且 D005 净收益 `+158.24`。这说明“未来收益”不能只由目的地区域强弱解释，还要看货源释放窗口和接单后完成时间是否压住后继链。
- v71 证明偏好罚分需要作为边际状态成本参与候选选择。D004 step11 选择 `cargo235854` 后 gross 下降、距离上升，但后续日程罚分下降 `400`，最终净收益 `+39.20`。这类样本说明 Agent 需要比较“当前收益 + 后继路线 + 偏好风险变化”，而不是只追当前 NPH。
- v72/v73 证明序列级 route rebase 是下一阶段主线。D004 step49 `cargo379155` 单独会把后续路线带偏，必须和 rebased path 上的 step56 `cargo93338` 组合执行，完整月 D004 净收益 `+277.93`。D001 step48 `wait30` 额外 `+54.55`。D010 step2 主动空驶虽然为正，但被 D010 step23 `cargo330064` 支配；清理 grid harness 的 submission-default 污染后，step23 可与 D001/D004 跨司机叠加，达到 `313500.75`。
- v74 证明全司机并行探测后仍能找到新的高收益 action-level teacher。80 个高可疑 step 中只有 D010 step82 为强正收益，说明“高空驶/长等待/高 scan”只能作为候选选择器，不能直接变成策略规则。step82 选择主动空驶到 DG 后重排后续链，并把 D010 连续休息罚分降低 `600`，总分提升到 `314347.46`。
- v75 证明二步序列回放能在 v74 路径上继续找到同罚分收益。D010 step103 改接 `cargo200361` 后，卸货位置从 `(23.49,116.56)` 变为 `(22.90,113.76)`，保留 1265 罚分并打开 `cargo203410 -> cargo490251` 的月末尾链，总分提升到 `314512.68`。这个样本把“未来收益”具体化为 `当前净收益 + 完单后位置价值 + 后继可接链 - 偏好风险`，比静态强/弱区域判断更可靠。

### 2.2 明确负方向

- D002 chain、D008 chain、D006 chain 多次为负，不应作为默认主线。
- D009 硬回家、home slack、过大候选池会降分，`limit221` 已明显触发多罚并降收益。
- D004 lunch 阈值不是新增收益点，很多实验只是没有改变实际动作。
- D001/D010 扩大查询视野会退化，说明远端候选噪声大于链路收益。
- 固定参数微调已进入平台期，继续扫 `410/415/420` 这类边界不会带来接近 34w 的突破。
- 普通 beam proxy 不能直接替代官方评分。v64 中 D008 的 proxy 候选被偏好罚分击穿，说明搜索必须回到 exact-tail scoring 或学习一个显式包含偏好风险的状态价值函数。

## 3. 司机画像与对应策略

### D001

发现：

- 链路价值强正收益。
- `chain_weight=1.05/1.10` 附近平台。
- 扩大查询视野为负。
- 休息补罚不能硬做，要看机会成本。
- v33 中 step72 反事实换到 `cargo 135107`，完整月度 `+18.63`。

策略：

```text
使用 visible_chain_value。
不扩大 query_limit。
只在低机会窗口考虑休息，不能为了少罚分牺牲高收益单。
下一代用 rollout 判断当前单是否破坏后继高价值链。
记录 D001 的小 regret 模式，后续归纳为“低差距候选中优先更好后继位置”。
```

### D002

发现：

- v32 中 step15 反事实换到 `cargo 334719`，完整月度 `+878.10`，是当前最大的单点贡献。
- v34 中 step87 反事实换到 `cargo 201151`，可在 v33 底座上继续 `+231.77`。
- 这说明 D002 不是没有进攻空间，而是原有 chain 权重没有抓住正确的状态价值。
- 大收益来自换单后的后继时间-空间状态，而不是简单当前单 NPH 更高。

策略：

```text
保留当前正收益 switch。
继续扫描 D002 候选丰富步骤，重点看低 NPH、长空驶、罚分前后的 regret。
后续把 D002 step15 的胜出原因蒸馏为 future_state_value，而不是只记固定 cargo。
不要同时启用 step59 和 step87，pair 验证低于只用 step87。
```

### D003

发现：

- `query_limit=200` 有小正收益。
- `chain_weight=0.05` 弱正，但不是主突破。
- 禁区/空驶惩罚仍要硬控。
- v34 中 step77 反事实换到 `cargo 136371`，完整月度 `+939.93`，是当前最大新增单点。
- D003 pair/multi 低于 step77 单点，说明路径依赖强。
- v35 中 step45 换到 `cargo 65590`，可与 step77 共存，继续 `+477.30`。

策略：

```text
query_limit 固定 200。
保留轻量 chain tie-break。
当空驶罚分接近封顶后，允许更偏向净收益，但不能放开禁区硬约束。
重点学习 step77 的胜出特征：它不是降罚，而是改变后继路线收益。
继续重点挖 D003，当前多个 rank4/rank5 候选胜出，说明 future-state reranker 很有必要。
```

### D004

发现：

- `query_limit=600` 是稳定峰值。
- `605/610/615/620` 都退化，说明边界很尖。
- lunch 阈值不是新收益点。
- D004 关键不是午休，而是每日订单槽位价值。
- v33 中 step35 反事实换到 `cargo 351154`，完整月度 `+59.13`，且总罚分减少 `100`。
- v35 中 step25 换到 `cargo 266319`，可继续 `+630.98`，但 D004 罚分上升，属于高收益激进点。
- v36 中 step45 换到 `cargo 67262`，可继续 `+422.18`，且总罚分下降，是比 step25 更稳的主记忆点。

策略：

```text
query_limit 固定 600。
前三单重视净收益和 NPH。
超过 3 单后提高接单门槛，避免低价值单占用订单槽并触发罚分。
下一代 rollout 要估计“当前单是否浪费今天剩余槽位”。
将 D004 的 counterfactual memory 解释为“槽位价值 + 偏好风险下降”的组合收益。
保留 step25 高分版，同时维护不启用 step25 的稳健低罚分版。
当前提交优先采用 step45；step60/step25 与 step45 组合后不再提供额外增益。
```

### D005

发现：

- `chain_weight=0.06/0.08/0.10` 多数同分，说明触发弱。
- 当前不是已验证主增量，但还没有做充分 action-level regret 深挖。
- v34 证明 D005 有真实空间：step123 换到 `cargo 194290`，完整月度 `+464.80`。
- D005 pair/multi 低于 step123 单点，说明多个正样本互相冲突。
- v35 中 step28 换到 `cargo 267168`，可与 step123 共存，继续 `+385.69`。

策略：

```text
保留轻量净收益 tie-break。
下一步必须跑 D005 关键步反事实扫描。
如果发现正收益点，优先判断是否来自目的地区域机会，而不是继续扫 chain_weight。
当前只保留 step123，其他正样本进入待组合搜索池。
当前保留 step123 和 step28，后续继续做 subset search。
```

### D006

发现：

- `query_limit=201/202` 同分最好。
- `203/204` 大幅退化，边界很尖。
- 硬休息降低罚分但总收益下降。
- v32 中 step16/step59 的窄反事实 switch 可带来小幅正收益，说明 D006 仍有候选排序 regret，但主要空间不在休息强约束。
- v35 中 step48 换到 `cargo 396811`，小幅 `+138.49`，可叠加。

策略：

```text
query_limit 固定 202。
保留极轻 chain_weight=0.014。
不做强制休息。
rollout 中只把休息作为状态风险，不作为硬约束。
保留月末低机会补休和窄反事实记忆，不扩大成全月休息规则。
继续小范围挖 D006，但优先级低于 D003/D004/D005。
```

### D007

发现：

- `query_limit=410/415/420` 同分最好。
- `425+` 开始退化。
- D007 是 0509 新增主要增益来源，+294.12。
- v37 中 step105 换到 `cargo 298040`，完整月度 `+552.49`，无新增罚分。
- step5 单独正收益，但与 step105 组合后冲突并增加罚分，不应并入。

策略：

```text
query_limit 取 420，保守可取 410。
保留 chain_weight=0.10。
下一代 rollout 判断后继机会密度，避免为了单个高价单进入低机会区域。
当前只保留 step105，不保留 step5。
```

### D008

发现：

- 当前 chain/进攻权重方向为负，但 action-level regret 证明 D008 有大空间。
- v32 中 step45 反事实换到 `cargo 102505`，完整月度 `+728.04`。
- 该点虽然增加部分罚分，但 gross 和后继链路提升更大。
- v34 中 step17 换到 `cargo 259344`，本地 `+69.75`，但总罚分升到 `14065`，泛化风险高。
- v37 中 step80 换到 `cargo 178320`，完整组合后涨分且总罚分下降，是当前 D008 更优记忆点。
- 食品饮料/休息约束更像防守项。

策略：

```text
保留硬偏好和休息防守。
继续扩展 action-level regret，不再把 D008 判定为“无进攻空间”。
把 D008 的收益判断从单步罚分最小化改成“收益链 - 偏好风险边际成本”。
优先保留 step80；step17 可视为本地小点但泛化优先级低。
```

### D009

发现：

- `query_limit=220` 是稳定甜点。
- `chain_weight=0.09/0.095/0.10` 同分平台。
- `limit221` 多罚且大幅退化。
- 硬回家、home slack 为负。
- v33 中 step120 反事实换到 `cargo 406477`，完整月度 `+3.74`，说明当前路径接近平台。

策略：

```text
query_limit 固定 220。
chain_weight 取 0.10。
保留必接熟货逻辑，但不要硬修全部回家罚分。
rollout 中只把回家风险作为软成本，不能一票否决高收益单。
不优先继续深挖 D009，除非发现回家风险和高收益链同时改善的动作。
```

### D010

发现：

- `query_limit=200` 最好。
- D010 能与 D001 链路价值叠加。
- `D010 weight=0.08/0.12` 退化，`0.10` 稳定。
- 降罚不一定增收益。
- v32 中 step31 换到 `cargo 334719` 后完整月度 `+132.63`。
- step82 单独可能更好，但和 step31 组合后有路径依赖，不能简单叠加。
- v35 中 step60 换到 `cargo 277413`，小幅 `+73.42`，同时 D010 罚分下降。

策略：

```text
query_limit 固定 200。
chain_weight 取 0.10。
家事硬约束保留。
其他休息/跨天只做机会成本判断。
同司机内部的多个 switch 必须组合验证，不能只看单点最高。
保留 step60，因为它是收益和偏好风险同时改善的小点。
```

## 4. 对应算法架构

最终 agent 不应该是单一规则，而是四层在线决策：

```text
Layer 1: hard filter
  过滤不可行、硬偏好违规、车辆不匹配、明显会失败的订单。

Layer 2: immediate value
  估计当前订单净收益、NPH、等待时间、空驶成本、偏好边际成本。

Layer 3: chain / rollout value
  模拟接完当前单后的时间和位置，从当前可见候选里找可赶上的后继单。
  计算后继单价值、机会密度、结束区域价值。

Layer 4: driver state risk
  按司机画像估计接完当前单后的风险：
  D004 槽位风险、D009 回家风险、D001/D006/D010 休息窗口风险、D003 空驶封顶状态。
```

统一评分：

```text
score(order, driver_state) =
  immediate_value(order)
  + chain_weight(driver) * visible_chain_value(order)
  + rollout_weight(driver) * next_order_value(order)
  + density_weight(driver) * opportunity_density_after(order)
  - risk_weight(driver) * state_risk_after(order)
```

其中 `driver_state` 至少包含：

```text
当前时间
当前位置
当日已接单数
最长连续休息时间
累计空驶/偏好相关状态
历史动作
是否处于跨天/夜间/家庭事件窗口
```

## 5. 已实现的 v18 版本

0509 已实现短视野规划器实验开关：

```text
AGENT_AP_ENABLE_TWO_STEP_ROLLOUT=1
```

代码位置：

```text
/home/zrr/study/demo_docs_release_20260509/demo/agent/feature_strategies/new_release_agentic_planner_agent.py
/home/zrr/study/demo_docs_release_20260509/demo/run_agentic_algo_grid.py
```

v18 的公式：

```text
score =
  base_score
  + visible_chain_value
  + rollout_weight(driver) * (
      best_reachable_next_order_value
      + density_weight(driver) * reachable_good_order_density
      - risk_weight(driver) * state_risk_after_order
    )
```

它只用在线 API 里的可见货源和历史动作，不读原始数据文件，符合赛题约束。

## 6. 下一步实验原则

不要再无目的扫全局参数。后续只做三类实验：

```text
1. 单司机归因
   先只开一个司机的 rollout，看该司机净收益和总分是否增加。

2. 正收益组合
   只有单司机为正，才与当前最好底座组合。

3. action-level regret
   对低 NPH、长空驶、触发罚分前后的动作做替代候选重放，找真正错误决策。
```

判断标准：

```text
当前 0509 最好 = 311679.70
任何算法只有超过这个分数，才算新的提交候选。
如果总分不涨但某司机涨，需要看是否被其他司机互相干扰。
如果罚分下降但总分下降，不能采纳。
```

## 9. v32-v57 新策略：Counterfactual Memory Planner

当前最有效的探索范式：

```text
trace 记录真实 agent 轨迹
-> 定位关键决策步
-> 对 top-k 候选 cargo 做 one-step counterfactual replacement
-> 后续整月交回 base agent
-> 官方收益脚本评分
-> 正收益动作写回 online memory gate
```

这个策略对应比赛里的 agent 能力：

```text
状态管理: 记录每个司机的 step、位置、时间、偏好风险和历史动作
工具化: 用 counterfactual_rollout_probe 调用官方仿真和收益计算
技能化: 每个司机有独立 regret/memory gate
记忆化: 只保存完整月度验证为正的动作模式
LLM 协作: Qwen3.5-Flash 用于离线总结正负样本，生成待验证规则
```

当前正收益记忆：

```text
D001: step72 cargo135107
D002: step15 cargo334719
D004: step35 cargo351154
D006: step16 cargo263827, step59 cargo115337, step65 cargo424880
D008: step45 cargo102505, step48 cargo406092
D009: step120 cargo406477, step120 cargo407855
D010: step31 cargo334719, step82 cargo107149
D002: step87 cargo201151
D003: step77 cargo136371
D005: step123 cargo194290
D008: step17 cargo259344
D003: step45 cargo65590
D004: step25 cargo266319
D005: step28 cargo267168
D006: step48 cargo396811
D010: step60 cargo277413
D004: step45 cargo67262
D007: step105 cargo298040
D008: step80 cargo178320
D006: step65 cargo424880
D009: step120 cargo407855
D007: step61 cargo93774
D010: step121 cargo200361
```

下一步不是无限追加固定 step，而是归纳这些动作为什么赢：

```text
是否提高卸货后区域机会密度？
是否减少未来空驶距离？
是否避免进入低价值区域？
是否减少偏好罚分？
是否保留了 D004 订单槽位？
是否让 D010 家事/休息窗口更可行？
```

只有能解释成稳定状态特征的规律，才应该升级成泛化 scoring rule。

## 7. D010 历史动作级发现

v20 阶段的 D010 正收益不是“夜间越短越好”，而是更窄的状态机会：

```text
如果当前 base 首选单会导致司机无法回到家/目标地并在早晨前完成 3 小时休息，
而另一个近似同分候选能完成这个恢复动作，
则允许小规划器在 top-k 内改选。
```

v21 的负实验说明短单偏好不能全局化。step87 中 base 长单本来能恢复休息，改成短单后后续链路更差且多罚 `300`。因此 v22 的方向是 `base-aware recovery gate`，判断首选动作是否真的造成恢复失败，而不是只看候选是否短、是否夜间、是否靠近家。

## 8. 最终提交策略建议

当前 0509 最好已更新为 v61：

```text
hot_v61_d004_step7dg_step41fs_step93
score = 312350.16
penalty = 12265
```

如果更重视隐藏集稳健性，可对比低罚分版本：

```text
hot_v55_d010100_d00780_d009200
score = 310370.12
penalty = 11865
```

v60/v61 的关键新增规律来自 D004 主动空驶路线修复：step7 原策略接短距离货 `1677`，但完整尾部回放证明主动空驶到东莞附近能打开更高价值链，尽管多付 `400` 偏好罚分，总分仍净增 `+581.84`。step41 进一步证明主动迁到佛山附近可以在罚分不变时用更高后续 gross 抵消额外距离成本，再增 `+80.50`。这说明区域价值不是单独强弱标签，而是“当前动作是否把司机送进后续货源链”的状态价值。

如果后续 D001/D009/D006 等低分或高罚分司机继续挖掘跑出更高组合，再替换提交底座；否则 v61 作为当前提交候选。

提交前原则：

```text
只并入超过 312350.16 的策略。
固定 step switch 必须经过完整月度验证。
同司机多个 switch 必须组合验证，不能只看单点最高。
D009 gated、D007 top5、D010 limit205、v21 night preserve 等旧负方向继续排除。
任何新高需要 confirm 重跑，且检查 penalty 与司机分项。
```
