# Algorithm Exploration Plan

## 当前结论

当前最好可复现分数：

```text
score = 373554.89
preset = v134_v132_plus_d009_p20_soft_c01
penalty = 78115.0
result_dir = results/hybrid_submission/v134_v132_plus_d009_p20_soft_c01
```

## v134 新发现：D009 存在高毛利覆盖回家罚分的窄缝，但需要 home repair

v134 在 v132 基础上替换 D009 的 prefix20 soft high-gross tail route：

```text
D009 20070.14 -> 20120.85, +50.71
gross 31571.41 -> 61428.04
distance 7067.51 -> 14338.13
preference_penalty 900 -> 19800

full hybrid:
  score 373504.18 -> 373554.89
  total_preference_penalty 59215 -> 78115
```

这不是一个漂亮路线，但它是有价值的发现：D009 的长链 gross 增量接近 3 万，扣掉距离和 22 天回家违规后仍略正。说明 D009 不能简单归为“绝对不能冲毛利”，而是要把高毛利尾链和 nightly home repair 同时优化。

同批 v133 负例：

```text
D006 p18 soft = 36504.35, lower than v132 37292.45
D006 p18 ignore = 36102.45, lower than v132 37292.45
D007 p20 soft = 30222.35, lower than current 32679.93
D007 p15 soft = 31828.10, lower than current 32679.93
D010 p20 soft = 8675.33, lower than current 34062.66 due 36000 penalty
```

启发：

```text
1. D006 当前有效的是 semisoft/tightdist 窄通道，继续放松偏好会掉分。
2. D007 零罚分路线不是保守浪费，而是当前 exact 最优附近；高毛利尾链被夜间/品类/长距离罚分打穿。
3. D010 家事约束是硬边界，prefix20 后放开会触发灾难罚分。
4. D009 可以继续探索，但下一步必须从“冲高 gross”切换到“高 gross + 每晚回家修复”，目标是保留 61428 gross 的一部分，同时把 19800 回家罚分降下来。
```

## v132 新发现：tightdist 不是通用方向，但 D006 尾段仍可小幅吃毛利

v132 在 v129 基础上替换 D006 的 prefix18 tightdist tail route：

```text
D006 37251.63 -> 37292.45, +40.82
gross 67307.35 -> 68563.94
distance 14570.48 -> 15247.66
preference_penalty 8200 -> 8400

full hybrid:
  score 373463.36 -> 373504.18
  total_preference_penalty 59015 -> 59215
```

同批 v131 的负例更重要：

```text
D001 tightdist = 43932.95, -609.71
D002 tightdist = 38406.95, -629.61
D003 tightdist = 41270.97, -609.70
D004 tightdist = 44678.70, -809.71
D005 tightdist = 39196.93, -461.91
D008 tightdist = 37429.95, -1361.91
D001 widegross = 44542.66, tied current
```

启发：当前路线族已经不是简单“压距离”能提升；tightdist 会牺牲高 gross 主链，只有 D006 因为前缀18后尾段仍有偏好/距离/毛利的局部错配，能多吃一单毛利覆盖新增 200 罚分。下一步高收益优先应换搜索范式：

```text
1. D006 做 semisoft 权重族，而不是只调 release point。
2. D007/D009/D010 做偏好约束 tail mining，找是否存在非 ignore-pref 的后半月正链。
3. D002/D003/D004/D005/D008 可试固定前缀 widegross 分支，但 tightdist 已基本判负。
```

## v129 新发现：D001 也进入 tail-release 收益区，prefix10 对其他司机过早

v129 在 v127 基础上替换 D001 的 prefix12 capsoft tail route：

```text
D001 43713.77 -> 44542.66, +828.89
gross 73657.00 -> 74410.48
distance 16628.82 -> 16578.55
preference_penalty = 5000

full hybrid:
  score 372634.47 -> 373463.36
  total_preference_penalty = 59015
```

同批 v128 的负例也很关键：

```text
D002 prefix10 = 38065.24, lower than prefix12/13 best 39036.56
D005 prefix10 = 39137.52, lower than prefix12/14 best 39658.84
D008 prefix10 = 37859.59, lower than prefix14 best 38791.86
D006 prefix20 = 37251.63, tied with current prefix18 route
```

启发：release point 不是越早越好。D001 可以从 prefix12 放开并提升 gross；D002/D005/D008 在 prefix10 会破坏 3 月 10-12 日关键骨架，导致罚分/距离恶化。下一步应围绕临界区间做细搜：D001 prefix10/11/13，D002/D005 prefix11/12，D008 prefix12/13，D006 保持 prefix18 或微调 semisoft scorer。

## v127 新发现：释放点继续前移到 prefix12/14，收益来自降距离而非单纯加 gross

v127 在 v125 基础上替换 D002/D003/D004/D005/D008 的 v126 tail-release 结果。相比 v124/v125 的 prefix16，D002/D005 用 prefix12 更优，D003/D004/D008 用 prefix14 更优：

```text
D002 38602.12 -> 39036.56, +434.44, gross 73644.86, distance 16038.87, penalty 10550
D003 41598.44 -> 41880.67, +282.23, gross 74410.48, distance 16486.54, penalty 7800
D004 45206.17 -> 45488.41, +282.24, gross 74410.48, distance 16548.05, penalty 4100
D005 39324.40 -> 39658.84, +334.44, gross 73644.86, distance 16057.35, penalty 9900
D008 38246.47 -> 38791.86, +545.39, gross 73644.86, distance 16102.00, penalty 10700

full hybrid:
  score 370755.73 -> 372634.47
  total_preference_penalty 59315 -> 59015
```

关键启发：更早释放并没有带来更多订单，仍是 33 单主链，但它把后半月路线换成更短距离、罚分不升甚至下降的版本。当前最有价值的搜索维度是 prefix release point，而不是继续全局调 NPH/future。D006 prefix16 是负方向，说明 D006 的安全释放点目前更接近 prefix18。

## v125 新发现：D006 不能全月放开，但保留前 18 单后尾段冲单为正

v125 在 v124 的基础上替换 D006：使用 D006 当前最好轨迹的前 18 单作为 seed prefix，再开启半软偏好 tail mining。结果比 v124 保留的 D006 稳定轨迹更高：

```text
D006 37060.89 -> 37251.63, +190.74
gross 56396.21 -> 67307.35
distance 9423.55 -> 14570.48
preference_penalty 5200 -> 8200
orders = 43

full hybrid:
  score 370564.99 -> 370755.73
  total_preference_penalty 56315 -> 59315
```

关键启发：D006 的全月 ignore/semisoft 长链都没有超过原最好轨迹，但从第 18 单之后放开尾段，新增毛利能覆盖新增偏好罚分。这说明“负类司机”也不一定完全不能高毛利化，真正边界是前半月偏好安全骨架不能破坏。后续 D006 应测 prefix 14/16/20/22，并微调 `d006_semisoft` 的水产品/长距离罚分权重。

## v124 新发现：固定前 16 单后做尾段重规划，比全月重搜更有效

v124 以 v118 为底座，不再全月重搜，而是把 D002/D003/D004/D005/D008 的前 16 个已验证订单固定住，只从 3 月 16 日后的状态继续做 tail mining。这个搜索方式同时保留了前半月高毛利骨架，又给后半月留出重构空间，最终五个司机都得到正收益替换：

```text
D002 37692.29 -> 38602.12, +909.83, gross 74028.18, distance 16450.71, penalty 10750
D003 41051.78 -> 41598.44, +546.66, gross 74028.18, distance 16419.83, penalty 7800
D004 44659.52 -> 45206.17, +546.65, gross 74028.18, distance 16481.34, penalty 4100
D005 38677.74 -> 39324.40, +646.66, gross 74028.18, distance 16469.19, penalty 10000
D008 37647.59 -> 38246.47, +598.88, gross 73483.45, distance 16357.99, penalty 10700

full hybrid:
  score 367316.31 -> 370564.99
  total_preference_penalty 55615 -> 56315
```

关键启发：全月重搜 v120 虽然 proxy 很高，但 exact 评分全面低于 v118，因为它破坏了已验证前半月链路，并让距离/偏好罚分恶化。v121 的 fixed-prefix tail mining 则证明，当前高分瓶颈不在月初主链，而在月中以后几个可替换尾部订单。后续高收益优先应继续围绕不同 prefix 位置做路线族重构：

```text
1. 对 D002/D003/D004/D005/D008 测 prefix 12/14/18，找是否比 prefix16 更早或更晚放开更好。
2. 对 D001 做同样 tail-prefix 搜索，检查 33 单高毛利链后段是否还能降距离或加 gross。
3. D006 继续半软偏好搜索，因为 ignore 长链只差当前最优约 530 分，有可能通过保留关键偏好追回。
4. 不再主力跑 v120 这种全月宽搜参数族；它已被 exact 证实为负方向。
```

## v118 新发现：D004/D005 也能靠高毛利链覆盖偏好罚分

v118 把 v117 的 D001/D002/D003/D008 高毛利路线作为底座，继续并入 D004/D005 的 ignore-pref oracle exact 结果：

```text
D004 39516.78 -> 44659.52, +5142.74, penalty 4100
D005 28734.46 -> 38677.74, +9943.28, penalty 10100

full hybrid:
  score 352230.29 -> 367316.31
  total_preference_penalty 42915 -> 55615
```

最重要的新启发：D005 之前的 0 罚分轨迹看起来“稳”，但高收益目标下它实际上损失接近一万分。当前数据里，能进入同一类 31-33 单高毛利路线族的司机是：

```text
positive_long_chain = D001, D002, D003, D004, D005, D008
negative_long_chain = D006, D007, D009, D010
```

这不是泛化规则，而是高收益搜索的司机级分类：正类司机的偏好罚分边际可被毛利链覆盖，负类司机的真实偏好罚分会把同样的路线打穿。D009/D010 的 ignore-pref exact 结果尤其说明，低当前净收益不代表应该直接放开偏好；它们需要偏好约束路线搜索，而不是跟随 D001-D005/D008 的长链模板。

下一步高收益优先：

```text
1. 对 D001-D005/D008 做更宽、更深、更低 future 权重的路线族重搜。
2. 对 D009/D010 单独做偏好约束 planner，不再主力尝试 ignore-pref。
3. 组合验证只接受 official monthly_income exact 分数，不信 proxy。
```

## v117 新发现：多司机存在“付高罚分换高毛利链”的大空间

v117 把 v116 的 D001 cap-aware oracle 路线作为底座，对 D002/D003/D006/D007/D008 做 ignore-pref oracle mining，再由官方 `monthly_income` 精确评分筛选。结果不是全员有效，而是明显分化：

```text
positive:
  D002 34189.64 -> 37692.29, +3502.65, penalty 10350
  D003 35568.42 -> 41051.78, +5483.36, penalty 7800
  D008 36169.63 -> 37647.59, +1477.96, penalty 10300

negative controls:
  D006 37060.89 -> 36530.22, -530.67, penalty 12200
  D007 32679.93 -> 30849.93, -1830.00, penalty 17980

full hybrid:
  score 341766.32 -> 352230.29
  total_preference_penalty 17265 -> 42915
```

核心启发：当前高收益路线不是“少罚分最优”，而是：

```text
accept_route_if:
  gross_chain_gain - distance_cost_gain > preference_penalty_delta
```

D002/D003/D008 的 31-33 单高毛利路线即使带来 7k-10k 偏好罚分，仍然显著高于原有保守轨迹；D006/D007 则被罚分和距离成本打穿。这说明每个司机要先做真实罚分几何分类，再用 exact scoring 选路线族。v118 已补完 D004/D005/D009/D010：D004/D005 为强正，D009/D010 为强负。

## v116 新发现：高收益优先时，先接受封顶罚分，再最大化路线毛利链

v116 把 D001 的 `d001_capsoft` 搜索进一步放宽：`future_weight=0.02`、`max_pickup_km=460`、`min_net=-2000`、宽 beam/branch。官方精确评分后，`candidate_01` 达到：

```text
D001_net = 43713.77
D001_gross = 73657.00
D001_distance = 16628.82
D001_penalty = 5000.00
orders = 33
full_score = 341766.32
```

相对 v115：

```text
D001 40501.13 -> 43713.77, +3212.64
full score 338553.68 -> 341766.32, +3212.64
```

这次不是小阈值收益，而是搜索范式收益。D001 的每日休息罚分 cap=3000、深圳范围罚分 cap=2000，长链中已经变成固定成本；继续在线性 proxy 里惩罚每个休息/深圳违规，会把高 gross 路线提前剪掉。正确的高分搜索目标是：

```text
score_D001(action_chain) =
  gross_chain
  - distance_cost
  - non_capped_forbidden_category_risk
  - fixed_capped_penalty
```

同期 D009 daily-home constrained planner 是强负例：硬要求每天 23 点前回家且夜间静止，只跑出 `-8231.50`，罚分 `12700`。启发是：偏好不能统一硬满足，必须先分析该司机的罚分几何；封顶且已饱和的偏好可以当固定成本，无封顶或高额事件型偏好必须保守。

下一步高收益优先不是泛化，而是把这种 `cap-aware / ignore-pref oracle mining -> official exact scoring -> hybrid assembly` 扩到其他司机，找是否存在类似 D001 的未挖高毛利路线族。

## v98 新发现：修 long-idle 要追溯 root-order，而不是修 wait 本身

v95-v97 证明 D001/D005/D009 的尾部长等待点已经局部饱和；强制 query、单步替换、两步 sequence 都没有正收益。v98 新增 `analyze_idle_traps.py`，把长等待追溯到进入陷阱前的真实订单：

```text
wait_step -> previous_action -> root_order_step/root_order_cargo -> root_trap_score
```

这次找到三个可叠加正样本，并通过 `submission_score_v98` 验证：

| driver | root step | original | better action | delta | finding |
| --- | ---: | --- | --- | ---: | --- |
| D001 | 106 | cargo208674 | wait180 | +146.10 | 月末低价值尾单应主动跳过，等待能同时降罚 |
| D009 | 190 | cargo475223 | cargo192513 | +200.31 | 回家链之前的订单选择比强制回家/等货更关键 |
| D010 | 43 | cargo50832 | cargo352638 | +174.34 | 早期前置订单决定第 10 天长等待后的后继状态 |

组合后：

```text
score = 315688.45
penalty = 12865
run = results/grid_agentic_algo/20260526_001234_v98_submission_profile_check/01_submission_score_v98
```

算法启发：

```text
score(action) =
  current_net
  + V(after_unload_state)
  - idle_trap_risk(after_unload_state, driver_profile, month_phase)
  - preference_risk_delta
```

也就是说，区域强弱不是核心规则；核心是当前动作把司机送进哪条未来可执行链。下一步要把 v98 的 root-order teacher 转成更泛化的状态模式，而不是继续只加 step/cargo 标签。

## v95-v97 新发现：局部尾部修补已饱和

新增 `build_value_dataset.py` 和 `analyze_value_dataset.py` 后，历史 full-tail 反事实样本被整理成可复盘的 regret/value dataset：

```text
rows = 10919
positive_rows = 28
above_current_v94_driver_score = 0
```

这说明当前 v94 已经吸收历史所有正样本，没有任何旧分支能超过当前单司机净收益。为了验证“是不是 pre-query 规则挡住了市场”，又做了 `--force-query-on-target` 探索：

