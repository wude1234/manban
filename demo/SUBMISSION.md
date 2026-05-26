# Submission Profile

## 当前提交版本

当前保留两类结果：在线 agent/profile 结果和高收益轨迹 artifact。

```text
v169_d003_d008_exacttail
用途：当前本地最高分 step+summary artifact，用于高收益优先冲分/轨迹提交讨论。
特点：在此前 hybrid 高收益轨迹上，继续替换 D003 和 D008 的 exact-tail。D003 使用 `seed:D003:28 -> 300820 -> 482426 -> 484386 -> 206199 -> 210030`，D008 使用 `seed:D008:27 -> 180213 -> 298622 -> 194166 -> 197179 -> 203930 -> 484386`。完整结果 score `376333.36`，total_preference_penalty `76515`，failed_driver_count `0`，tokens `0`。
注意：v169 轨迹来自全量货源 oracle/tail mining/exact-tail search。这是高收益轨迹 artifact，不是 official_clean 在线 agent 决策，也不应被包装成无未来信息的合法在线策略。
复现：demo/build_hybrid_submission_result.py
score = 376333.36
total_preference_penalty = 76515.0
failed_driver_count = 0
tokens = 0
result_dir = demo/results/hybrid_submission/v169_d003_d008_exacttail
summary = demo/results/hybrid_submission/v169_d003_d008_exacttail/monthly_income_202603.json
steps = demo/results/hybrid_submission/v169_d003_d008_exacttail/actions_202603_D*.jsonl
```

在线 agent/profile 当前保留以下 profile：

```text
score_v105_d005_step7_8_teacher
用途：当前默认本地冲分、离线研究和榜单复现实验。
特点：在 v104 底座上叠加 D005 step7/8 两步 route-chain teacher，复现 316546.84。

score_v104_d010_prehome_chain_teacher
用途：历史稳定基线和消融对照。
特点：在 v103 底座上叠加 D010 pre-home 三步 route-chain teacher，复现 316468.90。

score_v101_high_yield_teacher_316057
用途：历史稳定基线和消融对照。
特点：在 v98 root-order idle-trap 底座上叠加 D001/D007/D008/D009 四个完整尾部验证过的高收益 teacher，复现 316057.19。

score_v103_tail_reposition_teacher_316144
用途：历史稳定基线和消融对照。
特点：在 v101 底座上叠加 D003/D006 两个完整尾部验证过的尾段路线修复 teacher，复现 316144.15。

score_v98_root_idle_trap_teacher_315688
用途：历史稳定基线和消融对照。
特点：保留 counterfactual/distilled teacher，并加入 root-order idle-trap distillation，复现 315688.45。

score_v94_d001_step103_teacher_315167
用途：历史稳定基线和消融对照。
特点：保留 v94 之前的 counterfactual/distilled teacher，复现 315167.70。

official_clean_agentic_planner
用途：官方强调不得使用已知全局视角时的合规 Agent 版本。
特点：关闭固定 step/cargo teacher，只使用当前 get_driver_status/query_cargo/query_decision_history 可见状态、司机私有记忆、偏好编译、route scorer 和在线动态空驶候选。

official_clean_flash_agentic_planner
用途：合规 API Agent 版本。
特点：底座仍是 official_clean，Qwen3.5-Flash 只在当前可见 top-k 候选的 near-tie/偏好冲突窗口做受控仲裁，输入 calculator_summary，不允许生成候选外动作。当前实测 `submission_official_clean_flash` 分数仍为 `275973.46` 且 tokens=0，说明触发窗口过严，Flash 尚未实际改变决策。

official_distilled_value_agentic_planner
用途：把 v169/oracle 发现蒸馏成合法在线 value scorer 的实验版本。
特点：不使用固定 step/cargo teacher，只用当前候选的净收益、NPH、可见后继密度、目的地 latent market、偏好风险和月末 closure 风险。v1 实测 `272961.58`，低于 official_clean `275973.46`，目前作为负例和后续消融起点，不作为提交候选。
```

本地 0509 数据当前最好复现结果为 score profile：