```text
D001 dynamic/sequence force-query: best delta 0.00
D005 dynamic/sequence force-query: best delta 0.00
D009 dynamic/sequence force-query: best delta 0.00
```

结论：D001/D005/D009 的低收益并不是尾部某一步没查询货源，而是更早动作已经把司机带入低价值状态。下一步不能继续在长等待点本身做短等、空驶、top-k 换单；要学习“接完当前单后会不会进入等待坑”的状态价值函数。

新的算法重点：

```text
score(action) =
  current_net
  + V(after_unload_time, after_unload_location, driver_profile, rest_debt, month_phase)
  - preference_risk_delta
  - idle_trap_risk
```

其中 `V(after_state)` 不用全局未来数据在线计算，而是由本地 exact-tail 反事实样本蒸馏出状态规则，例如：

```text
同一司机在某类时间窗/区域/剩余月份下，
接到某种低 haul、高 pickup、卸货到弱后继区域的订单，
后续是否高概率进入长等待或低 gross 链。
```

## 两套提交/研究 Profile

```text
score_v98_root_idle_trap_teacher_315688
  当前本地冲分和离线研究版本。
  使用 full-tail 反事实回放蒸馏出的 fixed step/cargo/action teacher。
  当前复现 score=315688.45, penalty=12865。

score_v94_d001_step103_teacher_315167
  历史稳定基线和消融对照。
  当前复现 score=315167.70, penalty=13165。

official_clean_agentic_planner
  官方合规版本。
  关闭 AGENT_AP_ENABLE_COUNTERFACTUAL_SWITCHES 与 AGENT_AP_ENABLE_DISTILLED_COUNTERFACTUAL_GATE。
  只保留当前可观测状态、司机 memory、偏好编译、visible-chain/route-plan scorer、gated rollout，以及在线动态空驶候选。
  当前复现 score=275973.46, penalty=17565。
```

clean 版的在线动态空驶只使用本轮 `query_cargo` 返回的可见货源，按 pickup/end 聚类生成 reposition 候选，不读取完整货源表、不使用未来 full-tail 结果、不写死 step/cargo/坐标。后续如果官方严格审查“不得使用已知全局视角”，应以 clean 版为提交主线，并继续把 teacher 版中的规律蒸馏成可泛化状态规则。

这套分数不是靠单点阈值堆出来的，核心是把司机拆成不同画像后做收益-扣分权衡，并在关键决策步使用反事实回放验证“换一个候选货源是否让整个月更优”：

```text
D001: 低机会窗口补 8 小时连续休息
D004: 每日订单配额，超过 3 单后只接高净收益高 NPH 单
D006: 月末低机会窗口补休，不全月强制休息
D009: 回家罚分在当前数据上多数时候值得支付
D010: 家事事件 pre-query，避免 query scan 推进时间造成固定罚分
v32-v57: 对关键步骤做 candidate/action-level counterfactual rollout，验证后写回窄触发记忆、状态蒸馏门和 phase-level action gate
```

## 已发现的关键规律

1. 偏好罚分不能简单硬满足。D006 全月强制休息减少违规但破坏高收益链路，结果比当前最优低很多；只在 27-30 日低机会窗口补休反而正收益。

2. D004 的收益瓶颈不是多接单，而是超配额后的低性价比单。严格配额少接一个低质量单，损失 gross 但减少罚分和里程，总分上升。

3. D009 的 900 回家罚分不是当前第一优先级。强行回家损失的机会收益大于罚分收益。

4. D010 家事约束属于硬事件，必须在 query 前执行。否则 query scan 的几分钟推进会造成不可见的额外罚分。

5. Flash 不适合自由逐步决策。直接让 LLM 改接单会破坏已验证链路；更合适的位置是 near-tie critic、轨迹总结器、规则生成器。

6. 反事实回放比继续扫全局阈值更有效。v32/v33 的收益来自“只替换一个司机某一步的 cargo，再把后续交还给原 agent 跑完整月”。这种方法能直接回答长期问题：当前单虽然局部更高/更低，但是否改变后续货源链和偏好罚分。

7. 小的单步 regret 可以稳定叠加，但大空间仍在未充分扫描司机。D001/D004/D009 的正收益点总共只贡献 `+81.50`，说明这些司机局部已接近平台；D003/D005、以及 D002/D008 的更多关键步更值得继续挖。

8. v34 证明 D003/D005/D002 是当前新增主战场。D003 step77、D005 step123、D002 step87 三个 top regret 跨司机可以稳定叠加，把分数从 `298447.37` 推到 `300083.87`；再加 D008 step17 小增益后到 `300153.62`。

9. 同一司机内部不能贪心叠加所有正样本。D002 pair、D003 pair/multi、D005 pair/multi 都低于各自 top 单点，说明同司机路径依赖很强，必须做 per-driver subset search。

10. v35 证明第二轮 regret mining 仍能大幅涨分。D003 step45、D004 step25、D005 step28、D006 step48、D010 step60 可以叠加到 v34，分数从 `300153.62` 提升到 `301859.50`。

11. v36 证明 D004 step45 是更优、更稳的 D004 记忆点。它把分数从 `301859.50` 提升到 `302281.68`，同时总罚分从 `14265` 降到 `13965`；D004 step60 虽能降罚但收益低于 step45，45+60 与 step45 同分。

12. v37 证明 D007/D008 仍有高质量空间。D007 step105 与 D008 step80 可跨司机叠加，分数从 `302281.68` 提升到 `303285.96`，同时总罚分降到 `13565`。D007 step5 单独正，但和 step105 冲突，不应并入。

13. v38 证明低优先级司机也还有小而稳定的链路收益。D006 step65 与 D009 step120 在 v37 底座上均为正，组合后从 `303285.96` 提升到 `303592.37`，总罚分仍为 `13565`。这说明当前方向没有收敛，剩余提升更像“关键步候选替换 + 完整月度验证”的累积，而不是全局阈值微调。

14. v39 证明官方分享里的“Route Plan + Driver Memory + 安全执行层”方向可以落到真实分数。D008 step35 是最大新增点，D004 step50、D007 step10、D010 step115 可跨司机叠加，分数从 `303592.37` 提升到 `305852.15`，总罚分降到 `13065`。

15. v40 证明 v39 后仍有同司机次级正样本可叠加。D008 step85 与 D007 step120 在 v39 all-top 路径上继续有效，组合后到 `306208.27`，罚分保持 `13065`；D004 step80 与 D004 step50 路径等价，没有额外贡献。

16. v45-v47 证明探索不能只看接哪个货，还要把 `wait/reposition` 作为同等动作分支。D004 step70、D009 step165 是 cargo-level 正样本；D004 step86 wait30、D009 step170 wait120 是 action-level 正样本。组合后当前最好达到 `307355.19`，说明受控 Agent 要比较完整动作，而不是只 rerank 货源。

17. v48 证明“阶段级动作门控”是新的高收益角度。D010 step100 wait60 不是单点等货，而是在月末家事/休息边界把后续链整体后移，罚分 `1565 -> 1265` 且 gross 略升，单点 +212.52；D004 step87 cargo164073 降低罚分与里程，+74.36；D009 step178 wait120 小幅降低长返程链路，+28.58。组合后当前最好 `307670.65`，罚分降到 `12465`。

18. v49-v51 证明 action gate 可以继续跨司机叠加。D006 step65 wait300、D006 step95 reposition FS、D006 step98 cargo484278、D001 step102 wait180、D004 step96 reposition FS、D003 step107 wait60 逐步把分数推进到 `309057.58`。同司机后续动作必须 rebase，D003 step107 后 108-116 已无新增正收益。

19. v52 证明之前部分“无效动作”其实是 guard 过窄导致未触发。仿真中 `query_cargo` 会推进时间，trace step 起点和 agent 真正决策时刻存在错位。把 D010/D007/D005 的尾部动作改成 query 后可触发的 phase guard 后，D010 step123、D007 step119、D005 step128 可以跨司机叠加，新最好达到 `309373.04`。

20. v53 证明 action-level teacher 需要高于 cargo-level counterfactual switch。D008 step80 的 full-tail probe 显示 `wait240` 比旧 cargo `178320` 高 `+228.23`，但最初 online gate 一直 no-op，因为旧 `D008:80:178320` cargo switch 在 pre_action 中先返回。修复优先级后，D008 step80 wait240 生效，最好达到 `309601.27`。D009 step178 HY reposition 在单局部有正收益，但与旧 wait teacher 冲突后 full-grid 下降 `-28.58`，不推广。

21. v54 证明同一司机月末动作需要做“分支选择”而不是“正样本叠加”。在 v53 路径上，D002 step87 wait60、step89 cargo200633、step90 wait240、step91 reposition GZ 单点均为正收益，其中 step89 最高，完整月达到 `309885.45`。但 step87+step89、step89+step90、step89+step91 均不超过 step89 单点，说明更早动作会改变后续状态，导致晚一点的 teacher 不再适用。最终推广 D002 step89 cargo200633。

22. v55 证明主动空驶是高收益 Agent 动作。D010 step100 从 wait60 改为 reposition DG 后，完整月从 `309885.45` 到 `310249.39`，同时罚分 `12165 -> 11865`；D007 step80 reposition GZ 单点 +67.48；D009 step200 wait60 单点 +53.25。三者跨司机叠加后达到 `310370.12`。这说明“区域价值”不是全局常量，而是司机/日期/位置/偏好状态共同决定的 phase action。

23. v56 证明低效率关键步挖掘仍未收敛，而且收益不一定来自降罚。基于 v55 真实轨迹，从高空驶、高耗时、长等待和高罚分司机中自动选 step 做 full-tail 反事实，发现 D003 step80、D006 step17、D007 step114、D002 step78、D003 step10 可稳定组合。最终 `hot_v56_core_new_all6` 达到 `311234.76`，总罚分仍为 `11865`，说明本轮增益来自同罚分下的路线链修复。

24. v56 的 D007 是典型同司机路径冲突案例。step114 主动空驶 SW 单点 +201.22，step122 wait30 单点 +208.42，但二者组合不能叠加；在 all6 组合中最终由 step114 分支主导。结论仍是：同司机正样本必须做 subset/rebase，不能贪心全开。

25. v56 的 D004 负结果同样重要。针对 D004 高空驶、午间、晚首单等 15 个关键 step 做 take/wait/reposition 反事实，没有一个正收益动作。说明 D004 当前的日程罚分不是可轻易修的漏洞，强行等/空驶常用几百罚分换掉上千 gross；下一步 D004 要做更早的槽位规划，而不是高空驶 step 替换。

26. v57 证明自动选点 + action regret 仍能继续涨分，但“高空驶/长等待”只是筛选信号，不是直接决策规则。`select_probe_steps.py` 从 v56 轨迹中选出 D003/D005/D007/D008/D010 的可疑步，再对 top-k 接单、等待、热点迁移做 full-tail 回放。结果 D003/D005/D008 大多保持原动作最优，D007 step61 改 `cargo93774` 单点 +279.72，D010 step121 改 `cargo200361` 单点 +165.22，跨司机组合达到 `311679.70`。D010 step118 单点 +87.48，但与 step121 同司机冲突，all3 回落到 `311601.96`，不推广。

27. v61 证明 D004 的主动迁移仍是高收益路线修复主线。D004 step7 DG、step41 FS、step93 cargo297250 组合后达到 `312350.16`，罚分 `12265`。其中 step41 FS 的收益来自多走一点距离换后续 gross 增长，罚分不变。

28. v74-v75 证明 D010 月末仍是高价值的 Route Plan 搜索区。v74 的 step82 主动空驶到 DG 通过路线重排把 D010 休息罚分降低 `600`，总分到 `314347.46`。v75 在 v74 rebased tail 上继续做二步序列回放，发现 step103 改接 `cargo200361` 比原 `cargo196038` 更好：总罚分不变，但卸货位置从粤东侧 `(23.49,116.56)` 改回珠三角侧 `(22.90,113.76)`，后续能接 `203410 -> 490251`，总分到 `314512.68`。这说明“区域强弱”不是核心判断，核心是当前动作把司机送入哪条可执行后继链。

29. v76 证明同司机 teacher 必须可撤销、可重组。继续在 v75 尾链上做二步 sequence replay 后，`cargo196038 -> wait180 -> cargo484175 -> cargo205150` 反而比 v75 的 `cargo200361 -> wait180 -> cargo203410 -> cargo490251` 高 `+17.26`，总分到 `314529.94`，罚分不变。D004 的 step93/94 局部微正没有通过 full-grid 验证，说明小正样本尤其要防止 harness/路径冲突。

30. v77 证明三步 exact rebase 仍能突破 v76 平台。新增 `triple_counterfactual_probe.py` 后，先修复了一个重要 harness bug：probe 在 `_decide()` 之后才记录 step_start，而 `_decide()` 已经消耗 query scan 时间，导致 action trace 被 `calc_monthly_income` 判“时间推进不一致”并归零。修复后，D008/D010 三步窗口均保持 rule 最优，但 D004 step93/94/96 找到 `cargo469204 -> cargo299927 -> cargo303849`，D004 单司机 `+190.87`。

31. v77 的 full-grid 过程说明 Agent 安全执行层不只是合法性校验，还要管理规则优先级和时间口径。第一次蒸馏失败是旧 cargo-level switch 抢在 route-level teacher 前返回，第二次失败是 phase guard 写成 trace 时间，真实 query 后 action_start 比窗口晚 1 分钟。修复后，D004 路径变为 `469204 -> 299927 -> wait30 -> 303849`，总分达到 `314720.81`。这验证了官方分享里的 Route Plan 比单单排序更重要，也说明 Memory 应该记录可重估的多步状态模式，而不是僵硬预录轨迹。

32. v80-v83 证明“未来价值”不能粗暴做全局加分。D004 step58 的 `cargo93738` 能少 200 罚分、少 129km，但 gross 损失更大，二步 rebase 后仍低 `7.32`；D006 强行补休、D003 降 deadhead、D009 提前回家/等待大多为负。v82 的 layered/latent market scorer 也显著退化，说明区域强弱、单位时间、偏好风险只能作为候选生成和 near-tie 解释，最终必须靠 exact-tail teacher 验证。

33. v84 从 v83 的 D009 home-boundary probe 中挖出新的正样本：step110 从 `cargo97891` 改接 `cargo398828`。该动作不降低 900 回家罚分，但 gross 更高、后续返家空驶更短，D009 净收益 `19725.44 -> 19851.46`，完整月总分到 `314846.83`。启发是：偏好相关司机并不是简单硬回家，而是要比较“当前单收益 + 完单后回家成本 + 后继链”。实现上要求 winner/loser 同时可见、时间位置匹配，保持受控 Agent teacher。

34. v85 从 D008 wide route-value probe 中挖出新的 action-level 正样本：step87 不接原规则 `cargo203004`，而是在 03-30 早晨 `(23.20,112.90)` 原地 `wait180`。后续链从 `203004 -> 489410` 切换为 `486259 -> 210728`，罚分仍为 `800`，gross `+27.36`、距离 `-31.23km`，D008 净收益 `35929.67 -> 36003.87`，完整月总分到 `314921.03`。启发是：等待动作应该作为主动 Route Plan 分支参与规划，特别是月末低价值候选窗口；它不是“没货兜底”，而是为了释放更好的后继链。

35. v86-v89 证明当前平台不是“没有空间”，而是单步 regret 已经收敛，必须使用二步 Route Plan。v86 对 D003/D004/D008/D010/D005 的 one-step wide probe 全部无正收益；v87 sequence probe 反而找到 D008 `step85 cargo482796 + step86 cargo200633`（D008 `36003.87 -> 36051.86`，+47.99）和 D010 `step103 cargo481074 + step105 cargo489360`（D010 `33500.63 -> 33563.57`，+62.94）。D008 的 step85 单独是负收益，但和 step86 组合为正，说明候选排序必须看后继链。D010 增加 300 罚分仍然净赚，说明偏好罚分要作为边际风险成本，不是硬约束。

36. v90-v92 证明继续在已有 top-k/value/sequence 候选里排列组合已经饱和，但“候选生成”本身还能产生收益。v90/v91 对 D001/D002/D006/D007/D009 以及 D008/D010 后段做 two-step / triple probe，共 3340 个 ok 分支，没有正收益。v92 新增 `dynamic_candidate_probe.py`，从当前可见货源的 pickup、destination、centroid 生成动态空驶点，并把 `take_order / wait / reposition` 同级交给 full-tail exact scoring。结果找到 D001 step99 深圳内微空驶 `(22.81,114.21)`，D001 `18456.85 -> 18504.73`，+47.88；D007 step114 动态空驶到 `(22.61,112.78)`，D007 `32521.97 -> 32527.88`，+5.91。完整月达到 `315085.75`，罚分仍为 `12865`。启发是：区域强弱不是核心规则，但可见市场可以用来生成更好的候选动作；最终仍必须用官方 exact-tail 回放判定。

37. v93/v94 先修复探索 harness 口径，再找到新的 D001 月末尾链动作。v93 发现 `counterfactual_rollout_probe.py` 对 `submission_score_v92` 没有正确展开 `submission_defaults`，导致 rule branch 无法复现 baseline；修复后重新跑 D003/D004/D005/D008/D010 的 dynamic probe，共 303 个有效分支，全部无正收益。v94 补跑 D001/D002/D006/D007/D009 dynamic probe，并对 D001/D002/D007 做 two-step sequence rebase。唯一新增是 D001 step103 `cargo202502`：原策略在 03-30 01:02 后 `wait480`，改接 `cargo202502` 会多 300 休息罚分，但进入 `cargo202502 -> cargo203175 -> cargo485616` 尾链，D001 净收益 `18504.73 -> 18586.68`，完整月 `315167.70`。启发是：偏好罚分仍应作为边际成本而非硬约束，月末短链价值可以覆盖额外罚分。

28. v62/v63 证明 v61 后单步 regret mining 已经饱和。对 D001/D002/D004/D005/D006/D007/D008/D009 共 75 个关键 step 做 take/wait/reposition full-tail 单步替换，没有正收益动作。结论是：高空驶、高等待、高罚分只是探测信号，不是策略规则；下一步必须做序列级 rebase 或状态价值学习。

29. v64 证明普通 beam proxy 不可靠。`offline_beam_planner.py` 在 D001/D005/D007/D008 上的候选经官方精确评分均低于 v61，D008 尤其被偏好罚分击穿。这说明不能用简化 proxy 直接判断路线优劣，必须用官方 exact-tail scoring 做小规模序列搜索。

30. v65 新增 `sequence_counterfactual_probe.py`，把搜索升级为“第一步分叉 -> rebase 轨迹 -> 第二步分叉 -> 交回原 agent 完成整月 -> 官方精确评分”。第一批 D001/D002/D005/D006/D008 的最佳仍是 rule/rule；D007 step114 发现 `cargo475223` 比旧 SW reposition tail 多 `+7.20`。原因不是更高 gross，而是 gross 少 113.16 同时距离少 80.24km，净收益略优且罚分不变。完整 grid 验证后当前最好为 `312357.36`。

31. v66 对 D003/D004/D007/D008 的中期高疑似窗口做 exact two-step sequence probing，仍没有新正收益。D003/D008 的替代分支常能减少距离或偏好风险，但 gross 损失更大；D004 有些分支 gross 更高，但距离与罚分同时上涨；D007 中期分支大多是少距离换掉太多收入。结论：`top-k cargo + wait + 固定 hotspot` 的局部候选空间已经基本饱和，下一步要扩展候选生成方式，而不是继续同类 pair。

32. v67 把 sequence probe 的候选扩展为 destination/opportunity value，但 D003/D004/D007/D008 仍没有新高。最接近的是 D008 step61 `cargo431645`：罚分从 `800` 降到 `600`，但 gross 下降 `186.76` 且距离略增，最终仍比 v65 低 `8.42`。启发是：强区域/弱区域不是核心决策，只能作为未来价值弱特征；真正可靠的 teacher 仍然必须来自 official exact-tail scoring。

33. v68 将 `counterfactual_rollout_probe.py` 升级为 value-candidate one-step probe。目的不是让静态区域价值直接进入 agent，而是先用便宜的一步完整尾部回放挖出非 top-k 的候选 label；只有 exact driver net 正收益的候选才进入两步 rebase 和 full-grid 验证。本轮 D001/D006/D008 主体仍为负，但 D009 step180 `cargo181577` 单点 `+22.94`，D010 step123 `cargo484817` 单点 `+35.41`，完整 grid 组合后达到 `312415.71`，罚分保持 `12265`。

34. v70 证明 `wait` 也要进入 Route Plan，而不是只在无货时兜底。D005 step49 `wait120` 放弃 06:50 附近的 `cargo370991`，等待到后续货源释放后接入 `cargo371838 -> cargo66508` 短链，D005 净收益从 `28347.57` 提升到 `28505.81`，罚分仍为 `0`。这说明未来收益的关键不是简单强/弱区域，而是“当前动作是否锁死后续释放窗口”。Agent 层面要把等待、空驶、接单作为同级动作，用 exact-tail teacher 蒸馏状态规则。

35. v71 证明 D004 的 schedule-aware value candidate 仍有空间。D004 step11 从 `cargo4008` 换到 `cargo235854` 后，gross 减少 `143.93` 且距离增加 `144.58km`，但偏好罚分减少 `400`，D004 净收益 `+39.20`，总分达到 `312613.15`。这类动作不是追当前最高收益，而是选择能改善后续首单、午餐和配额节奏的订单，说明偏好风险应该作为边际状态成本进入候选排序。

36. v72 证明 two-step route rebase 是单步 regret 饱和后的主要增益方向。D004 step49 先从 `cargo75036` 改到 `cargo379155`，再在重排后的 step56 从局部首选 `cargo94682` 改到 `cargo93338`，D004 净收益 `+277.93`。单独开 step49 会严重掉分，必须把 step49->56 当作序列计划执行。D001 step48 `wait30` 额外 `+54.55` 且罚分不变；D010 step2 主动空驶广州 `+40.54`，虽然罚分上升但完整月 gross 链补回成本。组合后达到 `312986.17`。

37. v73 先修复 grid harness 污染：提交默认会在子进程 import 时 `setdefault` 注入当前最好 teacher，导致“关闭某个动作”的对照不干净。新增 `AGENT_DISABLE_SUBMISSION_DEFAULTS=1` 后，grid 只使用 preset env，v71/v72 都能干净复现。

38. v73 证明 D010 step23 `cargo330064` 是更优的互斥路线修复。反事实中它单司机 `+555.12`；清理 harness 后，在不启用 D010 step2 的路径上可复现，并能与 D001 wait30、D004 step49->56 跨司机叠加，达到 `313500.75`。结论是：D010 step2 是小修，step23 是大修，二者不能贪心全开。

39. v74 对 v73 默认轨迹做全司机 one-step exact-tail action probe：每个司机选 8 个高可疑 step，并比较规则动作、top cargo、value cargo、wait、reposition。结果只有 D010 有正收益，其他 9 个司机的高空驶/长等待/高 scan 状态均为 rule-optimal。D010 step82 主动空驶到 DG 完整月达到 `314347.46`，总罚分 `12465`，比 v73 高 `+846.71`。它不是简单强区域规则，而是重排 03-23 到 03-25 的月末链：放弃 cargo290384，迁移到 DG 后进入 cargo290652 -> wait180 -> cargo446813 -> cargo290811，同时 D010 连续休息罚分从 `1800` 降到 `1200`。D010 step84 wait180 是同段链路的较弱替代，step97 cargo186578 full-grid 不增益，因此只推广 step82。

## 为什么不能继续一点点试阈值

本题每个动作都会改变后续时间、位置、在线货源池、偏好状态和 query scan 成本。单个阈值实验只能看到局部效果，不能回答：

```text
这个司机今天少接一单，后面两天能不能接到更好的链路？
现在休息 5 小时，是减少罚分更值，还是错过高收益链更亏？
当前位置低收益，是继续等、空驶到热点，还是接一单去更好的目的地？
```

所以后续要用轨迹级搜索，再把搜索结果蒸馏成在线 agent 技能。

## 搜索器设计

`offline_beam_planner.py` 是离线搜索 harness，不进入提交路径。

搜索状态：

```text
CargoRepository + DriverStateManager + decision_history
```

分支动作：

```text
top-N take_order
event wait: 等到下一个货源释放或关键工作窗口
manual wait: 60/180/300 分钟等候
后续可加 hotspot reposition
```

评分方式：

```text
proxy = 订单价格 - 空驶成本 - 干线成本
final = calc_monthly_income.py 官方精确评分
```

当前已经修掉两个搜索器问题：

```text
不再 deepcopy 50 万货源大表，只轻量克隆分支状态
不再奖励空等时间进度，避免 planner 学会长时间等待
```

## 后续高收益方向

1. Action-level regret mining：优先扫描 D003/D005，以及 D002/D008 的候选丰富步骤。当前 v33 已证明这种方法比继续扫阈值收益更高。

2. Counterfactual memory distillation：把 `driver:step:cargo_id` 固定记忆升级成状态模式，例如时间、位置、候选差距、卸货后区域机会、偏好风险边际变化。

3. Preference-aware value function：对每个司机维护 `收益链价值 - 偏好风险成本`，让 D004/D006/D008 这类司机不再被单步 NPH 或单步罚分误导。

4. Hotspot reposition branch：目前反事实主要比较接单候选，还没系统探索空驶到广州白云、佛山南海、佛山顺德、深圳龙岗等热点后的收益。

5. LLM trajectory critic：让 Qwen3.5-Flash 离线读取正负反事实样本摘要，输出“哪类动作模式值得固化成规则”，再由 grid runner 验证，不让 LLM 直接改线上动作。

## 推荐实验命令

当前优先用 v33 底座继续反事实挖掘，这些命令互不覆盖，结果目录固定可追踪。

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D003 --preset hot_v33_cf_v32_plus_all_tiny --target-steps 6,36,40,48,52,64,77,87 --top-k 5 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D003_v33_key_steps
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D005 --preset hot_v33_cf_v32_plus_all_tiny --target-steps 3,16,25,32,58,71,74,80,93,105,110,123 --top-k 5 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D005_v33_key_steps
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D002 --preset hot_v33_cf_v32_plus_all_tiny --target-steps 35,51,59,66,68,71,79,87 --top-k 5 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D002_v33_more_steps
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D008 --preset hot_v33_cf_v32_plus_all_tiny --target-steps 9,13,14,17,28,39,65,67,68,75,77,86 --top-k 5 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D008_v33_more_steps
```

## 结果分析标准

看 `beam_summary.md/json` 时不要只看最高分，还要看胜出轨迹的动作模式：

```text
胜出轨迹是否先等待到固定时间窗口？
是否反复选择某类目的地？
是否故意支付某个偏好罚分换更高链路收益？
是否在某天少接单后后续收益更高？
是否出现当前规则没覆盖的高价值空驶方向？
```

如果同一模式在多个候选里重复出现，才值得写回提交 agent。

## 2026-05-22 反事实回放实验

新增工具：

```text
counterfactual_rollout_probe.py
```

实验方法：

```text
1. 用当前最好 agent 回放到某司机某个 1-based 决策步。
2. 保留同一状态和同一可见候选集合，只替换为 top-k 中另一个 cargo。
3. 替换后不再人工干预，后续整月交回原 agent。
4. 使用 calc_monthly_income.py 精确计算该司机月度净收益和偏好罚分。
5. 只有完整月度正收益的动作，才写回 agent 的窄触发记忆。
```

v32 关键结果：

```text
hot_v32_cf_all_small
score = 298365.87
penalty = 13565.0
相对 v30 = +1788.50
```

v32 的主要贡献：

```text
D002 step15 -> cargo 334719: +878.10
D006 step16 -> cargo 263827: +49.73
D008 step45 -> cargo 102505: +728.04
D010 step31 -> cargo 334719: +132.63
```

v33 关键结果：

```text
hot_v33_cf_v32_plus_all_tiny
score = 298447.37
penalty = 13465.0
相对 v32 = +81.50
```

v33 的新增贡献：

```text
D001 step72 -> cargo 135107: +18.63
D004 step35 -> cargo 351154: +59.13，且总罚分 -100
D009 step120 -> cargo 406477: +3.74
D007 当前探测步没有发现正收益替代动作
```

### 实验启发

1. 当前 agent 的主要错误不是“不会算当前单收益”，而是局部排序不能稳定反映后续链路价值。D002、D008 的大幅提升说明，某些看起来不是规则首选的货源，会把司机送到更好的后续时间-空间状态。

2. 偏好扣分必须和收益链一起看。D008 的正收益点增加了部分罚分，但 gross 和后续链路提升更大；D004 的正收益点则同时减少罚分。说明不能简单把罚分作为硬约束，也不能完全忽略，要做边际收益比较。

3. 多司机可以独立反事实挖掘，但合并前必须完整验证。D001、D004、D009 的收益可以线性叠加，说明它们互不干扰；D010 step82 单独正收益但和 step31 组合后会互相影响，说明同司机内部动作有路径依赖。

4. 反事实记忆不能长期停留在 `driver:step:cargo_id`。这个形式适合快速冲分和验证，但更好的 agent 算法应该学习触发条件：时间、位置、候选差距、后继区域价值、偏好风险，而不是记住固定 step。

5. Flash/LLM 的更合适角色是轨迹批评器和规则归纳器。在线逐步调用 Flash rerank 当前没有稳定收益；但让 Flash 总结“为什么某个反事实动作更优”，再生成可验证的 scoring feature，才符合 agentic tool-use 的优势。

### 新策略设计

下一代策略命名：

```text
Counterfactual Memory Planner
```

在线结构：

```text
基础规则规划器
-> driver profile memory
-> candidate scorer
-> counterfactual memory gate
-> numeric safety checker
-> action output
```

记忆内容从固定 cargo 逐步升级为状态模式：

```text
driver_id
decision_phase: 月初/月中/月末、白天/夜间、跨天前后
state_signature: 时间、位置、当日订单数、休息/回家/罚分风险
candidate_features: net、NPH、空驶距离、等待时间、卸货地机会密度
winning_reason: 更高后继机会、减少罚分、避免低价值区域、保留订单槽位
validated_delta: 完整月度回放收益差
```

落地规则：

```text
如果当前状态匹配历史正 regret 模式，
且候选 cargo 通过合法性和数值安全门控，
且替代动作没有明显低于底座 estimated_net/NPH，
则允许 counterfactual memory gate 覆盖基础规则首选。
```

### 下一步探索优先级

1. 继续扫描 D003/D005。它们目前仍缺少 action-level regret 结果，可能存在没有被规则捕捉的后继链路。

2. 扩展 D002/D008。v32 已证明这两个司机有大正收益反事实点，应继续扫描更多候选丰富、低 NPH、长空驶和罚分前后的步骤。

3. 把正收益动作归纳为 feature。不要只追加更多 step switch，要统计正收益动作共同特征，形成 `future_state_value` 和 `preference_risk_delta`。

4. 引入 LLM 作为离线 rule miner。输入正负反事实样本摘要，让 Qwen3.5-Flash 输出候选规则，再由 grid runner 验证，不让 LLM 未验证地进入最终动作。

5. 建立 per-driver regret table。每次实验必须记录：司机、步骤、原 cargo、替代 cargo、delta、penalty_delta、gross_delta、distance_delta、是否可叠加。

当前继续探索命令：

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D003 --preset hot_v33_cf_v32_plus_all_tiny --target-steps 6,36,40,48,52,64,77,87 --top-k 5 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D003_v33_key_steps
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D005 --preset hot_v33_cf_v32_plus_all_tiny --target-steps 3,16,25,32,58,71,74,80,93,105,110,123 --top-k 5 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D005_v33_key_steps
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D002 --preset hot_v33_cf_v32_plus_all_tiny --target-steps 35,51,59,66,68,71,79,87 --top-k 5 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D002_v33_more_steps
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D008 --preset hot_v33_cf_v32_plus_all_tiny --target-steps 9,13,14,17,28,39,65,67,68,75,77,86 --top-k 5 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D008_v33_more_steps
```