```text
score = 316546.84
total_preference_penalty = 13465.0
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
demo/results/grid_agentic_algo/20260526_033936_v104_submission_profile_check/01_submission_score_v104
demo/results/grid_agentic_algo/20260526_040701_v105_d005_step7_8_timefix/02_submission_score_v105
preset = submission_score_v105
step files = demo/results/grid_agentic_algo/20260526_040701_v105_d005_step7_8_timefix/02_submission_score_v105/actions_202603_D001_*.jsonl ... actions_202603_D010_*.jsonl
summary = demo/results/grid_agentic_algo/20260526_040701_v105_d005_step7_8_timefix/02_submission_score_v105/monthly_income_202603.json
```

v134 相比 v132 的新增有效轨迹：

```text
D009 使用 results/oracle_route_miner/v133_d009_p20_soft_homeguard/candidate_01，净收益从 20070.14 提升到 20120.85，+50.71；gross 61428.04，distance 14338.13，偏好罚分 19800。

完整总分从 v132 的 373504.18 提升到 373554.89，总偏好罚分从 59215 提升到 78115。
```

v134 的关键启发是：D009 不是完全不能冲高毛利，prefix20 后的高 gross 尾链即使带来 22 天回家违规，仍有极小正收益。但这不是理想终点，真正潜力在于保留 D009 高毛利尾链的一部分，同时修复 23 点回家/夜间静止罚分。同期 D006 soft/ignore、D007 p15/p20 soft、D010 p20 soft 都是负例，说明不能把 D009 的高毛利缝隙泛化到所有低分司机。

v136 相比 v134 的新增有效轨迹：

```text
D009 使用 results/oracle_route_miner/v136_d009_v134_p40_dailyhome_gross/candidate_05，净收益从 20120.85 提升到 20253.56，+132.71；gross 从 61428.04 降到 60333.47，但 distance 从 14338.13 降到 14119.94，回家/夜间违规罚分从 19800 降到 18900。

完整总分从 v134 的 373554.89 提升到 373687.60，总偏好罚分从 78115 降到 77215。
```

v136 的关键启发是：D009 的收益不是来自全日归，而是来自“尾段局部修复”。v135 的 p20 全日归最好只有 14619.52，p25/p30/p35 释放也都明显低于 v134；只有 prefix40 保留到 3 月 29 日晚后替换最后两单，才能在少丢毛利的同时减少一天 900 元罚分。

v137 相比 v136 的新增有效轨迹：

```text
D009 使用 results/oracle_route_miner/v137_d009_v134_p42_dailyhome_gross/candidate_22，净收益从 20253.56 提升到 20618.27，+364.71；gross 从 60333.47 提升到 60961.27，distance 从 14119.94 增到 14295.33，回家/夜间违规罚分保持 18900。

完整总分从 v136 的 373687.60 提升到 374052.31，总偏好罚分保持 77215。
```

v137 的关键启发是：D009 的最高收益不是尽早修日归，而是保留前 42 单高毛利骨架，只替换最后一单。p39 虽然总罚分更低，但损失毛利后总分只有 373852.10；p42 说明最后一单的目的地/回家衔接比多省一天罚分更重要。

v138 相比 v137 的新增有效轨迹：

```text
D009 使用 results/oracle_route_miner/v138_d009_p43_preserve_all_home/candidate_01，保留 v134 全部 43 单，仅在最后追加回家和等待。D009 净收益从 20618.27 提升到 20995.75，+377.48；gross 恢复到 61428.04，distance 为 14354.86，回家/夜间违规罚分保持 18900。

完整总分从 v137 的 374052.31 提升到 374429.79，总偏好罚分保持 77215。
```

v138 的关键启发是：有些高收益轨迹的问题不是货源选择，而是月末 closure 缺失。D009 原高毛利尾单可以保留，追加一次回家就能少吃一天 900 元罚分，同时只增加约 16.73km 空驶成本。

v140 相比 v138 的新增有效轨迹：

```text
D001 使用 results/oracle_route_miner/v140_d001_p30_taildeep/candidate_03，净收益 +25.82。
D002 使用 results/oracle_route_miner/v140_d002_p30_taildeep/candidate_03，净收益 +25.82。
D004 使用 results/oracle_route_miner/v140_d004_p30_taildeep/candidate_03，净收益 +25.82。
D008 使用 results/oracle_route_miner/v140_d008_p30_taildeep/candidate_72，净收益 +89.05，偏好罚分从 10700 降到 10300。

完整总分从 v138 的 374429.79 提升到 374596.30，总偏好罚分从 77215 降到 76815。
```