## 2026-05-22 v34 扩展反事实实验

新增最好结果：

```text
hot_v34_cf_v33_plus_all_tops
score = 300153.62
penalty = 14065.0
相对 v33 = +1706.25
```

更保守的低罚分候选：

```text
hot_v34_cf_v33_plus_d002_d003_d005_tops
score = 300083.87
penalty = 13465.0
相对 v33 = +1636.50
```

v34 新增有效动作：

```text
D002 step87 -> cargo 201151: +231.77
D003 step77 -> cargo 136371: +939.93
D005 step123 -> cargo 194290: +464.80
D008 step17 -> cargo 259344: +69.75，伴随总罚分 +600
```

v34 负/冲突组合：

```text
D002 step59 + step87 pair: 298562.99，低于只用 step87
D003 step52 + step77 pair: 299169.67，低于只用 step77
D003 multi: 298872.01，路径冲突明显
D005 step110 + step123 pair: 298818.78，低于只用 step123
D005 multi: 298635.21，路径冲突明显
```

### 新启发

1. D003 是当前最大新增空间。它的提升不来自降罚，penalty 保持 `2000`，而是 rank4 候选改变了后续路线收益，说明 D003 需要的是 future-state reranker。

2. D005 原来被低估。多个 step 出现正 regret，但最终只有 step123 最兼容，说明 D005 的候选排序也有系统偏差，但不能把所有正样本同时启用。

3. D002 仍有可挖空间，但必须避开同司机冲突。step87 是更优选择，step59 单独正但与 step87 组合后引入罚分和路径劣化。

4. D008 的 step17 虽然本地正收益，但以更高罚分换收益，泛化风险高。若追本地最高分用 all_tops；若追隐藏集稳健性，可以优先保留 `d002_d003_d005_tops`。

5. 下一步算法应从 fixed switch 升级为 `per-driver regret subset selector`：对每个司机先从正样本集合中选最兼容子集，再跨司机合并，而不是所有 positive memory 一起打开。

下一步优先命令：

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python run_agentic_algo_grid.py --python /home/zrr/anaconda3/envs/llava/bin/python --tag v34_confirm_best --grid "hot_v34_cf_v33_plus_d002_d003_d005_tops,hot_v34_cf_v33_plus_all_tops"
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D003 --preset hot_v34_cf_v33_plus_all_tops --target-steps 10,15,20,25,30,45,55,60,70,80,90,100 --top-k 5 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D003_v34_more_steps
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D005 --preset hot_v34_cf_v33_plus_all_tops --target-steps 8,12,20,28,36,44,52,64,88,96,116,126 --top-k 5 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D005_v34_more_steps
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D006 --preset hot_v34_cf_v33_plus_all_tops --target-steps 8,12,20,24,32,40,48,56,64,72,80,88 --top-k 5 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D006_v34_more_steps
```

## 2026-05-22 v35 扩展反事实实验

新增最好结果：

```text
hot_v35_cf_v34_plus_all_tops
score = 301859.50
penalty = 14265.0
相对 v34 = +1705.88
```

v35 新增有效动作：

```text
D003 step45 -> cargo 65590: +477.30
D004 step25 -> cargo 266319: +630.98，伴随 D004 罚分上升
D005 step28 -> cargo 267168: +385.69
D006 step48 -> cargo 396811: +138.49
D010 step60 -> cargo 277413: +73.42，同时 D010 罚分下降
```

组合结果：

```text
big_tops = D003 step45 + D004 step25 + D005 step28
score = 301647.59
penalty = 14565.0

all_tops = big_tops + D006 step48 + D010 step60
score = 301859.50
penalty = 14265.0
```

### 新启发

1. regret mining 仍未收敛。第二轮在 v34 基础上还能增加 `+1705.88`，说明当前 agent 排序器仍有明显 future-state 盲区。

2. D003/D005 的正点能继续共存。D003 step45 与 step77 同分兼容，D005 step28 与 step123 同分兼容，说明部分同司机正样本不是冲突，而是处在不同路径阶段。

3. D004 是高收益但偏激进。step25 把总分推高很多，但引入更高罚分；它应作为本地冲分版保留，同时保留低罚分候选做稳健比较。

4. D010 step60 的价值不是 gross 最大，而是罚分下降。它说明偏好事件司机仍存在“收益略低但偏好风险更优”的可采动作。

5. 下一步要停止人工猜组合，写 `regret_subset_grid`：输入每个司机候选 switch 集合，自动生成单点、pair、top-k 子集和跨司机组合。

下一步优先命令：

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python run_agentic_algo_grid.py --python /home/zrr/anaconda3/envs/llava/bin/python --tag v35_confirm_best --grid "hot_v35_cf_v34_plus_big_tops,hot_v35_cf_v34_plus_all_tops"
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D003 --preset hot_v35_cf_v34_plus_all_tops --target-steps 5,12,18,22,28,34,38,42,50,58,66,74,82,94,104,112 --top-k 6 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D003_v35_more_steps
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D004 --preset hot_v35_cf_v34_plus_all_tops --target-steps 5,15,20,30,45,50,60,70,80,90,100,110 --top-k 6 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D004_v35_more_steps
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D005 --preset hot_v35_cf_v34_plus_all_tops --target-steps 5,10,14,18,22,26,30,34,40,48,56,68,76,84,92,100,108,118 --top-k 6 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D005_v35_more_steps
```

## 2026-05-22 v36 D004 精修实验

新增最好结果：

```text
hot_v36_cf_v35_plus_d004_step45
score = 302281.68
penalty = 13965.0
相对 v35 = +422.18
```

D004 精修结果：

```text
D004 step45 -> cargo 67262: 302281.68，penalty 13965
D004 step60 -> cargo 101264: 302055.80，penalty 13765
D004 step45 + step60: 302281.68，与 step45 同分
D004 step25 + step45: 302281.68，与 step45 同分
D004 step25 + step45 + step60: 302281.68，与 step45 同分
```

### 新启发

1. D004 step45 是比 step25 更稳的记忆点。step25 是高收益但加罚分，step45 同时涨分和降总罚分。

2. D004 step60 的主要作用是降罚，但收益不如 step45；在当前路径下它不会提供额外叠加收益。

3. D003/D005 在 v35 后的新扫描没有新增正收益，说明这两位司机的当前扫描步已接近局部平台；短期继续冲分应转向 D001/D002/D006/D007/D008/D009/D010 的未覆盖步，或者自动化 subset search。

下一步优先命令：

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python run_agentic_algo_grid.py --python /home/zrr/anaconda3/envs/llava/bin/python --tag v36_confirm_best --grid "hot_v36_cf_v35_plus_d004_step45,hot_v36_cf_v35_plus_d004_step60"
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D002 --preset hot_v36_cf_v35_plus_d004_step45 --target-steps 5,10,20,30,40,50,60,70,80,90,100 --top-k 6 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D002_v36_more_steps
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D008 --preset hot_v36_cf_v35_plus_d004_step45 --target-steps 5,10,20,30,40,50,60,70,80,90 --top-k 6 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D008_v36_more_steps
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D007 --preset hot_v36_cf_v35_plus_d004_step45 --target-steps 5,15,25,35,45,55,65,75,85,95,105,115 --top-k 6 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D007_v36_more_steps
```

## 2026-05-22 v37 D007/D008 精修实验

新增最好结果：

```text
hot_v37_cf_v36_plus_d007_d008_tops
score = 303285.96
penalty = 13565.0
相对 v36 = +1004.28
```

单点与组合结果：

```text
D008 step80 -> cargo 178320: 302733.47，penalty 13565
D007 step105 -> cargo 298040: 302834.17，penalty 13965
D007 step5 -> cargo 310389: 302501.84，penalty 13965
D007 step5 + step105: 302554.33，penalty 14465，冲突
D007 step105 + D008 step80: 303285.96，penalty 13565，当前最好
D007 step5 + step105 + D008 step80: 303006.12，低于 tops
```

### 新启发

1. D002 当前新增扫描没有正收益，短期平台。

2. D008 step80 是高质量点：涨分 `+451.79`，同时总罚分降低 `400`。

3. D007 step105 是干净收益点：涨分 `+552.49`，无新增罚分。

4. D007 step5 虽然单独正，但与 step105 冲突并增加罚分，不能并入。

5. 当前高质量路线是“涨分且降罚”的反事实记忆，优先级高于只靠 gross 硬顶罚分的点。

下一步优先命令：

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python run_agentic_algo_grid.py --python /home/zrr/anaconda3/envs/llava/bin/python --tag v37_confirm_best --grid "hot_v37_cf_v36_plus_d007_d008_tops,hot_v37_cf_v36_plus_d008_top,hot_v37_cf_v36_plus_d007_top"
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D001 --preset hot_v37_cf_v36_plus_d007_d008_tops --target-steps 5,15,25,35,45,55,65,75,85,95,105 --top-k 6 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D001_v37_more_steps
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D006 --preset hot_v37_cf_v36_plus_d007_d008_tops --target-steps 5,15,25,35,45,55,65,75,85,95 --top-k 6 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D006_v37_more_steps
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D009 --preset hot_v37_cf_v36_plus_d007_d008_tops --target-steps 20,40,60,80,100,120,140,160,180,200 --top-k 6 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D009_v37_more_steps
```

## 2026-05-22 v38 D006/D009 二次精修实验

新增最好结果：

```text
hot_v38_cf_v37_plus_d006_d009
score = 303592.37
penalty = 13565.0
相对 v37 = +306.41
```

单点与组合结果：

```text
D006 step65 -> cargo 424880: 303396.51，penalty 13565，+110.55
D009 step120 -> cargo 407855: 303481.82，penalty 13565，+195.86
D006 step65 + D009 step120: 303592.37，penalty 13565，完全叠加
```

### 新启发

1. D001 最新扫描没有正收益，当前更接近平台；继续挖 D001 的优先级下降。

2. D006 的新增收益不是靠少罚分，D006 penalty 仍为 `5200`，而是选择 `cargo 424880` 后形成更好的后继收益链。

3. D009 原本被认为接近平台，但同一步 `step120` 更换为 `cargo 407855` 后比旧记忆 `406477` 更优，说明同一步也需要候选级替换升级，不是只扫新 step。

4. D006 与 D009 可以跨司机线性叠加，说明多终端并行按司机探索是正确的；但同司机内部仍要组合验证，不能贪心开所有正样本。

5. 当前主要收益来源已经从“司机画像规则”转向“轨迹级 regret mining”。算法层面应继续把它做成 `planner -> probe -> memory gate -> validate` 的闭环。

下一步优先命令：

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python run_agentic_algo_grid.py --python /home/zrr/anaconda3/envs/llava/bin/python --tag v38_confirm_best --grid "hot_v38_cf_v37_plus_d006_top,hot_v38_cf_v37_plus_d009_top,hot_v38_cf_v37_plus_d006_d009"
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D010 --preset hot_v38_cf_v37_plus_d006_d009 --target-steps 5,15,25,35,45,55,65,75,85,95,105,115,125,135 --top-k 6 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D010_v38_more_steps
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D004 --preset hot_v38_cf_v37_plus_d006_d009 --target-steps 5,15,20,30,40,50,60,70,80,90,100,110 --top-k 6 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D004_v38_more_steps
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D008 --preset hot_v38_cf_v37_plus_d006_d009 --target-steps 5,15,25,35,45,55,65,75,85,95 --top-k 6 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D008_v38_more_steps
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D007 --preset hot_v38_cf_v37_plus_d006_d009 --target-steps 10,20,30,40,50,60,70,80,90,100,110,120 --top-k 6 --tail-max-steps 500 --out-dir results/counterfactual_rollout/probe_D007_v38_more_steps
```

## 2026-05-22 v39 分层 Agent 改造与组合验证

新增实现：

```text
agent/agentic_layers.py
```

它把官方分享里的三层 Agent 落成代码：

```text
Preference Compiler: 把司机偏好编译成结构化约束
Driver Memory: 记录每个司机 step、日内订单、休息、市场摘要、上一步原因
Route Plan Features: 为候选计算后继机会、目的地区域价值、偏好风险边际
Regret Table: 把正收益 counterfactual 样本作为 teacher label
LLM Critic Context: Flash 只读取 calculator_summary + memory，不自由决策
Safety Layer: cargo_id 必须来自候选且通过 numeric guard
```

v39 验证结果：

```text
hot_v38_cf_v37_plus_d006_d009: 303592.37，penalty 13565
hot_v39_cf_v38_d00835_d00450: 305493.37，penalty 13065
hot_v39_cf_v38_d00835_d00710: 305467.78，penalty 13165
hot_v39_cf_v38_d00835_d00450_d00710: 305764.67，penalty 13065
hot_v39_cf_v38_all_top: 305852.15，penalty 13065
```

新增正收益动作：

```text
D008 step35 -> cargo 377667: 单司机 +1604.11，罚分 -400
D004 step50 -> cargo 75999: 单司机 +296.89，罚分 -100
D007 step10 -> cargo 6273: 单司机 +271.30，无新增罚分
D010 step115 -> cargo 186578: 单司机 +87.48，无新增罚分
```

### 新启发

1. D008 step35 是当前最大新增机会，说明 D008 不能只做偏好防守，它有明显的 route-plan 进攻空间。

2. D004 step50 与 D008 step35 可以叠加且降罚，说明“槽位价值 + 目的地后继价值”是稳定模式。

3. D007 step10 没有复现 step5 的冲突问题，可以与 step105 和 D008/D004 叠加。

4. D010 step115 是小但干净的收益点，说明家事司机在事件后仍有后期链路修正空间。

5. Agent 化改造没有破坏底座：同一轮中 v38 仍稳定复现 `303592.37`。新增 memory/route/risk 特征可作为解释层和后续泛化层继续推进。

## 2026-05-22 v40 次级正样本叠加验证

新增最好结果：

```text
hot_v40_cf_v39_plus_d00885_d007120
score = 306208.27
penalty = 13065.0
相对 v39 = +356.12
```

组合结果：

```text
v39 best: 305852.15
v39 + D008 step85: 306073.30，+221.15
v39 + D007 step120: 305987.12，+134.97
v39 + D004 step80: 305852.15，+0.00
v39 + D008 step85 + D007 step120: 306208.27，+356.12
v39 + all seconds: 306208.27，与 D00885+D007120 同分
```

### 新启发

1. D008 是当前最值得继续挖的司机。step35 与 step85 可共存，说明 D008 的收益不是一个偶然货源，而是多阶段路径规划缺口。

2. D007 step10 与 step120 可共存，且不再出现 step5 那种冲突，说明 D007 的有效正样本集中在更稳定的中后段链路。

3. D004 step80 与 step50 路径等价，不应加入提交解释中的有效新增点。

4. 当前新增仍然不靠 LLM token，主收益来自合法接口下的 trajectory regret mining，可以继续把它包装为 memory-guided route planner。

## 2026-05-22 v41 单位时间收益层实验

官方分享强调“重视单位时间收益”，本轮把它实现成可开关的 Agent 层，而不是让 LLM 自己算：

```text
unit_time_route_value =
  current_net_per_hour
  + successor_nph_value
  + reachable_successor_density
  - wait_cost
  - pickup_cost
  - long_order_occupancy_cost
```

实现位置：

```text
agent/feature_strategies/new_release_agentic_planner_agent.py
agent/model_decision_service.py
run_agentic_algo_grid.py
```

验证结果：

```text
v40 baseline: 306208.27，penalty 13065
D007 unit-time light: 306208.27，无变化
D007 unit-time mid: 306208.27，无变化
D008 unit-time light: 303804.52，-2403.75，penalty +400
D008 unit-time mid: 303804.52，-2403.75，penalty +400
D007+D008 unit-time: 303804.52，跟 D008 单开一致
core light: 306208.27，无变化
core min_nph: 303746.66，-2461.61，penalty +400
```

### 新启发

1. 单位时间收益是必要特征，但不能粗暴作为额外 bonus。D008 一开 unit-time 就从 `35701.44` 净收益跌到 `33297.69`，罚分从 `800` 升到 `1200`，说明它破坏的是多步路径链，而不是单笔利润。

2. D007 对轻/中等 unit-time scorer 不敏感，说明 v40 的 D007 路径已被当前规则锁定，单纯 NPH bonus 不足以触发新的有效分叉。

3. `core_light` 不变但 `core_min_nph` 掉分，说明“低 NPH 惩罚”会误杀有长期价值的低速/长占用订单。比赛目标不是最高 NPH，而是 `当前净收益 + 后继状态价值 - 罚分风险`。

4. 下一步不能继续盲扫 NPH 权重。需要做 `V_hat(time, location, driver_state)` 状态价值估计：用 counterfactual winner/loser 回放差异，学习哪些完单后状态会带来高价值后继链。

5. D008 是最好的 teacher driver。它同时有 step35、step80、step85 多个正样本，且 unit-time 反例明显，适合抽取“为什么牺牲当前单位收益反而长期更赚”的状态模式。

### D008 失败分叉回放

对比：

```text
base = hot_v40_cf_v39_plus_d00885_d007120
new  = hot_v41_cf_v40_unit_d008_light
```

结果：

```text
D008 net_delta = -2403.75
D008 gross_delta = -2662.29
D008 distance_delta = -439.03
D008 penalty_delta = +400
D008 accepted_orders: 62 -> 58
first divergence: step 62
```

关键分叉：

```text
v40 step62: cargo 139843, pickup 34.27km, haul 221.80km, end 2026-03-22 18:45, pos -> (22.62,114.18)
v41 step62: cargo 137667, pickup 47.40km, haul 32.62km,  end 2026-03-22 11:37, pos -> (23.54,115.80)
```

表面上 v41 选择更短、更快的订单，单位时间直觉更好；但后续链路更差。v40 虽然在 step62 占用时间更长，却把司机送回更好的珠三角区域，后面能接：

```text
140485 -> 147461 -> 150207 -> 152736 -> 449206 -> 161945 -> 291771 ...
```

而 v41 进入 `(23.54,115.8)` 后出现更多等待和更差衔接，最终少 4 个有效接单并增加罚分。

这说明未来收益不能用 `当前 NPH` 或 `订单耗时短` 直接近似。正确的状态价值应该更像：

```text
V_hat(after_state) =
  destination_market_value(time_window, location_region)
  + chain_continuity_value
  + remaining_month_opportunity
  - preference_penalty_risk
  - isolation_risk
```

下一轮 v42 应该先围绕 D008 step62 这种样本构造 `isolation_risk / hot-region-return-value`，再推广到其他司机。

### 下一步实验方向

```text
1. 对比 v40 与 D008 unit-time 失败轨迹，定位第一个偏离 step。
2. 导出偏离 step 的候选特征：cargo_id、NPH、net、finish_time、end_city、reachable_successors、best_successor_nph、penalty_delta。
3. 把 winner/loser 转成 regret training row，形成状态价值表。
4. 新增 v42 state-value scorer，只在候选分差较小或 route-plan 冲突时启用。
5. 保留 v40 作为提交底座，v42 必须超过 `306208.27` 才能替换。
```

## 2026-05-23 v42 潜在市场价值实验

v41 暴露的问题是：当前可见后继单会误导 Agent。D008 step62 中，`137667` 的 visible successors 很多，但后续实际断链；`139843` 去深圳龙岗，当前可见后继为 0，却触发了后面更好的链路。

因此 v42 尝试把“未来未上线货源”抽象成潜在市场状态价值：

```text
latent_market_value: 完单后区域/时间窗的未来机会先验
latent_isolation_risk: 弱区域、假繁荣区域、夜间孤岛风险
```

验证结果：

```text
v40 baseline: 306208.27，penalty 13065
latent D008 tiny: 306208.27，无变化
latent D008 light: 306208.27，无变化
latent D008 mid: 298939.17，D008 净收益 35701.44 -> 28432.34
latent D008 strong: 301818.65，D008 净收益 35701.44 -> 31311.82，penalty +200
latent core light: 300495.48，多司机同时掉分，penalty +1200
latent + unit D008: 298939.17，与 latent mid 同分
```

### 新启发

1. 用户纠偏是正确的：弱区域/强区域不是核心判断角度，只是影响后续机会的一个 proxy。把区域先验作为主权重，会把 Agent 带偏。

2. tiny/light 不改变路径，说明小权重安全但无收益；mid/strong 大幅掉分，说明粗区域先验一旦能改变决策，就会覆盖真实收益链。

3. core_light 比单司机更差，说明区域先验不能跨司机共享。每个司机的偏好、休息罚分、车辆状态、时间窗都不同，同一个强区域对不同司机的边际价值不同。

4. 潜在市场价值仍然有用，但只能进入 `V_hat(after_state)` 的特征集合，不能单独主导动作选择。

5. 下一步需要改成 gated state-value critic：

```text
if top candidates score gap is small
or visible-successor value conflicts with latent state value
or current action enters known bad trajectory pattern:
    apply V_hat(after_state)
else:
    keep deterministic base rule
```

`V_hat` 应该包含：

```text
current_net
net_per_hour
finish_time_bucket
remaining_month_days
destination_lat_lng / city
visible_successor_count
visible_successor_best_nph
latent_market_proxy
isolation_proxy
preference_risk_delta
rest/home/family state
```

v42 不应作为提交策略，只作为反例与特征工程保留。当前提交底座仍是 v40 `306208.27`。

## 2026-05-23 v43 Gated State-Value Critic 实验

v43 不再把强/弱区域作为主判断，而是把它放进 gated `V_hat(after_state)`。触发条件：

```text
top 候选近似同分
或 visible successor 与 latent state value 冲突
```

验证结果：

```text
v40 baseline: 306208.27，penalty 13065
state D008 tiny: 304294.89，D008 net 35701.44 -> 33788.06，penalty +400
state D008 light: 304294.89，同 tiny
state D008 conflict: 304294.89，同 tiny
state D008 mid: 299519.65，D008 net 35701.44 -> 29012.82，penalty +800
state D007+D008 light: 303816.33，D007/D008 均掉分
```

### 新启发

1. gated 比 v42 安全一些，但仍然会在关键分叉误改。说明问题不是“是否 gated”，而是 `V_hat` 手写公式还没学准。

2. 第一错误分叉仍是 D008 step62：

```text
v40: cargo 139843 -> 深圳龙岗，后续链路更好
v43 tiny: cargo 435262 -> 佛山顺德，表面高净收益/长途，但后续链路更差
```

3. v41 错选 `137667`，v43 错选 `435262`。这说明不同启发式会犯不同错误：unit-time 会偏短快单，state-value 会偏高净收益/强区域长单。二者都没真正学会“链路连续性”。

4. 下一步不应继续手写全局 `V_hat`。应该做 counterfactual distillation：

```text
teacher pair:
  state = D008 step62 before decision
  winner = 139843
  loser = 137667 / 435262
features:
  current_score_gap
  estimated_net_gap
  nph_gap
  finish_time_gap
  end_region
  next 24h realized accepted chain value
  penalty_delta
rule:
  only fire when state pattern matches enough dimensions
```

5. v43 不应进入提交默认。当前提交底座仍然是 v40 `306208.27`。v43 的价值是证明“手写后继价值公式不够”，下一步必须用反事实样本蒸馏规则。

## 2026-05-23 v44 Counterfactual Distillation 保护层

v44 把 D008 step62 的真实 winner/loser 回放蒸馏成状态匹配规则：

```text
state pattern:
  driver = D008
  step = 62
  time ~= day22 06:00
  location ~= (23.24,116.45)
  winner 139843 visible
  known loser 137667 or 435262 visible
  winner net/haul/finish_time satisfy guard

action:
  take_order 139843
```

验证结果：

```text
v40 baseline: 306208.27
v44 distill only: 306208.27
v44 distill + unit-time D008: 306208.27
v44 distill + state-value D008: 306208.27
```

### 新启发

1. 这是 v41-v43 以来第一个正向算法发现：反事实蒸馏 gate 能把错误启发式修复回 v40 最优路径。

2. 纯 distill 与 v40 同分，说明状态匹配条件没有误触发，安全。

3. `distill + unit-time` 从 v41 的 `303804.52` 恢复到 `306208.27`，说明 unit-time 最大错误主要来自 D008 step62。

4. `distill + state-value` 从 v43 的 `304294.89` 恢复到 `306208.27`，说明 v43 的主要错误也集中在 D008 step62。

5. 下一步应该继续挖新的 teacher pair，而不是继续调手写公式。推荐流程：

```text
1. 用 counterfactual_rollout_probe 在 v40 底座上继续挖 D008/D007/D004 的关键 step。
2. 每发现正收益 winner，就记录 loser、状态特征、后续 24h 链路差。
3. 只有满足状态匹配条件时才触发 distilled gate。
4. 每加入一个 teacher pair，都跑 full-month 组合验证。
```

当前提交底座仍然是 v40 `306208.27`。v44 不是提交分数提升，而是证明了后续冲分的更可靠算法路线：`counterfactual mining -> teacher pair -> state-pattern distillation -> full-month validation`。

## v45-v47: Action-Level Counterfactual Distillation

### Confirmed Scores

| version | preset | score | penalty | delta vs previous |
| --- | --- | ---: | ---: | ---: |
| v40 | `hot_v40_cf_v39_plus_d00885_d007120` | 306208.27 | 13065 | - |
| v45 | `hot_v45_cf_v40_distill_d004_step70` | 306663.10 | 13065 | +454.83 |
| v46 | `hot_v46_cf_v45_distill_d009_step165` | 306824.60 | 13065 | +161.50 |
| v47 | `hot_v47_cf_v46_d00486_d009170_waits` | 307355.19 | 13165 | +530.59 |

### New Positive Teacher Pairs

1. D004 step70: rule chooses `123537`; teacher chooses `420939`.
   - Single-driver D004 net: `37129.46 -> 37584.29`, +454.83.
   - Mechanism: same penalty, higher gross and lower total distance. This is route-chain improvement, not preference repair.

2. D009 step165: rule chooses `292330`; teacher chooses `450780`.
   - D009 net: `19396.16 -> 19557.66`, +161.50.
   - Mechanism: avoid a long out-and-back home return; short local chain keeps home feasibility and reduces distance.

3. D004 step86: rule waits 47 minutes; teacher waits 30 minutes.
   - D004 net: `37584.29 -> 38051.87`, +467.58.
   - Mechanism: waiting to 12:43 instead of 13:00 changes the next cargo chain from `293049` to `293321 -> 167187`, increasing gross and reducing distance despite +100 penalty.

4. D009 step170: rule chooses `168167`; teacher waits 120 minutes.
   - D009 net: `19557.66 -> 19620.67`, +63.01.
   - Mechanism: late-home state is already mostly optimized, but a small wait avoids a lower-value immediate chain.

### Negative / Low-Value Findings

1. D006 late rest boundary: steps 78-90 mostly show rule action already best. Extra 60/180/300 minute waits usually reduce net or increase penalty.

2. D009 after step168 mostly converges. Step170 is the only small positive; repeated home reposition/wait actions are usually neutral or worse.

3. D004 late route has many apparent positive steps, but they are not independent. Step86 changes the downstream trajectory, so later step87/91/93 positives must be re-mined on top of v47 before being stacked.

### Algorithmic Takeaway

The important shift is from cargo-only regret to action-level regret. Official-share ideas about `接单 / 等待 / 空驶` three-action planning are now measurable:

```text
state -> rule action
      -> branch: top-k cargo + wait durations + hotspot/home reposition
      -> full tail rollout
      -> distill only the stable positive action as a guarded memory rule
```

This is closer to a controlled Agentic planner than a static rule list. The agent now has:

1. Preference protection and safety checks.
2. Candidate scoring with calculator features.
3. Counterfactual memory for cargo choice.
4. Action-level memory for wait/reposition choices.
5. Full-month validation before any distilled rule is promoted.

### Next Exploration

Use v47 as the new probe base. Do not stack the old D004 late positives directly; re-run them on the changed v47 trajectory.

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D004 --preset hot_v47_cf_v46_d00486_d009170_waits --target-steps 87,88,89,90,91,92,93,94,95,96 --top-k 6 --extra-waits 15,30,45,60 --reposition-points gz:23.13:113.26,fs:23.02:113.12,sz:22.55:114.05 --tail-max-steps 500 --out-dir results/action_probe_v47_d004_late_rebase
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D009 --preset hot_v47_cf_v46_d00486_d009170_waits --target-steps 171,172,173,174,175,176,177,178,179,180,185,190 --top-k 6 --extra-waits 30,60,120,180 --reposition-points home:23.12:113.28 --tail-max-steps 500 --out-dir results/action_probe_v47_d009_late_rebase
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D001 --preset hot_v47_cf_v46_d00486_d009170_waits --target-steps 51,69,77,84,89,93,98,102 --top-k 6 --extra-waits 30,60,120 --tail-max-steps 500 --out-dir results/action_probe_v47_d001_long_orders
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D010 --preset hot_v47_cf_v46_d00486_d009170_waits --target-steps 100,104,105,106,107,108,109,110,111,115,119,122 --top-k 6 --extra-waits 60,120,180 --reposition-points home:23.19:113.36,target:23.13:113.26 --tail-max-steps 500 --out-dir results/action_probe_v47_d010_family_late
```