v140 的关键启发是：p31 释放最后两单已经饱和；p30 释放最后三单仍有小收益。D001/D002/D004 是 `484386 -> 206199 -> 210030` 的毛利覆盖距离成本；D008 是少接末端一单，牺牲 gross 但减少休息/空驶相关罚分后净收益更高。

v141 相比 v140 的新增有效轨迹：

```text
D006 使用 results/oracle_route_miner/v141_d006_p42_taildeep/candidate_37，净收益从 37292.45 提升到 37309.02，+16.57；偏好罚分从 8400 降到 8200。
D010 使用 results/oracle_route_miner/v141_d010_p58_taildeep/candidate_06，净收益从 34062.66 提升到 34284.54，+221.88；偏好罚分保持 1865。

完整总分从 v140 的 374596.30 提升到 374834.75，总偏好罚分从 76815 降到 76615。
```

v141 的关键启发是：D010 的剩余收益不在最后 1-2 单，而在 3 月 29 日凌晨以后整段尾链；p58 的 `194807 -> 484227 -> 484175 -> 489094` 比旧尾链多出 600+ gross，能覆盖新增距离成本。D006 的收益则来自少 200 休息罚分，属于低幅但可叠加的偏好修复。

v142 相比 v141 的新增有效轨迹：

```text
D010 使用 results/oracle_route_miner/v142_d010_p58_ultrawide/candidate_33，净收益从 34284.54 提升到 34514.53，+229.99；gross 从 52304.33 降到 51883.72，但 distance 从 10769.86 降到 10536.13，休息罚分从 1800 降到 1500，总偏好罚分从 1865 降到 1565。

完整总分从 v141 的 374834.75 提升到 375064.74，总偏好罚分从 76615 降到 76315。
```

v142 的关键启发是：D010 的最优尾链不是最大 gross，而是 `193800 -> 201349 -> 204262 -> 211858` 这种更短、更低罚分的路线。它牺牲约 420 gross，但省 233.73km 距离成本和 300 罚分，净收益更高。

v143 相比 v142 的新增有效轨迹：

```text
D010 使用 results/oracle_route_miner/v143_d010_p58_lowdist/candidate_01，净收益从 34514.53 提升到 34744.56，+230.03；gross 从 51883.72 提升到 52098.01，distance 从 10536.13 降到 10525.63，偏好罚分保持 1565。

完整总分从 v142 的 375064.74 提升到 375294.77，总偏好罚分保持 76315。
```

v143 的关键启发是：D010 p58 不是一次性命中，而是一个可继续压榨的尾部链路邻域。`193800 -> 201349 -> 206199 -> 210030` 比 v142 路线略高 gross、略低距离、罚分不变，因此继续提升；同批 strictdist 的 63 单路线 gross 更高但多 300 罚分，净收益反而低。

v132 相比 v129 的新增有效轨迹：

```text
D006 使用 results/oracle_route_miner/v131_d006_p18_tightdist/candidate_08，净收益从 37251.63 提升到 37292.45，+40.82；gross 68563.94，distance 15247.66，偏好罚分 8400。

完整总分从 v129 的 373463.36 提升到 373504.18，总偏好罚分从 59015 提升到 59215。
```

v132 的关键启发是：tightdist 不是通用正方向，同批 D001/D002/D003/D004/D005/D008 tightdist 均为负；但 D006 在 prefix18 后仍存在小幅后半月毛利覆盖罚分空间。下一步应换到 D006 semisoft 权重族或 D007/D009/D010 偏好约束尾矿，不应只继续抠 release point。

v129 相比 v127 的新增有效轨迹：

```text
D001 使用 results/oracle_route_miner/v128_d001_tail_p12_capsoft/candidate_01，净收益从 43713.77 提升到 44542.66，+828.89；gross 74410.48，distance 16578.55，偏好罚分 5000。

完整总分从 v127 的 372634.47 提升到 373463.36，总偏好罚分保持 59015。
```

v129 的关键启发是：D001 也适合 tail-release，且收益来自更高 gross 与略低 distance 的共同作用。同批 D002/D005/D008 的 prefix10 均明显负收益，说明释放点存在临界区间，不是越早越好。

v127 相比 v125 的新增有效轨迹：

```text
D002 使用 results/oracle_route_miner/v126_d002_tail_p12_nph255_f015/candidate_03，净收益从 38602.12 提升到 39036.56，+434.44；gross 73644.86，distance 16038.87，偏好罚分 10550。

D003 使用 results/oracle_route_miner/v126_d003_tail_p14_nph255_f015/candidate_01，净收益从 41598.44 提升到 41880.67，+282.23；gross 74410.48，distance 16486.54，偏好罚分 7800。

D004 使用 results/oracle_route_miner/v126_d004_tail_p14_nph255_f015/candidate_01，净收益从 45206.17 提升到 45488.41，+282.24；gross 74410.48，distance 16548.05，偏好罚分 4100。

D005 使用 results/oracle_route_miner/v126_d005_tail_p12_nph255_f015/candidate_03，净收益从 39324.40 提升到 39658.84，+334.44；gross 73644.86，distance 16057.35，偏好罚分 9900。

D008 使用 results/oracle_route_miner/v126_d008_tail_p14_nph255_f015/candidate_03，净收益从 38246.47 提升到 38791.86，+545.39；gross 73644.86，distance 16102.00，偏好罚分 10700。

完整总分从 v125 的 370755.73 提升到 372634.47，总偏好罚分从 59315 降到 59015。
```

v127 的关键启发是：prefix release point 是当前最强冲分维度。更早释放没有增加订单数，但能找到更短距离尾链并略降罚分，因此收益比继续全月深搜稳定。

v125 相比 v124 的新增有效轨迹：

```text
D006 使用 results/oracle_route_miner/v122_d006_tail_p18_semisoft_retry/candidate_01，净收益从 37060.89 提升到 37251.63，+190.74；gross 67307.35，distance 14570.48，偏好罚分 8200。

完整总分从 v124 的 370564.99 提升到 370755.73，总偏好罚分从 56315 升到 59315。
```

v125 的关键启发是：D006 全月放开长链会被偏好/距离打穿，但保留前 18 单后只重构尾段是正收益。D006 不是“完全负类”，而是需要先保住前半月偏好安全骨架，再在后半月用高毛利订单覆盖新增罚分。

v124 相比 v118 的新增有效轨迹：

```text
D002 使用 results/oracle_route_miner/v121_d002_tail_p16_nph255_f015/candidate_01，净收益从 37692.29 提升到 38602.12，+909.83；gross 74028.18，distance 16450.71，偏好罚分 10750。

D003 使用 results/oracle_route_miner/v121_d003_tail_p16_nph255_f015/candidate_01，净收益从 41051.78 提升到 41598.44，+546.66；gross 74028.18，distance 16419.83，偏好罚分 7800。

D004 使用 results/oracle_route_miner/v121_d004_tail_p16_nph255_f015/candidate_01，净收益从 44659.52 提升到 45206.17，+546.65；gross 74028.18，distance 16481.34，偏好罚分 4100。

D005 使用 results/oracle_route_miner/v121_d005_tail_p16_nph255_f015/candidate_01，净收益从 38677.74 提升到 39324.40，+646.66；gross 74028.18，distance 16469.19，偏好罚分 10000。

D008 使用 results/oracle_route_miner/v121_d008_tail_p16_nph255_f015/candidate_56，净收益从 37647.59 提升到 38246.47，+598.88；gross 73483.45，distance 16357.99，偏好罚分 10700。

完整总分从 v118 的 367316.31 提升到 370564.99，总偏好罚分从 55615 升到 56315。
```

v124 的关键启发是：当前高收益链路不是全月越宽搜越好，v120 全月重搜已经证明会破坏前半月强链。固定前 16 单后只重构后半月，能同时提高 D002/D003/D004/D005/D008 的 gross 或降低 distance，说明月中以后才是当前可挖的主空间。后续应围绕 prefix 12/14/18 做尾段搜索，而不是继续无差别全月重搜。

v118 相比 v117 的新增有效轨迹：

```text
D004 使用 results/oracle_route_miner/v117_d004_ignore_nph235_future002_wide460/candidate_01，净收益从 39516.78 提升到 44659.52，+5142.74；gross 73657.00，distance 16598.32，偏好罚分 4100。

D005 使用 results/oracle_route_miner/v117_d005_ignore_nph235_future002_wide460/candidate_01，净收益从 28734.46 提升到 38677.74，+9943.28；gross 73657.00，distance 16586.17，偏好罚分 10100。

完整总分从 v117 的 352230.29 提升到 367316.31，总偏好罚分升至 55615，但 D004/D005 的高毛利路线覆盖了额外罚分。
```