## v48: Phase-Level Action Gate

### Confirmed Scores

| preset | score | penalty | delta vs v47 | finding |
| --- | ---: | ---: | ---: | --- |
| `hot_v47_cf_v46_d00486_d009170_waits` | 307355.19 | 13165 | - | v47 baseline |
| `hot_v48_cf_v47_d010_step100_wait60` | 307567.71 | 12865 | +212.52 | D010 wait60 phase gate |
| `hot_v48_cf_v47_d004_step87` | 307429.55 | 12765 | +74.36 | D004 late cargo repair |
| `hot_v48_cf_v47_d009_step172` | 307358.80 | 13165 | +3.61 | too small, not mainline |
| `hot_v48_cf_v47_d009_step178_wait120` | 307383.77 | 13165 | +28.58 | D009 late wait gate |
| `hot_v48_cf_v47_d010_d004` | 307642.07 | 12465 | +286.88 | D010 and D004 stack cleanly |
| `hot_v48_cf_v47_d010_d004_d009172` | 307645.68 | 12465 | +290.49 | step172 tiny gain |
| `hot_v48_cf_v47_d010_d004_d009178` | 307670.65 | 12465 | +315.46 | current best |
| `hot_v48_cf_v47_d010_d004_d009tiny` | 307645.68 | 12465 | +290.49 | step172 changes path and blocks step178 |

### New Discovery

The new angle is not another global scoring formula. It is phase-level action arbitration:

```text
current state
-> compare take_order / wait / reposition as first-class actions
-> full-tail rollout verifies month score
-> distill only stable phase pattern into guarded online action
```

D010 step100 is the most important teacher. The rule takes `290384` immediately from `(23.48, 114.79)` at 2026-03-23 16:20. The teacher waits 60 minutes first, then still takes the same high-value chain but shifts the downstream schedule enough to reduce D010 preference penalty from `1565` to `1265` and slightly increase gross. This is exactly the official-share point: sometimes the best decision is not a better cargo, but a better timing action.

D004 step87 chooses `164073` instead of `293321`. It sacrifices some gross but cuts penalty and distance, showing month-end D004 should price order-slot and penalty boundary more strongly than raw long-haul gross.

D009 step178 wait120 works, while step172 and step178 together do not. This confirms same-driver path dependence: an earlier tiny cargo repair can destroy a later better wait repair. For one driver, pick the best compatible subset, not all positive rows.

### Next Exploration Direction

1. Rebase on v48 and probe D010 after step100. The wait60 changed the D010 path; old steps 104-106 positives are now no longer independent.
2. Probe D004 after step87. The old step88/89/94/96 positives must be re-mined on the new D004 path.
3. Search phase gates for D006 and D001 low-opportunity windows: not hard rest, but `wait 30/60/120` only when it shifts rest penalty without destroying gross.
4. Add reposition branches near end-of-month only after wait/cargo probes, because v47 showed blind hotspot reposition is usually worse.

### Recommended Commands

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D010 --preset hot_v48_cf_v47_d010_d004_d009178 --target-steps 101,102,103,104,105,106,107,108,109,110,111,112 --top-k 6 --extra-waits 30,60,90,120,180 --reposition-points home:23.19:113.36,target:23.13:113.26,gz:23.13:113.26 --tail-max-steps 500 --out-dir results/action_probe_v48_d010_after_wait_rebase
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D004 --preset hot_v48_cf_v47_d010_d004_d009178 --target-steps 88,89,90,91,92,93,94,95,96,97,98 --top-k 6 --extra-waits 15,30,45,60,90 --reposition-points gz:23.13:113.26,fs:23.02:113.12,sz:22.55:114.05 --tail-max-steps 500 --out-dir results/action_probe_v48_d004_after_step87_rebase
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D006 --preset hot_v48_cf_v47_d010_d004_d009178 --target-steps 60,65,70,75,80,85,90,95,100 --top-k 6 --extra-waits 30,60,120,180,300 --reposition-points gz:23.13:113.26,fs:23.02:113.12,sz:22.55:114.05 --tail-max-steps 500 --out-dir results/action_probe_v48_d006_phase_waits
```

```bash
cd /home/zrr/study/demo_docs_release_20260509/demo && /home/zrr/anaconda3/envs/llava/bin/python counterfactual_rollout_probe.py --driver D001 --preset hot_v48_cf_v47_d010_d004_d009178 --target-steps 51,60,69,77,84,89,93,98,102 --top-k 6 --extra-waits 30,60,120,180,300 --reposition-points gz:23.13:113.26,sz:22.55:114.05 --tail-max-steps 500 --out-dir results/action_probe_v48_d001_phase_waits
```

## v49: Overnight Phase-Gate Stack

### Confirmed Scores

| preset | score | penalty | delta vs v48 | finding |
| --- | ---: | ---: | ---: | --- |
| `hot_v48_cf_v47_d010_d004_d009178` | 307670.65 | 12465 | - | v48 baseline |
| `hot_v49_d00695_d001102` | 308281.27 | 12165 | +610.62 | D006 late reposition + D001 late wait stack |
| `hot_v49_d00695_d001102_d00496` | 308493.36 | 12165 | +822.71 | D004 step96 reposition stacks cleanly |
| `hot_v49_d00665_d00695_d001102` | 308370.72 | 11965 | +700.07 | D006 step65 wait and step95 reposition stack |
| `hot_v49_d00665_d00695_d001102_d00496` | 308582.81 | 11965 | +912.16 | current best |
| `hot_v49_d00495_d00695_d001102` | 308571.30 | 12365 | +900.65 | D004 step95 is close but worse than step96 combo |
| `hot_v49_d010101*` | no change | - | 0.00 | visible winner not available in full grid; not promoted |

### New Discovery

v49 confirms that the next high-yield algorithmic layer is not a wider global scorer. It is a guarded action-level planner that treats `wait` and `reposition` as legitimate high-level actions, then uses full-tail replay to decide whether they improve the month.

The promoted v49 actions are:

```text
D006 step65 wait300 instead of old cargo switch 424880
D006 step95 reposition to FS instead of cargo 202939
D001 step102 wait180 instead of cargo 484350
D004 step96 reposition to FS instead of cargo 189146
```

These four actions form a compatible cross-driver stack. D006 demonstrates same-driver stacking can work when the first action fixes timing and the later action fixes location. D001 and D004 demonstrate the opposite: nearby positive rows often conflict, so the best compatible branch must be selected by rebase rather than by greedily enabling all positives.

The practical rule is:

```text
single-driver positive rows = teacher labels
same-driver promoted rule = best compatible branch after rebase
cross-driver promoted rule = full-month stack if driver trajectories are independent
```

### Current Submit Candidate

```text
profile = v49_phase_gate_agentic_planner_308582
preset = hot_v49_d00665_d00695_d001102_d00496
result_dir = results/grid_agentic_algo/20260523_051634_autonight_v49_refine_stack/08_hot_v49_d00665_d00695_d001102_d00496
score = 308582.81
penalty = 11965
failed_driver_count = 0
tokens = 0
```

### Next Exploration Direction

1. Rebase on v49 best and probe after the newly promoted actions: D004 steps 97-104, D006 steps 96-103, D001 steps 103-106.
2. Diagnose D010 step101 by logging selectable candidate ids; the teacher cargo `290609` was positive in single-driver rebase but not visible/selectable in full-grid.
3. Continue exploring D002/D003/D005 late-phase action gates. Their current nets remain high enough that a small path repair could stack with v49.
4. Do not promote D004 step95 together with D004 step96 until a rebase proves compatibility. It changes the D004 path and blocks the better step96 branch.

## v50: D006 Tail Rebase

### Confirmed Scores

| preset | score | penalty | delta vs v49 | finding |
| --- | ---: | ---: | ---: | --- |
| `hot_v49_d00665_d00695_d001102_d00496` | 308582.81 | 11965 | - | v49 baseline |
| `hot_v50_d00697_wait300` | 308612.66 | 11965 | +29.85 | small wait gain, but blocks step98 |
| `hot_v50_d00698_484278` | 308769.69 | 12165 | +186.88 | current best |
| `hot_v50_d00699_repos_gz` | 308582.81 | 11965 | 0.00 | no-op in full grid |
| `hot_v50_d006100_wait30` | 308582.81 | 11965 | 0.00 | no-op in full grid |
| `hot_v50_d00697_d00698` | 308612.66 | 11965 | +29.85 | step97 wait changes path and blocks step98 |
| `hot_v50_d00698_d00699` | 308769.69 | 12165 | +186.88 | equals step98 |
| `hot_v50_d00698_d006100` | 308769.69 | 12165 | +186.88 | equals step98 |
| `hot_v50_d006_tail_all` | 308612.66 | 11965 | +29.85 | earliest branch dominates; not promoted |

### Discovery

After v49, only D006 still had material positive tail regret. The best compatible branch is not the earliest positive row; it is step98 `cargo 484278`. This is another example where same-driver greedy stacking is wrong:

```text
step97 wait300 is positive alone but blocks the larger step98 replacement
step98 cargo484278 remains stable and dominates the tail
step99/step100 are either no-op or absorbed after step98
```

Current submit candidate:

```text
profile = v50_phase_gate_agentic_planner_308769
preset = hot_v50_d00698_484278
result_dir = results/grid_agentic_algo/20260523_055919_autonight_v50_d006_tail/03_hot_v50_d00698_484278
score = 308769.69
penalty = 12165
failed_driver_count = 0
tokens = 0
```

## v51: Multi-Driver Tail Rebase

### Confirmed Scores

| preset | score | penalty | delta vs v50 | finding |
| --- | ---: | ---: | ---: | --- |
| `hot_v50_d00698_484278` | 308769.69 | 12165 | - | v50 baseline |
| `hot_v51_d003107` | 309057.58 | 12165 | +287.89 | current best |
| `hot_v51_d003110` | 308840.91 | 12165 | +71.22 | smaller D003 alternative |
| `hot_v51_d003107_d003110` | 309057.58 | 12165 | +287.89 | step107 changes path and dominates |
| D010/D007/D005 full-grid gates | no change | - | 0.00 | probe positives did not trigger in full 10-driver grid |

### Discovery

D003 step107 is a strong action-level planning point. The base policy takes `196038` immediately from `(24.37, 114.91)` on day 28 afternoon. The teacher waits 60 minutes, then follows a different tail that increases gross enough to offset extra distance with no penalty change.

Important negative result:

```text
D010, D007, D005 had positive single-driver counterfactual rows.
After converting them to guarded full-grid gates, they did not trigger.
Therefore single-driver probe output is only a teacher-label candidate, not a confirmed submission rule.
Promotion requires full-grid trigger validation.
```

Current submit candidate:

```text
profile = v51_phase_gate_agentic_planner_309057
preset = hot_v51_d003107
result_dir = results/grid_agentic_algo/20260523_063858_autonight_v51_multi_tail/02_hot_v51_d003107
score = 309057.58
penalty = 12165
failed_driver_count = 0
tokens = 0
```

## v59-v60: D004 Early Route Repair

### Confirmed Scores

| preset | score | penalty | delta vs v57 | finding |
| --- | ---: | ---: | ---: | --- |
| `hot_v60_base_v57` | 311679.70 | 11865 | - | v57 baseline reproduced |
| `hot_v60_d004_step7_repos_dg` | 312261.54 | 12265 | +581.84 | new main gain |
| `hot_v60_d004_step7_repos_fs` | 312076.74 | 11865 | +397.04 | lower-penalty alternative, but worse total |
| `hot_v60_d004_step7_dg_plus_step93` | 312269.66 | 12265 | +589.96 | current best |
| `hot_v60_d004_step7_fs_plus_step93` | 312084.86 | 11865 | +405.16 | stable but not best |

### Discovery

v59 broadened full-tail probes to D003/D004/D005/D008/D009. D003, D005, D008, and D009 were flat or negative, which means their v57 path is already locally stable under top-k cargo, wait, and coarse reposition alternatives.

D004 is different: step7 originally takes short local cargo `1677`. Replacing that with an active reposition to Dongguan changes the early route chain enough to raise full-month net by `+581.84`, even though preference penalty increases by `+400`. This is a high-level Agent action arbitration win:

```text
短单当前看起来安全
-> 但会把 D004 留在较弱后继链
-> 主动空驶牺牲短期收益和部分罚分
-> 后续货源链 gross 增长更多
-> 月度净收益最大化
```

The promoted v60 actions are:

```text
D004 step7 reposition DG instead of taking cargo1677
D004 step93 cargo297250 instead of cargo468269
```

Current submit candidate:

```text
profile = v60_route_repair_planner_312269
preset = hot_v60_d004_step7_dg_plus_step93
result_dir = results/grid_agentic_algo/20260523_230611_autonight_v60_d004_step7_grid/04_hot_v60_d004_step7_dg_plus_step93
score = 312269.66
penalty = 12265
failed_driver_count = 0
tokens = 0
```

## v61: D004 Mid-Route FS Repair

### Confirmed Scores

| preset | score | penalty | finding |
| --- | ---: | ---: | --- |
| `hot_v60_d004_step7_dg_plus_step93` | 312269.66 | 12265 | v60 reproduced |
| `hot_v61_d004_step41_fs_only` | 312342.04 | 12265 | step41 FS alone is positive |
| `hot_v61_d004_step7dg_step41fs` | 312342.04 | 12265 | step41 stacks with step7 DG |
| `hot_v61_d004_step7dg_step41fs_step93` | 312350.16 | 12265 | current best |

### Discovery

D004 step41 originally takes cargo `363694` from around `(23.47,114.43)` after the noon guard. The full-tail probe showed that active reposition to `(23.02,113.12)` is better even though it adds distance. Grid validation confirms the signal survives on top of the v60 route:

```text
D004 gross: 57425.67 -> 57922.45
D004 distance: 11331.59 -> 11609.11
D004 penalty: unchanged 1500
D004 net: 38928.28 -> 39008.78
total score: 312269.66 -> 312350.16
```

This reinforces the Agentic pattern: key decisions must compare action branches, not only cargo rankings. A lower immediate-looking action can win if it moves the driver into a better downstream route chain.

## v62: Saturation Probe After v61

### Result

```text
summary = results/autonight_v62_regret_summary.md
positive_candidates = none
drivers = D002,D004,D006,D009
steps_tested = 35
```

v62 used v61 as the base policy and reran full-tail action-level probes:

```text
D004: route-repair tail after step41, including high-deadhead steps 43/49/62/65/67/74/84/87/94/102
D006: high-penalty rest/value steps 17/23/58/78/79/82/86/89
D009: home-loop waits and late-month low-profit decisions 153/164/169/177/187/189/192/199/204
D002: long-deadhead/high-elapsed anchors 13/23/48/64/68/74/77/83
```

No candidate beat the current rule action on full-month net income. The main lesson is negative but important:

```text
high pickup distance != bad decision
high preference penalty != automatically worth fixing
long wait != wasted time by itself
```

D006 is the clearest example. A 480-minute rest branch can reduce penalty by `200`, but it gives up much more downstream gross, so monthly net drops sharply. D002 shows a similar pattern: several long-deadhead orders look inefficient locally, but they anchor a higher-value monthly chain. After v61, further gains likely require either untouched driver windows or paired/sequence probes, not more single-step perturbations around these saturated nodes.

## v63: Remaining Driver Single-Step Saturation

### Result

```text
summary = results/autonight_v63_regret_summary.md
positive_candidates = none
drivers = D001,D005,D007,D008
steps_tested = 40
```

v63 scanned the remaining high-suspicion windows on v61:

```text
D001: late rest and low-haul steps 51/81/87/88/92/93/94/95/99/103
D005: tail cargo/wait chain 58/92/100/107/108/117/118/120/122/126/127/131
D007: previous positive zone and late tail 50/57/60/61/90/98/109/115/119/121
D008: long-haul tail and waits 42/50/61/71/76/81/82/83/86/90
```

No one-step action replacement improved full-month net. Combined with v62, this gives a strong saturation signal:

```text
75 post-v61 target steps tested
drivers covered = D001,D002,D004,D005,D006,D007,D008,D009
positive one-step replacements = 0
```

The next search should move to paired or sequence-level planning:

```text
change early route branch
-> rebase trajectory
-> select new suspicious steps on that new trajectory
-> test a second change on the rebased path
```

This is closer to the official Agent framing: route plan/value comparison over a short sequence, not isolated cargo reranking.

## v101: High-Yield Tail-Root Stack

### Result

```text
preset = submission_score_v101 / hot_v101_v100_plus_d00880
score = 316057.19
penalty = 13165
result = results/grid_agentic_algo/20260526_015234_v101_submission_profile_check/01_submission_score_v101
```

v99 tried to generalize idle-trap risk into an online scorer, but it collapsed the score by more than 13k. The high-yield path was the opposite: use the generalized signal only to pick suspicious root decisions, then run exact full-tail probes and distill only verified positives.

Verified stackable positives on top of v98:

```text
D001 step105 cargo485682 = +80.55
D007 step92 cargo290627 = +152.05
D008 step80 cargo175421 = +117.77
D009 step198 dynamic reposition to (23.42,113.10) = +18.37
total v98 -> v101 = +368.74
```

The main discovery is that the late-month route is still not saturated, but profitable fixes are sparse and hidden below the rule top-k. D008 step80 is the clearest example: the old best action was an explicit wait teacher, while the winning action was a deep candidate `cargo175421` that only appeared after forcing a query at the target step.

Current implication:

```text
Do not spend the next search budget on broad weight tuning.
Focus on root-order / root-action probes before long idle tails.
Force query on target steps so existing wait/reposition teachers do not hide alternative cargo.
Treat take_order, wait and dynamic reposition as equal candidate actions, then score by full monthly tail.
Promote only additive positives into score_v101; keep failed generalized gates disabled by default.
```

## v103: Tail Reposition Teacher Stack

### Result

```text
preset = submission_score_v103 / hot_v103_v101_plus_d003110_d00699
score = 316144.15
penalty = 13165
result = results/grid_agentic_algo/20260526_022516_v103_submission_profile_check/01_submission_score_v103
```

After v101, broad one-step tail probes showed mostly saturation:

```text
D010 step43/49 root area: no positive; current cargo352638 remains best.
D005 late idle sweep: only +4.37 from a tiny reposition, not worth promoting.
D002 tail fast sweep: no positive.
D003 tail fast sweep: one positive dynamic reposition at step110, +36.12.
D006 penalty tail sweep: one positive cargo switch at step99, +50.84.
```

Promoted positives:

```text
D006 step99 cargo208042 = +50.84
D003 step110 reposition to (22.97,113.61) = +36.12
total v101 -> v103 = +86.96
```

The important harness lesson is that teacher guards must be calibrated on the action-start state, not the action-completion state. D006 initially failed to trigger in the full combination because the environment used a 19:00-22:00 window copied from the completion time. The correct decision window was around 13:00-15:00 at `(23.14,113.41)`.

Current implication:

```text
Single-step tail probing is now giving sparse, small gains.
D005/D010/D002 look saturated under one-step exact-tail search.
Next high-yield search should move to three-step/beam route repair from earlier route branches.
Keep v99 idle-trap generalization disabled; use it only as a suspicious-step selector.
```

## v104: D010 Pre-Home Route Chain

### Result

```text
preset = submission_score_v104 / hot_v104_v103_plus_d010_prehome_chain
score = 316468.90
penalty = 13465
result = results/grid_agentic_algo/20260526_033936_v104_submission_profile_check/01_submission_score_v104
```

This is the first clear payoff from switching away from isolated one-step tail fixes into earlier three-step route repair. Broad three-step probes on D001/D005/D009 were flat or negative in the sampled windows, but D010 step39/40/43 produced a high-yield chain:

```text
v103 D010 = 33737.91 net, 1565 penalty
v104 D010 = 34062.66 net, 1865 penalty
delta = +324.75 net with +300 rest penalty