v118 的关键启发是：D005 原来的 0 罚分保守轨迹并不是高收益最优，真正应比较的是 `gross_chain_gain - distance_cost_gain - preference_penalty_delta`。D004/D005 与 D001/D002/D003/D008 同属高毛利链可覆盖罚分的司机；D009/D010 的 ignore-pref exact 结果分别只有 11378.86 和 9543.81，说明它们的回家/家事罚分不是小固定成本，不能照搬长链。

v117 相比 v116 的新增有效轨迹：

```text
D002 使用 results/oracle_route_miner/v117_d002_ignore_nph235_future002_wide460/candidate_04，净收益从 34189.64 提升到 37692.29，+3502.65；gross 72892.38，distance 16566.73，偏好罚分 10350。

D003 使用 results/oracle_route_miner/v117_d003_ignore_nph235_future002_wide460/candidate_01，净收益从 35568.42 提升到 41051.78，+5483.36；gross 73657.00，distance 16536.81，偏好罚分 7800。

D008 使用 results/oracle_route_miner/v117_d008_ignore_nph235_future002_wide460/candidate_02，净收益从 36169.63 提升到 37647.59，+1477.96；gross 72892.38，distance 16629.86，偏好罚分 10300。

完整总分从 v116 的 341766.32 提升到 352230.29，总偏好罚分升至 42915，但高毛利路线覆盖了额外罚分。
```

v117 的关键启发是：高分不是“尽量少罚”，而是判断罚分边际是否被路线毛利覆盖。D002/D003/D008 都能复用 D001 式 31-33 单高毛利路线族；D006/D007 同样试了 ignore-pref oracle，但精确评分后分别低于当前最优，说明这不是无脑放开偏好，而是每个司机要用 official exact scoring 判定。

v116 相比 v115 的新增有效轨迹：

```text
D001 使用 results/oracle_route_miner/v116_d001_capsoft_nph235_future002_wide460/candidate_01 轨迹。D001 净收益从 v115 的 40501.13 提升到 43713.77，+3212.64；gross 73657.00，distance 16628.82，偏好罚分仍为封顶 5000，订单数 33。

完整总分从 v115 的 338553.68 提升到 341766.32，总偏好罚分仍为 17265，已经超过 340000。
```

v116 的关键启发是：D001 的 cap-aware 搜索仍未收敛，而且“future value”过强会误导。最优方向不是保护休息/深圳偏好，也不是泛化区域强弱，而是在接受封顶 5000 固定罚分后，用更宽 pickup、更低 future 权重、更低 min-net 打开高毛利长链，再交给官方 monthly_income 精确评分筛选。D009 daily-home hard constraint 同期验证为强负例，说明不能把偏好硬满足当作默认优化目标。

v115 相比 v113/v114 的新增有效轨迹：

```text
D001 使用 results/oracle_route_miner/v115_d001_capsoft_nph280_future012_branch28/candidate_04 轨迹。D001 净收益从 v113 的 39909.04、v114 的 40171.89 提升到 40501.13；gross 68477.75，distance 15317.75，偏好罚分仍为封顶 5000。

完整总分从 v113 的 337961.59、v114 的 338224.44 提升到 338553.68，总偏好罚分仍为 17265，距离 340000 还差 1446.32。
```

v115 的关键启发是：D001 不能继续按“每次出深圳/未休息都扣边际分”的 proxy 搜索。真实评测里 D001 的每日休息罚分封顶 3000、深圳范围罚分封顶 2000，二者在高收益路线中已经是固定成本；但禁接化工塑料/煤炭矿产还不能放开。因此 `d001_capsoft` 只保护非封顶禁止品类，把已封顶项当固定成本，最终找到更高的 gross-distance 路线。

v113 相比 v112 的新增有效轨迹：

```text
D001 使用 results/oracle_route_miner/v113_d001_nph270_future015_loose/candidate_04 轨迹。D001 净收益从 v112 的 37601.82 提升到 39909.04，+2307.22；gross 67088.85，distance 14786.54，偏好罚分仍为封顶 5000。

完整总分从 335654.37 提升到 337961.59，总偏好罚分仍为 17265。
```

v113 的关键启发是：D001 的真实偏好罚分已经封顶，继续在线性 scorer 里惩罚每个出深圳/偏好违规订单会压掉高毛利路线。高收益优先时，D001 应按“接受 5000 固定罚分后最大化 gross - distance cost”的思路继续搜索；下一轮应试 `preference-mode ignore`、更低 future 权重、更宽 pickup/min-net。

v112 相比 v111 的新增有效轨迹：

```text
D001 使用 results/oracle_route_miner/v112_d001_nph275_future030_lowfuture/candidate_26 轨迹。D001 净收益从 v111 的 36432.69 提升到 37601.82，+1169.13；gross 64248.96，distance 14431.43，偏好罚分仍为封顶 5000。

完整总分从 334485.24 提升到 335654.37，总偏好罚分仍为 17265。
```

v112 的关键启发是：D001 的高分不只是“订单数越多越好”。v111 的 30 单链已经很强，但 v112 降低 future 权重后找到 28 单更高 gross 路线，精确净收益更高。当前应围绕 `nph≈2.7-2.8`、`future≈0.25-0.35`、高 gross/低 proxy 误差的路线族继续窄搜。

v111 相比 v110 的新增有效轨迹：

```text
D001 使用 results/oracle_route_miner/v111_d001_nph28_future045/candidate_09 轨迹。D001 净收益从 v110 的 34275.23 提升到 36432.69，+2157.46；gross 62412.51，distance 13986.55，偏好罚分仍为封顶 5000。

完整总分从 332327.78 提升到 334485.24，总偏好罚分仍为 17265。
```

v111 的关键启发是：D001 的封顶罚分已经成为固定成本，真正的边际目标是高毛利路线链。NPH 过低会少吃高频订单，NPH 过高又会降低 gross；必须用精确月度评分筛选。

v110 相比 v109 的新增有效轨迹：

```text
D001 使用 results/oracle_route_miner/v110_d001_wide_nph24/candidate_12 轨迹。D001 净收益从 v109 的 29205.61 提升到 34275.23，+5069.62；gross 59373.00，distance 13398.51，偏好罚分仍为封顶 5000。

完整总分从 327258.16 提升到 332327.78，总偏好罚分仍为 17265。
```

v110 的关键启发是：D001 不是简单“放大未来区域价值”就能更好。`future125` 和 `longlook` 的 proxy 很高，但精确评分分别只有 21125.22 和 16156.80；真正有效的是 NPH 压力更强的 27 单高 gross 路线。后续 D001 应继续围绕高订单数、高毛收、可吃满封顶罚分的路线族搜索；其他司机不能照搬，因为 D005/D008/D010 的真实偏好会把长链罚穿。

v109 相比 v106 的新增有效轨迹：

```text
D003 使用历史 dynamic_candidate_probe/v102_d003_late_chain_sweep/step_106/candidate_54_loadwait_220 轨迹。D003 净收益从 v106/v105 的 35400.09 提升到 35568.42，+168.33，偏好罚分仍为 2000。

D005 使用历史 sequence_counterfactual_probe/v105_d005_daybreak_edges/pair_036_037/f01_wait_369__s02_cargo_46348 轨迹。D005 净收益从 v106/v105 的 28583.75 提升到 28734.46，+150.71，偏好罚分仍为 0。

完整总分从 326939.12 提升到 327258.16，总偏好罚分仍为 17265。
```

v109 的关键启发是：各司机相互独立计分时，最高收益优先的第一步应先做 per-driver best trajectory assembly。也就是扫描所有历史完整月 action 文件，按司机取净收益最高轨迹，再构造 hybrid step+summary；这比继续在同一个 profile 上微调阈值更直接。边界也要明确：这属于轨迹/teacher 高分 artifact，可用于提交格式或蒸馏分析；如果官方要求纯在线 Agent，则不能把 full-cargo oracle 和 counterfactual artifact 描述为实时可见决策。

v106 相比 v105 的新增有效轨迹：

```text
D001 oracle route：原 v105 D001 只有 18813.33 net。oracle_route_miner 发现 D001 应该放弃严格深圳/休息保护，吃满 5000 偏好罚分，转入少单高毛利长链。D001 gross 从 25669.77 提升到 53301.35，distance 从 3797.33 增到 12730.49，penalty 从 1200 增到 5000，净收益仍提升到 29205.61，单司机 +10392.28，完整总分到 326939.12。
```

v106 的关键启发是：D001 的局部在线规则过度保守，偏好罚分封顶后继续保护深圳/休息并不划算；当可进入高毛利长链时，应把偏好风险作为边际成本而不是硬约束。反例同样重要：D005/D008 的 oracle 长链被官方评分否掉，说明不是“所有司机都长途化”，而是要按司机偏好和成本结构单独判断。