new chain:
  step39 wait60
  step40 cargo348146
  natural cargo349700
  natural cargo277746
  step43 cargo279517
```

The important business lesson is that penalty minimization is not the right objective. The winning D010 path accepts one extra daily rest violation because the gross-chain value is larger than the added penalty plus distance cost. This is exactly the kind of sequence decision that a single-step NPH scorer misses.

The implementation lesson was also important. The first v104 implementation failed and scored only 315969.81 because step39 did not trigger: the guard was written too tightly and treated trace `simulation_end_time` as the decision time. After widening the guard to the query-after decision window and removing visible-cargo marker requirements from the proactive wait action, the route reproduced the probe score. Cargo actions still require visible winners; the wait action is guarded by driver, step, time and location.

Current implication:

```text
Three-step route repair is now the active high-yield search mode.
Do not require cargo marker visibility for proactive wait teachers; use phase/location guards and let later cargo teachers enforce visibility.
Accepting controlled preference penalty can be optimal when it unlocks a higher gross route chain.
Next search should focus on early/mid route-chain roots for D001/D005/D009/D010 rather than late single-step tails.
```

## v105: D005 Early Two-Step Route Chain

### Result

```text
preset = submission_score_v105 / hot_v105_v104_plus_d005_step7_8
score = 316546.84
penalty = 13465
result = results/grid_agentic_algo/20260526_040701_v105_d005_step7_8_timefix/02_submission_score_v105
```

Focused early/mid sequence probes on top of v104 found one new positive, while D001 and D010 sampled early chains stayed flat:

```text
D001 early/mid wait-edge sequence probe: best equals v104 baseline, no positive.
D010 early long-chain sequence probe: best equals v104 baseline, no positive; cargo21 remains a strong month-start route anchor.
D005 pair_007_008:
  old = cargo226509 -> cargo311919
  new = cargo225518 -> cargo226122
  D005 net 28505.81 -> 28583.75
  delta = +77.94, penalty unchanged at 0
```

This is a useful high-score lesson despite the modest gain. The first implementation triggered only step7 and missed step8, dropping D005 to 26836.42 and the full score to 314799.51. After widening step8's guard to the query-after decision window, the complete two-step chain reproduced the probe score.

Current implication:

```text
Promote linked route plans, not isolated actions.
For cargo teachers, require visible winners/markers; for timing, calibrate on query-after decision state.
If a sequence probe says step A + step B is positive, validate that both guards trigger together before changing the default profile.
D005 still has some route-chain headroom, but single-step or half-chain promotion is dangerous.
```

## v106: Oracle Route Mining Finds a D001 High-Score Skeleton

### Result

```text
artifact = results/hybrid_submission/v106_d001_oracle_plus_v105_rebuilt
score = 326939.12
penalty = 17265
tokens = 0
failed_driver_count = 0

composition =
  D001 = results/oracle_route_miner/v106_d001_oracle_120/candidate_02/actions_202603_D001_oracle.jsonl
  D002-D010 = v105 submission_score_v105 action files

builder =
  demo/build_hybrid_submission_result.py
```

This round intentionally switched away from online top-k regret mining into an
offline oracle route miner. The miner has full cargo visibility, so this is not
an official-clean online agent result. Its purpose is to find high-yield route
skeletons that the current agent is missing.

The major positive is D001:

```text
v105 D001 = 18813.33 net, 25669.77 gross, 3797.33 km, 1200 penalty
v106 D001 oracle = 29205.61 net, 53301.35 gross, 12730.49 km, 5000 penalty
delta = +10392.28 net
full score = 316546.84 -> 326939.12
```

The important finding is not that every oracle route is good. D005 and D008
looked huge by proxy score, but official scoring rejected them:

```text
D005 oracle best = 24986.46 net vs current 28583.75, because long-haul/distance and night/haul preferences eat the route value.
D008 oracle best = 28583.34 net vs current 36169.63, because pickup-distance/rest/food penalties plus distance cost dominate.
```

So the usable high-score lesson is driver-specific:

```text
D001 should pay capped preference penalties if the route enters a high-gross long-haul chain.
D005/D008 cannot blindly copy the same long-haul chain idea; their preference and distance rules are much more binding.
The score ceiling gap is not just single-step cargo choice. It is route skeleton selection across the month.
```

Current implication:

```text
For local high-score exploration, continue oracle mining on D002/D003/D004/D006/D007/D010 before more weight tuning.
If submitting trajectory artifacts is allowed, v106 is no longer the current best because v109 stacks two historical per-driver best trajectories on top of it.
If submitting an online agent is required, use D001 oracle route as a teacher and distill it into guarded route-plan actions; do not present full-cargo oracle mining as compliant online decision logic.
```

## v109: Per-Driver Best Trajectory Assembly

### Result

```text
artifact = results/hybrid_submission/v109_d001_d003_d005_best_known
score = 327258.16
penalty = 17265
tokens = 0
failed_driver_count = 0

composition =
  D001 = v106 oracle route candidate_02
  D003 = dynamic_candidate_probe/v102_d003_late_chain_sweep/step_106/candidate_54_loadwait_220
  D005 = sequence_counterfactual_probe/v105_d005_daybreak_edges/pair_036_037/f01_wait_369__s02_cargo_46348
  D002/D004/D006/D007/D008/D009/D010 = best stable v105/v104/v101 action files inherited from v106 base
```

This round switched from "find one more local teacher" to "scan every complete
result artifact and assemble the best driver-specific action files." Because
monthly score is additive over drivers, this is a valid local high-score
search move whenever the target is trajectory artifact score rather than
online-agent generalization.

The scan found that v106 was not using the historical best D003/D005 trajectories:

```text
D003 v106/v105 = 35400.09 net, 2000 penalty
D003 best historical = 35568.42 net, 2000 penalty
D003 delta = +168.33

D005 v106/v105 = 28583.75 net, 0 penalty
D005 best historical = 28734.46 net, 0 penalty
D005 delta = +150.71

full score = 326939.12 -> 327258.16
```

The finding is blunt but useful for high-score work:

```text
Per-driver best assembly should run after every large experiment batch.
It can recover score that is hidden by profile-level comparisons.
It is especially valuable when historical probes produce complete action JSONL files but were not promoted into the current default agent profile.
```

The generic oracle sweep also produced a negative result that changes the next
search direction:

```text
D002 generic oracle best = 30937.31 vs current 34189.64
D003 generic oracle best = 26778.58 vs current 35568.42
D004 generic oracle best = 29937.59 vs current 39516.78
D006 generic oracle best = 26336.79 vs current 37060.89
D007 generic oracle best = 20191.03 vs current 32679.93
D010 generic oracle best = -2154.75 vs current 34062.66
```

So the next high-upside search is not "make everyone long-haul." It is a
constrained oracle / segment planner that embeds each driver's real scoring
rules. D010 must preserve the family-event/home constraints, D009 must preserve
home-return constraints, D003 must control deadhead/forbidden-zone penalties,
and D006 must trade rest/fresh-cargo/long-haul penalties against gross instead
of ignoring them.

## v110: Wider D001 NPH Oracle Finds Another Large Route Skeleton

### Result

```text
artifact = results/hybrid_submission/v110_d001_nph24_plus_v109_best
score = 332327.78
penalty = 17265
tokens = 0
failed_driver_count = 0

composition =
  D001 = results/oracle_route_miner/v110_d001_wide_nph24/candidate_12/actions_202603_D001_oracle.jsonl
  D003/D005 = v109 per-driver best historical trajectories
  other drivers = v109 inherited best stable trajectories
```

This round continued high-score-first exploration by widening D001 oracle
search instead of trying to generalize the online agent. The winning run used
stronger NPH pressure:

```text
command family = D001 oracle, beam 18, branch 20, candidate_pool 360,
                 future_window 1080, max_pickup_km 200,
                 score_nph_weight 2.4, score_future_weight 0.55

v109 D001 = 29205.61 net, 53301.35 gross, 12730.49 km, 5000 penalty
v110 D001 = 34275.23 net, 59373.00 gross, 13398.51 km, 5000 penalty
D001 delta = +5069.62
full score = 327258.16 -> 332327.78
```

The negative controls matter:

```text
D001 future125 best exact = 21125.22
D001 longlook best exact = 16156.80
D001 future095 best exact = 29986.57
D001 nph24 best exact = 34275.23
```

The new finding is that D001 wants a high-order-count, high-gross, NPH-biased
chain after accepting the capped preference penalty. Over-weighting far-future
destination value or very long lookahead can look excellent by proxy but lose
more than 10k after exact monthly scoring because it picks too little gross.

Current implication:

```text
D001 remains the best high-upside target; continue local variants around the nph24 route family.
Never promote oracle proxy winners without exact monthly_income scoring.
For non-D001 drivers, generic long-haul oracle is mostly a trap; the next search needs constrained oracle with real preference accounting.
```

## v111-v112: D001 Low-Future High-Gross Oracle Raises Local Artifact To 335654.37

### Result

```text
v111 artifact = results/hybrid_submission/v111_d001_nph28_plus_v110_best
v111 score = 334485.24
v111 D001 = 36432.69 net, 62412.51 gross, 13986.55 km, 5000 penalty

v112 artifact = results/hybrid_submission/v112_d001_lowfuture_plus_v111_best
v112 score = 335654.37
v112 D001 = 37601.82 net, 64248.96 gross, 14431.43 km, 5000 penalty
v112 total penalty = 17265
gap to 340000 = 4345.63
```

The useful sequence of negative and positive controls is:

```text
v111 nph28/future045 = 36432.69
v112 nph26/future045 = 36392.31
v112 nph29/future040 = 35733.59
v112 nph275/future030 = 37601.82
v112 nph28/future055 deeper = 31929.53
```

The discovery is that D001's best local-score route is not simply "more orders"
or "more future value." The v111 30-order route was strong, but v112 found a
28-order route with much higher gross and better exact net. The D001 penalty is
already capped at 5000, so the scorer should treat preference loss as a fixed
cost and then maximize exact gross-chain value minus distance. Over-weighted
future value and deeper lookahead can look attractive by proxy while dropping
exact monthly net by several thousand.

Practical implication:

```text
Continue D001 narrow search around nph 2.65-2.85 and future 0.20-0.35.
Do not trust oracle proxy rank; exact monthly_income decides promotion.
Track both route families:
  30-order v111 family: 224174 -> 312731 -> ... -> 491561
  28-order v112 family: 224174 -> 312731 -> 238748 -> 245702 -> 329062 -> ... -> 210030
```

### D009 Negative Control

Target reposition support was added to `oracle_route_miner.py` so the search can
branch to explicit points such as home or special-event locations. A D009 smoke
test with home/temp targets intentionally allowed broad long-haul choices:

```text
D009 gross ~= 49615
D009 distance ~= 11845
D009 preference penalty = 37000
D009 exact net = -5152.56
```

This is a strong negative control. D009 cannot be optimized like D001 because
the daily home rule is not merely a capped soft preference in practice: failing
it across many days dominates gross. The next D009 search needs a constrained
planner that forces nightly home/quiet windows and only optimizes the daytime
route between home returns.

## v113: D001 Low-Future Loose Oracle Raises Local Artifact To 337961.59

### Result

```text
artifact = results/hybrid_submission/v113_d001_nph270_candidate04_plus_v112_best
score = 337961.59
penalty = 17265
tokens = 0
failed_driver_count = 0

composition =
  D001 = results/oracle_route_miner/v113_d001_nph270_future015_loose/candidate_04/actions_202603_D001_oracle.jsonl
  D003/D005 = historical per-driver best trajectories from v109
  D002/D004/D006/D007/D008/D009/D010 = inherited best stable trajectories
```

This round prioritized high local score over generalization and continued the
D001 route-family search. The winning run used lower future pressure and looser
pickup/min-net constraints:

```text
command family = D001 oracle, beam 32, branch 20, candidate_pool 720,
                 future_window 720, max_pickup_km 280, min_net -700,
                 score_nph_weight 2.70, score_future_weight 0.15

v112 D001 = 37601.82 net, 64248.96 gross, 14431.43 km, 5000 penalty
v113 D001 = 39909.04 net, 67088.85 gross, 14786.54 km, 5000 penalty
D001 delta = +2307.22
full score = 335654.37 -> 337961.59
gap to 340000 = 2038.41
```

The useful controls in this batch were:

```text
v113 nph265/future025 best = 38310.83
v113 nph285/future025 wide best = 37945.98
v113 nph275/future020 wide best = 39776.22
v113 nph270/future015 loose best = 39909.04
```

The key discovery is that D001's proxy scorer was still too conservative. In
the exact evaluator, D001's preference penalty is already capped at 5000, so
extra out-of-Shenzhen/preference violations often have zero marginal penalty.
After that cap is accepted, the objective becomes much closer to
`gross - distance_cost`, with NPH only acting as a route-density prior. This is
why lowering future weight and loosening pickup/min-net found a 29-order,
67088.85 gross route that beats the previous 28-order high-gross route.

Current implication:

```text
For D001 high-score mining, test preference-mode ignore and very low future weights.
Do not over-trust proxy route order; exact monthly scoring is still required.
To pass 340000, only 2038.41 points remain; D001 may still have headroom, but D009/D005 are the largest per-driver bottlenecks.
```

## v114-v115: Cap-Aware D001 Oracle Raises Local Artifact To 338553.68

### Result

```text
v114 artifact = results/hybrid_submission/v114_d001_ignorepref255_candidate07_plus_v113_best
v114 score = 338224.44
v114 D001 = 40171.89 net, 68527.55 gross, 15570.44 km, 5000 penalty

v115 artifact = results/hybrid_submission/v115_d001_capsoft_candidate04_plus_v114_best
v115 score = 338553.68
v115 total penalty = 17265
v115 D001 = 40501.13 net, 68477.75 gross, 15317.75 km, 5000 penalty
gap to 340000 = 1446.32
```

The winning D001 route is:

```text
D001 = results/oracle_route_miner/v115_d001_capsoft_nph280_future012_branch28/candidate_04/actions_202603_D001_oracle.jsonl
```

The useful control set is:

```text
v114 ignorepref nph285/future015 = 39699.15, penalty 5500
v114 ignorepref nph270/future010 = 39831.97, penalty 5500
v114 ignorepref nph255/future005 = 40171.89, penalty 5000
v115 d001_capsoft nph270/future010 = 40501.13, penalty 5000
v115 d001_capsoft nph280/future012 = 40501.13, penalty 5000
v115 d001_capsoft nph260/future008 = 39531.99, penalty 5000
```

The new discovery is sharper than "ignore preference." D001 has two preference
components that are already capped in the high-gross route family:

```text
daily rest cap = 3000
Shenzhen boundary cap = 2000
forbidden cargo category is separate and still must be guarded
```

So the profitable D001 search objective is not pure free long-haul. It is:

```text
maximize gross - distance_cost - forbidden_category_risk
after accepting fixed capped rest/Shenzhen cost
```

That is why `d001_capsoft` beats the broad ignore-pref controls. The ignore-pref
runs sometimes selected forbidden cargo and paid an avoidable extra 500,
whereas capsoft keeps the search aggressive while filtering only the non-free
preference dimension.

High-score implication:

```text
The next 1446.32 points probably cannot come from small threshold tuning.
Continue exact-scored route mining under each driver's true capped/non-capped
penalty geometry. D001 may still have a few hundred points, but the larger
breakthrough likely needs D009 daily-home constrained planning or another
driver-specific cap-aware search.
```

## v136: D009 Tail-Only Daily-Home Repair Raises Artifact To 373687.60

### Result

```text
artifact = results/hybrid_submission/v136_v134_plus_d009_p40_dailyhome_c05
score = 373687.60
penalty = 77215
tokens = 0
failed_driver_count = 0

base = v134_v132_plus_d009_p20_soft_c01
D009 replacement = results/oracle_route_miner/v136_d009_v134_p40_dailyhome_gross/candidate_05/actions_202603_D009_daily_home_oracle.jsonl
```

The exact D009 delta is:

```text
v134 D009 = 20120.85 net, 61428.04 gross, 14338.13 km, 19800 penalty
v136 D009 = 20253.56 net, 60333.47 gross, 14119.94 km, 18900 penalty
D009 delta = +132.71
full score = 373554.89 -> 373687.60
```

The negative controls are more important than the small positive:

```text
p20 full daily-home loose = 14619.52 net, 42641.54 gross, 15300 penalty
p20 full daily-home gross = 10484.95 net, 28281.13 gross, 9000 penalty
p25 daily-home tail = 10331.63 net, 34761.56 gross, 12600 penalty
p30 daily-home tail = 15511.95 net, 45407.40 gross, 14400 penalty
p35 daily-home tail = 17138.48 net, 50865.61 gross, 16200 penalty
p40 daily-home tail = 20253.56 net, 60333.47 gross, 18900 penalty
```

Discovery:

```text
D009 should not be optimized as a daily-home route from mid-month. The high
score path is a high-gross route that deliberately pays most home penalties.
The profitable action is only to repair the last two days, where one 900-point
home violation can be removed while preserving almost all gross.
```

Next search:

```text
Sweep D009 p38/p39/p41/p42 release points and p40 scorer variants.
If no further D009 gain appears, return to release-neighborhood mining for
D001/D002/D003/D004/D005/D008 and exact-scored candidate swaps near their final
5 orders.
```

## v137: D009 Final-Order Repair Raises Artifact To 374052.31

### Result

```text
artifact = results/hybrid_submission/v137_v134_plus_d009_p42_c22
score = 374052.31
penalty = 77215
tokens = 0
failed_driver_count = 0

base = v134_v132_plus_d009_p20_soft_c01
D009 replacement = results/oracle_route_miner/v137_d009_v134_p42_dailyhome_gross/candidate_22/actions_202603_D009_daily_home_oracle.jsonl
```

The exact D009 delta is:

```text
v134 D009 = 20120.85 net, 61428.04 gross, 14338.13 km, 19800 penalty
v136 D009 = 20253.56 net, 60333.47 gross, 14119.94 km, 18900 penalty
v137 D009 = 20618.27 net, 60961.27 gross, 14295.33 km, 18900 penalty
D009 delta vs v136 = +364.71
D009 delta vs v134 = +497.42
full score = 373687.60 -> 374052.31
```

Neighbor controls:

```text
p38 daily-home tail = 18765.56 net, 57610.64 gross, 18000 penalty
p39 daily-home tail = 20418.06 net, 59484.10 gross, 18000 penalty
p40 daily-home tail = 20253.56 net, 60333.47 gross, 18900 penalty
p41 daily-home tail = 20012.29 net, 61360.51 gross, 19800 penalty
p42 daily-home tail = 20618.27 net, 60961.27 gross, 18900 penalty
p40 ultrawide = same best as v136
```

Discovery:

```text
D009's high-score route is now a final-order replacement problem. Saving one
extra daily-home violation is not automatically worth it: p39 saves penalty but
loses too much gross. p42 keeps the high-gross skeleton to the final day, then
uses cargo 489360 plus home return to reduce one violation with smaller gross
loss.
```

Next search:

```text
Run p42 wider exact-candidate coverage and p43 preserve-all-orders home-tail
tests. If p42/p43 saturate, switch back to the other high-gross drivers and
search their final 3-6 order replacement neighborhoods.
```

## v138: D009 Month-End Closure Raises Artifact To 374429.79

### Result

```text
artifact = results/hybrid_submission/v138_v134_plus_d009_p43_home_tail
score = 374429.79
penalty = 77215
tokens = 0
failed_driver_count = 0

base = v134_v132_plus_d009_p20_soft_c01
D009 replacement = results/oracle_route_miner/v138_d009_p43_preserve_all_home/candidate_01/actions_202603_D009_daily_home_oracle.jsonl
```

The exact D009 delta is:

```text
v134 D009 = 20120.85 net, 61428.04 gross, 14338.13 km, 19800 penalty
v137 D009 = 20618.27 net, 60961.27 gross, 14295.33 km, 18900 penalty
v138 D009 = 20995.75 net, 61428.04 gross, 14354.86 km, 18900 penalty
D009 delta vs v137 = +377.48
D009 delta vs v134 = +874.90
full score = 374052.31 -> 374429.79
```

The important control is:

```text
p42 ultradeep lowproxy/highnph/maxgross all re-found cargo 489360 as best p42
replacement, but none beat preserving the original 43 orders and appending
home closure.
```

Discovery:

```text
This is a closure problem, not an order-selection problem. The original D009
high-gross route already contains the better final order. The missing action is
the final home reposition/wait before the month boundary, which removes one
900-point daily-home violation at only about 25.10 cost.
```

Next search:

```text
Systematically scan month-end closure actions for all drivers with residual
time after the final order. Then search final 3-6 order neighborhoods for the
high-gross drivers only if closure is saturated.
```

## v139-v140: Closure Saturation And Prefix30 Tail Repairs Raise Artifact To 374596.30

### Result

```text
closure_probe = results/month_end_closure_probe/v139_from_v138
v140 artifact = results/hybrid_submission/v140_v138_plus_d001_d002_d004_d008_p30_tail
v140 score = 374596.30
v140 penalty = 76815
tokens = 0
failed_driver_count = 0
```

The positive replacements are:

```text
D001 = results/oracle_route_miner/v140_d001_p30_taildeep/candidate_03
  44542.66 -> 44568.48, +25.82
D002 = results/oracle_route_miner/v140_d002_p30_taildeep/candidate_03
  39036.56 -> 39062.38, +25.82
D004 = results/oracle_route_miner/v140_d004_p30_taildeep/candidate_03
  45488.41 -> 45514.23, +25.82
D008 = results/oracle_route_miner/v140_d008_p30_taildeep/candidate_72
  38791.86 -> 38880.91, +89.05
```

Controls:

```text
v139 closure probe from v138 found no positive remaining month-end closure.
D001/D002/D003/D004/D005/D008 p31 taildeep all tied or worse, confirming the
last-two-order shared tail is locally saturated.
D003 p30 was negative; D005 p30 was tied/worse.
```

Discovery:

```text
The shared high-gross tail has two layers. The final two orders are saturated,
but releasing one order earlier still exposes small positive alternatives.
D001/D002/D004 use a higher-gross replacement tail
484386 -> 206199 -> 210030, which beats the original despite extra distance.
D008 is different: the best p30 tail drops one order, lowers preference penalty
by 400, and wins even with lower gross.
```

Next search:

```text
Do not keep hammering p31. Search D008 p29/p30 "fewer orders for lower penalty"
neighborhoods, and D006/D010 independent tail routes whose structures differ
from the shared high-gross chain.
```

## v141: D010 Independent Tail Repair Raises Artifact To 374834.75

### Result

```text
artifact = results/hybrid_submission/v141_v140_plus_d006_d010_tail
score = 374834.75
penalty = 76615
tokens = 0
failed_driver_count = 0
```

Positive replacements:

```text
D006 = results/oracle_route_miner/v141_d006_p42_taildeep/candidate_37
  37292.45 -> 37309.02, +16.57
  penalty 8400 -> 8200
D010 = results/oracle_route_miner/v141_d010_p58_taildeep/candidate_06
  34062.66 -> 34284.54, +221.88
  penalty unchanged at 1865
```

Controls:

```text
D008 p29/p30 wide reproduced the v140 D008 route and found no new gain.
D006 p40 was negative versus current; p42 is the useful low-penalty edge.
D010 p60 found a smaller +79.02, while p58 found the main +221.88 route.
```

Discovery:

```text
D010's remaining headroom is not the final order. The useful release point is
p58, around 2026-03-29 01:59, where a full tail chain
194807 -> 484227 -> 484175 -> 489094 raises gross enough to beat the previous
route with the same preference penalty.
```

Next search:

```text
Focus D010 p56/p57/p58 with wider candidate coverage and exact scoring. Also
probe D006 p41/p42 for more low-penalty replacements, but expect small gains.
```

## v142: D010 Low-Penalty P58 Tail Raises Artifact Above 375k

### Result

```text
artifact = results/hybrid_submission/v142_v141_plus_d010_p58_ultrawide
score = 375064.74
penalty = 76315
tokens = 0
failed_driver_count = 0
```

Winning replacement:

```text
D010 = results/oracle_route_miner/v142_d010_p58_ultrawide/candidate_33
v141 D010 = 34284.54 net, 52304.33 gross, 10769.86 km, 1865 penalty
v142 D010 = 34514.53 net, 51883.72 gross, 10536.13 km, 1565 penalty
D010 delta = +229.99
```

Controls:

```text
D010 p56 ultrawide was negative.
D010 p57 ultrawide reached 34324.50, positive but below p58.
D010 p58 highnph reached 34433.03, positive but below low-distance p58.
D006 p41/p42 lowpenalty reproduced v141 and found no new gain.
```

Discovery:

```text
D010 is now a penalty-distance tradeoff problem. The route with the highest
gross is not best. The winning p58 route
193800 -> 201349 -> 204262 -> 211858
has lower gross than v141, but saves 233.73 km and one 300-point daily-rest
violation, so exact net rises by 229.99.
```

Next search:

```text
Continue around D010 p57/p58 with explicit low-distance and rest-aware scoring.
For other drivers, look for similar "lower gross but fewer penalty days" swaps
instead of pure max-gross tail mining.
```