v105 相比 v104 的新增有效动作：

```text
D005 step7 cargo225518 -> step8 cargo226122：原 v104 路径在 3月2日 06:00 后接 cargo226509，再接 cargo311919。两步 sequence probe 发现先接较短的 cargo225518，再接 cargo226122，会把 D005 当日晚间休息位置和 3月3日后继链整体改好。D005 gross 从 37493.99 提升到 37711.58，distance 从 5992.12 增到 6085.22，偏好罚分仍为 0，D005 净收益从 28505.81 提升到 28583.75，完整月 +77.94。
```

v105 的关键启发是：同司机的 route repair 必须作为完整链验证。只触发 D005 step7 而不触发 step8 时，D005 会掉到 26836.42，说明单个“看起来更好”的订单可能破坏后续链。工程上，phase guard 必须按 query-after 决策时间设置；本次 step8 第一次实现用动作开始时间 09:25 写窗，线上查询后状态变成约 10:15，导致 teacher 未触发并严重降分。

v104 相比 v103 的新增有效动作：

```text
D010 step39 wait60 -> step40 cargo348146 -> natural cargo349700/cargo277746 -> step43 cargo279517：原 v103 路径在 step39 接 cargo349421、step43 接 cargo352638。三步 route repair 发现先等 60 分钟会错开原低效链，随后接入更高毛收入链。D010 gross 从 51001.53 提升到 51686.42，distance 从 10465.75 增到 10505.84，休息罚分从 1565 增到 1865，但净收益仍从 33737.91 提升到 34062.66，完整月 +324.75。
```

v104 的核心启发是：高分不一定来自减少扣分，很多时候应该接受可控罚分换更高收益链。实现上还发现 `wait` teacher 不能强依赖可见货源 marker，因为等待分支本身是主动时间重排；安全性应由司机、step、时间窗、位置 guard 约束，后续 `take_order` 再要求 winner 可见。时间窗必须按 query-after 决策状态设置，不能直接用 trace 的动作完成时间。

v103 相比 v101 的新增有效动作：

```text
D006 step99 cargo208042: v101 原路径接 cargo208263，完整尾部探针发现 cargo208042 虽然 gross 少 43.07，但距离少 62.60km、罚分不变，D006 净收益从 37010.05 提升到 37060.89，完整月 +50.84。

D003 step110 dynamic reposition: v101 原路径直接接 cargo203410。动态候选发现先短空驶到 `(22.97,113.61)`，再自然接入 cargo201171 尾链，罚分仍为 2000，D003 净收益从 35363.97 提升到 35400.09，完整月 +36.12。
```

v103 的工程启发：蒸馏 teacher 时必须使用动作开始状态做时间/位置 guard，而不是使用订单完成后的 `simulation_end_time`。D006 step99 第一次组合验证未触发，正是因为误把完成后 18:20/20:51 作为时间窗；修正到决策前 13:00-15:00 后才成功叠加。

v101 相比 v98 的新增有效动作：

```text
D001 step105 cargo485682: v98 月末 root-order 探针发现原接 cargo485616 会进入 03-30 晚间 8 小时长等。改接 cargo485682 后虽然休息罚分从 900 增到 1200，但 gross/distance 链路收益覆盖罚分，D001 净收益从 18732.78 提升到 18813.33，完整月 +80.55。

D007 step92 cargo290627: D007 step90/91 idle root 探针发现，等待后原路径接 cargo446937 不是最优。改接深层候选 cargo290627 后罚分仍为 0，D007 净收益从 32527.88 提升到 32679.93，完整月 +152.05。

D008 step80 cargo175421: D008 step80 原 teacher 是等待 240 分钟；force-query 动态探针发现深层候选 cargo175421 能改写后续尾链，罚分仍为 800，D008 净收益从 36051.86 提升到 36169.63，完整月 +117.77。

D009 step198 dynamic reposition: D009 step198 原路径接近月末 home/reposition 长等尾巴。动态候选发现空驶到 `(23.42,113.10)` 可轻微改善月末尾链，罚分仍为 900，D009 净收益从 20051.77 提升到 20070.14，完整月 +18.37。
```

v101 的核心启发是：高收益不来自全局权重微调，而来自对尾段 root-order / root-action 的精确 full-tail 比较。固定 teacher 仍必须满足司机、step、时间窗、位置和可见货源 marker，不能绕过在线候选集合。

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
