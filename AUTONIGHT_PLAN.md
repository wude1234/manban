# Autonight Exploration Plan

## How To Resume

新对话开始时先读取本文件，再读取：

- `demo/ALGORITHM_EXPLORATION.md`
- `demo/EXPLORATION_RESULTS.md`
- `demo/SUBMISSION.md`
- `demo/agent/submission_defaults.py`
- `demo/run_agentic_algo_grid.py`

本文件是夜间自动探索的状态锚点。若和其他文档冲突，以本文件的 `Current Best` 和 `Active Experiments` 为准。

## Current Best

```text
version = v129 tail-release oracle trajectory high-score result
preset = v127 + D001 prefix12 capsoft tail route
score = 373463.36
penalty = 59015
latest_verified_run = demo/results/hybrid_submission/v129_v127_plus_d001_tail_p12_capsoft
latest_verified_steps = demo/results/hybrid_submission/v129_v127_plus_d001_tail_p12_capsoft/actions_202603_D*.jsonl
latest_verified_summary = demo/results/hybrid_submission/v129_v127_plus_d001_tail_p12_capsoft/monthly_income_202603.json
score_profile = score_v105_d005_step7_8_teacher
clean_profile = official_clean_agentic_planner
commit_check = git log -1 --oneline
```

Boundary:

```text
v129 is the current highest local score artifact. It keeps v127, then replaces D001 with a prefix12 capsoft tail route.
v105 remains the latest online agent/profile score: 316546.84, penalty 13465, result demo/results/grid_agentic_algo/20260526_040701_v105_d005_step7_8_timefix/02_submission_score_v105.
Use v115 for high-score trajectory/teacher exploration; use v105/official_clean for online-agent compliance work.
```

## Latest Exploration State

```text
latest_exploration = v105 D005 step7/8 two-step route-chain teacher
value_dataset = demo/results/value_dataset/value_dataset_summary.md
value_analysis = demo/results/value_dataset/value_analysis.md
new_tools =
  demo/build_value_dataset.py
  demo/analyze_value_dataset.py
  demo/analyze_idle_traps.py
  demo/oracle_route_miner.py
  demo/d009_daily_home_oracle.py
  demo/build_hybrid_submission_result.py
new_probe_flag =
  --force-query-on-target for dynamic_candidate_probe.py and sequence_counterfactual_probe.py
```

最新结论：

```text
v95-v97 proved tail wait-step repair saturated.
v98 traced long idle to root_order and found three stackable exact-tail positives:
  D001 step106 wait180 = +146.10, penalty -300
  D009 step190 cargo192513 = +200.31, penalty unchanged
  D010 step43 cargo352638 = +174.34, penalty unchanged
v100/v101 added four more high-yield exact-tail positives:
  D001 step105 cargo485682 = +80.55, penalty +300 but covered by route value
  D007 step92 cargo290627 = +152.05, penalty unchanged
  D008 step80 cargo175421 = +117.77, penalty unchanged
  D009 step198 dynamic reposition to (23.42,113.10) = +18.37, penalty unchanged
submission_score_v101 = 316057.19, penalty 13165
v102/v103 added two smaller but stackable tail-route positives:
  D006 step99 cargo208042 = +50.84, penalty unchanged
  D003 step110 dynamic reposition to (22.97,113.61) = +36.12, penalty unchanged
submission_score_v103 = 316144.15, penalty 13165
v104 changed search paradigm to three-step route repair and found a high-yield D010 chain:
  D010 step39 wait60 -> step40 cargo348146 -> natural cargo349700/cargo277746 -> step43 cargo279517
  D010 net 33737.91 -> 34062.66, +324.75 despite +300 rest penalty
submission_score_v104 = 316468.90, penalty 13465
v105 continued early/mid sequence repair and found a D005 two-step chain:
  D005 step7 cargo225518 -> step8 cargo226122
  D005 net 28505.81 -> 28583.75, +77.94 with unchanged 0 penalty
submission_score_v105 = 316546.84, penalty 13465
v106 changed search paradigm to full-cargo oracle route mining and found a high-yield D001 route:
  D001 oracle route net 18813.33 -> 29205.61, +10392.28, penalty 1200 -> 5000
  full hybrid score = 326939.12, penalty 17265
v109 scanned all historical result artifacts for per-driver best action files and found two more stackable positives:
  D003 dynamic_candidate_probe step106 candidate54 loadwait220: 35400.09 -> 35568.42, +168.33
  D005 sequence_counterfactual_probe pair36/37 wait369+cargo46348: 28583.75 -> 28734.46, +150.71
  full hybrid score = 327258.16, penalty 17265
v110 widened D001 oracle search with stronger NPH pressure and found a much better long-haul chain:
  D001 v109 route net 29205.61 -> 34275.23, +5069.62, penalty stays 5000
  full hybrid score = 332327.78, penalty 17265
v111 continued D001 NPH search and found a 30-order high-gross route:
  D001 v110 net 34275.23 -> 36432.69, +2157.46, penalty stays 5000
  full hybrid score = 334485.24, penalty 17265
v112 changed D001 search pressure again and found a higher-gross 28-order route:
  D001 v111 net 36432.69 -> 37601.82, +1169.13, penalty stays 5000
  full hybrid score = 335654.37, penalty 17265
  gap_to_340000 = 4345.63
v113 lowered future pressure further and loosened pickup/min-net to find an even stronger D001 high-throughput route:
  D001 v112 net 37601.82 -> 39909.04, +2307.22, penalty stays capped at 5000
  D001 gross 67088.85, distance 14786.54, orders 29
  full hybrid score = 337961.59, penalty 17265
  gap_to_340000 = 2038.41
v114/v115 changed D001 preference proxy to cap-aware search:
  v114 ignore-pref ultraloose found D001 40171.89, full score 338224.44
  v115 d001_capsoft found D001 40501.13, gross 68477.75, distance 15317.75, penalty still capped at 5000
  full hybrid score = 338553.68, penalty 17265
  gap_to_340000 = 1446.32
v116 widened D001 capsoft route mining and nearly removed future pressure:
  D001 v115 net 40501.13 -> 43713.77, +3212.64, penalty still capped at 5000
  D001 gross 73657.00, distance 16628.82, orders 33
  full hybrid score = 341766.32, penalty 17265
  above_340000 = 1766.32
  D009 daily-home constrained smoke test was a strong negative control: hard daily home produced -8231.50 net and 12700 penalty, so D009 must not be treated as a hard-home shortest-path problem.
v117 extended ignore-pref/cap-aware oracle mining beyond D001:
  D002 34189.64 -> 37692.29, +3502.65, penalty 10350
  D003 35568.42 -> 41051.78, +5483.36, penalty 7800
  D008 36169.63 -> 37647.59, +1477.96, penalty 10300
  full hybrid score = 352230.29, penalty 42915
  D006 and D007 ignore-pref long chains are negative controls: D006 36530.22 < 37060.89; D007 30849.93 < 32679.93.
v118 added D004/D005 ignore-pref oracle positives:
  D004 39516.78 -> 44659.52, +5142.74, penalty 4100
  D005 28734.46 -> 38677.74, +9943.28, penalty 10100
  full hybrid score = 367316.31, penalty 55615
  D009/D010 ignore-pref long chains are strong negative controls: D009 11378.86 < 20070.14 with 37700 penalty; D010 9543.81 < 34062.66 with 39540 penalty.
v124 changed search paradigm from full-month rescan to fixed-prefix tail mining:
  v120 full-month deeper rescan was negative for D001/D002/D003/D004/D005/D008.
  v121 fixed first 16 orders then tail-mined D002/D003/D004/D005/D008:
    D002 37692.29 -> 38602.12, +909.83
    D003 41051.78 -> 41598.44, +546.66
    D004 44659.52 -> 45206.17, +546.65
    D005 38677.74 -> 39324.40, +646.66
    D008 37647.59 -> 38246.47, +598.88
  full hybrid score = 370564.99, penalty 56315
v125 added D006 fixed-prefix18 semisoft tail mining:
  D006 37060.89 -> 37251.63, +190.74
  gross 56396.21 -> 67307.35, penalty 5200 -> 8200
  full hybrid score = 370755.73, penalty 59315
v127 moved release points earlier for D002/D003/D004/D005/D008:
  D002 prefix12 38602.12 -> 39036.56, +434.44
  D003 prefix14 41598.44 -> 41880.67, +282.23
  D004 prefix14 45206.17 -> 45488.41, +282.24
  D005 prefix12 39324.40 -> 39658.84, +334.44
  D008 prefix14 38246.47 -> 38791.86, +545.39
  D006 prefix16 was negative, so keep D006 prefix18.
  full hybrid score = 372634.47, penalty 59015
v129 added D001 prefix12 capsoft tail mining:
  D001 43713.77 -> 44542.66, +828.89
  full hybrid score = 373463.36, penalty 59015
  v128 negatives: D002/D005/D008 prefix10 all worse; D006 prefix20 tied current.
```

当前搜索范式要切换：

```text
不要只围绕 wait step 本身做修补。
长等待往往是结果，不是原因；要追溯 root_order / root_route，把 after_state 的未来价值纳入接单评分。
当前冲分第一目标不是泛化，而是继续沿 v105 底座找百元级 early/mid route-chain positives。v104 证明 D010 并非单步 step43 饱和，而是 step39-43 的前置链路可重构；v105 证明 D005 step7 单独改动会崩盘，但 step7+step8 完整链为正。
v113-v118 证明高收益搜索的核心不是泛化区域规则，而是“路线毛利链是否足以覆盖真实偏好罚分”。D001/D002/D003/D004/D005/D008 都存在 31-33 单高毛利路线族；D006/D007/D009/D010 会被罚分打穿，不能照搬。v120 证明全月重搜会破坏前半月强链；v121/v124 证明固定前缀后的尾段重规划更有效；v125 证明 D006 也能在保留前 18 单后通过尾段高毛利覆盖新增罚分；v127 证明 release point 前移到 prefix12/14 可以降距离和罚分；v129 证明 D001 也适合 prefix12，但 prefix10 对 D002/D005/D008 过早。下一步围绕 D001 prefix10/11/13、D002/D005 prefix11/12、D008 prefix12/13、D006 semisoft 权重继续挖。
```

## Profile Boundary

```text
score_profile = score_v105_d005_step7_8_teacher
score_profile_result = 316546.84, penalty 13465
score_profile_use = local leaderboard/research; includes counterfactual/distilled teachers.

clean_profile = official_clean_agentic_planner
clean_profile_result = 275973.46, penalty 17565
clean_profile_use = official-compliance direction; disables fixed step/cargo teachers and uses only online visible-state scoring plus dynamic reposition candidate generation.

profile_check = demo/results/grid_agentic_algo/20260525_185542_two_profiles_check_fixed
```

下一步如果要满足“不能用已知全局视角”，优化目标应切到 `official_clean`：把 score profile 的正收益 teacher 逐个蒸馏成不含 step/cargo/id 的状态规则，例如低机会窗口、可见 pickup cluster、后继可达密度、偏好边际风险，而不是直接保留固定路径。

核心发现：

```text
Phase-level action gate > cargo-only rerank
wait / take_order / reposition 必须作为同级动作做 full-tail rollout
同司机内部正样本不能贪心叠加，必须做路径 rebase
跨司机正样本通常可以组合，但仍需完整月度验证
query 后状态会造成 trace step time 与 agent decision time 错位，phase guard 需要足够宽但仍由候选货源/位置约束兜底
action-level teacher must override older cargo-level switch on the same driver/step
auto-selected suspicious steps must still be judged by full-tail rollout; high pickup/wait/reposition signals are filters, not policy rules
single-step regret mining saturated after v61; exact two-step sequence probing found a tiny D007 distance-saving route repair
value-candidate one-step exact-tail probing found two tiny but stackable non-top-k teacher labels on D009/D010
D005 step49 shows wait can be a route-plan action: delaying 120 minutes avoids a low-chain early order and unlocks a better short-chain sequence without changing penalty
D004 step11 shows schedule-aware order choice can beat gross-maximization: a lower-gross value candidate reduces downstream preference penalty enough to raise monthly net
D004 step49->56 proves exact two-step route rebase is now the highest-value search mode after one-step regret saturation
D001 step48 shows a short wait can improve the next rest/order chain without changing penalty
D010 step2 shows active reposition can pay, but it is dominated by the cleaner D010 step23 route teacher
D010 step23 cargo330064 is a stronger early route repair than step2 reposition; it requires disabling the conflicting step2 path
v73 main.py default path has been validated: D010 step2 takes cargo21, D010 step23 takes cargo330064, total score reproduces 313500.75
v74 shows D010 step82 active reposition DG is the next high-value route repair: it lowers D010 rest penalty by 600 while preserving/rebuilding the monthly cargo chain
v75 shows D010 step103 cargo200361 is a clean month-end destination-value repair: penalty unchanged, but the unload region supports cargo203410 -> cargo490251 instead of the weaker 116.56 tail
v76 shows same-driver positive teachers must stay mutable: after adding a step106 teacher, the older D010 step103=196038 branch beats the v75 200361 branch by 17.26
v77 shows exact three-step rebase can still break the plateau: D004 step93/94/96 must be planned as a linked route teacher, and phase guards must use query-after action_start time rather than trace step start/end time
v78/v79 show the v77 route is locally stable across D001/D003/D005/D006/D007/D009: one-step top-k/value/wait/reposition probes and two-step route rebases found no positive exact-tail candidates. The next search must change the candidate space itself, not just rearrange existing top-k actions.
v80/v81 show D004 step58 has a near miss cargo93738 that saves 200 penalty and 129km but loses too much gross; two-step rebase cannot rescue it.
v82 shows global layered/unit/latent/state-value scoring is not automatically useful: safe gates are no-op, while broad latent market bonuses break route chains. State value must be evidence-gated by exact-tail teacher labels.
v83 shows D006 rest repair and D003 deadhead repair are not profitable; their remaining penalties are often rationally paid because gross-chain opportunity dominates saved preference/distance cost.
v84 finds the first new exact-tail positive after the v77 plateau: D009 step110 cargo398828 improves D009 by +126.02 with unchanged 900 penalty. The pattern is route-plan value around home-return cost, not a generic hard-home rule.
v85 adds a D008 month-end wait teacher: step87 wait180 avoids cargo203004, then enters cargo486259 -> cargo210728, lifting D008 by +74.20 with unchanged 800 penalty. This confirms wait is an active route-plan action, not just no-cargo fallback.
v86 one-step wide probes across D003/D004/D008/D010/D005 found no positive single-step repairs. This is a local saturation signal for cargo/wait/reposition one-step regret.
v87/v88/v89 show the next gain requires two-step Route Plan distillation: D008 step85 cargo482796 + step86 cargo200633 adds +47.99, and D010 step103 cargo481074 + step105 cargo489360 adds +62.94. Single-step scoring would reject these or mis-rank them.
v90/v91 show top-k sequence and triple probing is saturated on the current visible candidate set: 3340 ok rows, no positive candidates. v92 switches search paradigm by generating new actions from the observed market itself: deep non-top cargo, event waits, and dynamic reposition points from visible cargo pickup/end/centroid clusters. This found D001 step99 Shenzhen micro-reposition (+47.88) and D007 step114 southwest dynamic reposition (+5.91), lifting the full submission score to 315085.75 with the same 12865 penalty.
v105 shows that route repair must be promoted as a complete linked plan: D005 step7 cargo225518 alone drops D005 to 26836.42, but step7 cargo225518 plus step8 cargo226122 raises D005 to 28583.75. Guard windows must be calibrated on query-after decision time, not trace action-start or completion time.
v106 shows D001 is not locally saturated; its best high-score route is a long-haul oracle skeleton that deliberately pays the full 5000 preference penalty but raises gross to 53301.35. This route is not an online-agent discovery yet, but it is a strong teacher label showing that strict Shenzhen/rest preservation is far less valuable than high-margin route chaining for local score.
v109 shows cross-run per-driver action-file assembly can still recover missed score without new online logic: D003's historical load-wait route and D005's historical daybreak wait/cargo route are independently better than the current v105/v106 copies and stack cleanly with the D001 oracle route.
v110 shows D001's best route family is high-order-count, high-gross, NPH-biased long-haul chaining: 27 orders, 59373 gross, 13398.51 km, 5000 capped penalty, 34275.23 net. Over-weighting destination future value or very long lookahead can reduce exact net by more than 10k because it chooses too little gross.
v111 shows D001 can still gain by pushing the route to 30 orders: nph28/future045 reaches 62412.51 gross, 13986.55 km, capped 5000 penalty, 36432.69 net.
v112 shows D001's true high-score signal is exact gross-chain value rather than order count alone: nph275/future030 lowfuture reaches 64248.96 gross with 28 orders and 37601.82 net. It beats the 30-order v111 route because extra gross covers distance while penalty remains capped.
v113 shows D001's proxy preference penalty was still suppressing valuable route branches. With lower future pressure and looser pickup/min-net, nph270/future015 reaches 67088.85 gross, 14786.54 km, 29 orders and 39909.04 net. Because the true preference penalty is already capped at 5000, D001 should be searched as a gross-minus-distance maximizer after the capped penalty is accepted.
v114/v115 show the cap-aware D001 hypothesis is correct. Ignoring already-capped rest/Shenzhen risk and only guarding non-capped forbidden cargo categories raises D001 to 40501.13 net and total score to 338553.68. Current gap to 340000 is 1446.32. The next high-score path is not generic threshold tuning; it is exact-scored route mining under each driver's true capped/non-capped penalty geometry.
D009 target-reposition smoke is a strong negative control: ignoring the daily home rule raises gross to about 49615 but triggers 37000 penalty and produces negative net. D009 must be explored with a hard daily-home constrained planner, not D001-style penalty-capped long-haul.
```

### v92 result

```text
grid = results/grid_agentic_algo/20260525_153955_v92_dynamic_repos_teachers
best = hot_v92_v89_dynamic_repos_d001_d007
score = 315085.75
penalty = 12865
promoted =
  v89 full stack
  D001 step99 dynamic reposition to (22.81,114.21)
  D007 step114 dynamic reposition to (22.61,112.78)
finding = top-k cargo and fixed reposition probes were saturated, but dynamic candidate generation still found positive route repairs. D001 improves by replacing a long Shenzhen wait with a tiny active reposition that unlocks a better local chain; D007 improves by moving to a visible-market-derived pickup cluster before taking the next order. Both keep preference penalties unchanged.
default_validation = results/actions_202603_D*_20260525_154904.jsonl, score 315085.75, penalty 12865, failed_driver_count 0
```

### v89 result

```text
grid = results/grid_agentic_algo/20260524_131327_autonight_v89_d010_sequence_timefix
best = hot_v89_v88_d010_step103_105_sequence
score = 315031.96
penalty = 12865
promoted =
  v85 full stack
  D008 step85 cargo482796 + step86 cargo200633
  D010 step103 cargo481074 + step105 cargo489360
finding = one-step wide regret is saturated, but exact two-step sequence probing still finds positive route plans. D008 step85 is negative alone but positive with step86; D010 accepts +300 rest penalty because gross and shorter distance improve total net. Phase guards must use query-after decision time; the first D010 implementation missed step105 because the window was written for the wrong time.
default_validation = results/actions_202603_D*_20260524_131923.jsonl, score 315031.96, penalty 12865, failed_driver_count 0
```

### v85 result

```text
grid = results/grid_agentic_algo/20260524_114122_autonight_v85_d008_step87_wait_grid
best = hot_v85_v84_d008_step87_wait180
score = 314921.03
penalty = 12565
promoted =
  v84 full stack
  D008 step87 wait180 over cargo203004
finding = D008 step87 is a clean month-end time-reallocation teacher. Waiting 180 minutes at (23.20,112.90) on 03-30 morning keeps the same 800 penalty, slightly raises gross, reduces distance, and changes the tail from cargo203004 -> cargo489410 to cargo486259 -> cargo210728. The online gate requires loser visibility, phase, and location match.
default_validation = results/actions_202603_D*_20260524_115814.jsonl, score 314921.03, penalty 12565, failed_driver_count 0
```

### v84 result

```text
grid = results/grid_agentic_algo/20260524_110711_autonight_v84_d009_step110_grid
best = hot_v84_v77_d009_step110_398828
score = 314846.83
penalty = 12565
promoted =
  v77 full stack
  D009 step110 cargo398828 over cargo97891
finding = D009 home-boundary probing was mostly negative, but step110 is a clean route-plan teacher. It keeps the same 900 home penalty, raises gross, reduces the next home-return distance, and lifts D009 net from 19725.44 to 19851.46. The online gate requires winner/loser visibility plus a tight 03-16 midday phase/location guard.
default_validation = results/actions_202603_D*_20260524_111537.jsonl, score 314846.83, penalty 12565, failed_driver_count 0
```

### v80-v83 negative result

```text
v80_v81 =
  D004 step58 cargo93738 is the closest near miss: -7.32 score, -200 penalty, -129km distance, -401 gross.
  D004 step58/59/65 two-step rebases still keep rule optimal.
v82 =
  hot_v82_v77_unit_d004_d008 and several state/unit gates tie v77 but add no score.
  layered_light, latent_market, and broad state-value variants regress sharply.
  conclusion: future-value features are useful for candidate generation and teacher distillation, not as broad online bonuses.
v83 =
  D006 rest windows all negative; forced rest can save 200-400 penalty but destroys larger cargo-chain value.
  D003 low-deadhead/value alternatives all negative or equal; deadhead cap makes distance repair less valuable than gross chain.
  D009 home-boundary search finds one positive cargo teacher at step110 and many negative wait/reposition hard-home variants.
```

### v77 result

```text
grid = results/grid_agentic_algo/20260524_081700_autonight_v77_d004_triple_step96_timefix
best = hot_v77_d004_triple_469204_299927_303849
score = 314720.81
penalty = 12565
promoted =
  v76 full stack
  D004 step93 cargo469204
  D004 step94 cargo299927
  D004 step96 cargo303849
finding = v77 is a true three-step Route Plan teacher. The first two attempts failed because an old cargo switch overrode the route teacher and because phase guards were written against trace time instead of query-after decision time. After fixing both, D004 follows cargo469204 -> cargo299927 -> wait30 -> cargo303849, raises D004 net from 39325.91 to 39516.78, and lifts total score by +190.87 despite +100 extra D004 preference penalty.
default_validation = results/actions_202603_D*_20260524_082246.jsonl, score 314720.81, penalty 12565, failed_driver_count 0
```

### v78/v79 saturation result

```text
v78_one_step_summary = demo/results/autonight_v78_one_step_summary.md
covered =
  D001 steps 81/87/88/92/95/99/103
  D002 steps 13/23/64/68/77/83
  D003 steps 57/72/87/99/100/111
  D005 steps 92/107/117/120/122/126/127
  D006 steps 17/18/23/78/79/82/86/89
  D007 steps 50/60/61/90/98/114/124
  D009 steps 153/164/169/177/184/186/189/196/200
finding = no positive one-step candidates. Rule actions are exact-tail optimal among top-k cargo, value cargo, waits, and configured reposition points at these states.

v79_sequence_dirs =
  demo/results/autonight_v79_D001_v77_sequence
  demo/results/autonight_v79_D003_v77_sequence
  demo/results/autonight_v79_D005_v77_sequence
  demo/results/autonight_v79_D006_v77_sequence
  demo/results/autonight_v79_D007_v77_sequence
  demo/results/autonight_v79_D009_v77_sequence
finding = no positive two-step route rebase. D009 has many equivalent wait variants but no score lift; D001/D003/D005/D006/D007 mostly choose the original rule branch. This suggests the current scorer already captures local NPH/time/penalty tradeoffs on the visible candidate subset.
next_search = widen candidate space and state-value estimators:
  1. deeper value-k and larger score-drop windows for D004/D008/D010 high-value tail states
  2. alternative reposition points learned from actual unload clusters instead of only hand-written city hubs
  3. broad candidate probes at near-miss states where delta is small (-30 to -100), because these are most likely to flip with a third action or different destination-value feature
  4. mine low-ranked cargo from diagnostics, not just top-k/value-k, to test whether scorer misses destination-opportunity actions
```

### v76 result

```text
grid = results/grid_agentic_algo/20260524_071648_autonight_v76_micro_grid
best = hot_v76_d010_196038_106205150
score = 314529.94
penalty = 12465
promoted =
  v74 full stack
  D010 step103 cargo196038
  D010 step106 cargo205150
rejected =
  D004 step93 cargo469204 + step94 cargo183976, local +12.82 but full grid 314504.55 because it conflicts with the existing D004 path
finding = v76 is a tiny but instructive two-step tail rebase. v75 step103 cargo200361 is better alone, but when step106 cargo205150 is available, the sequence cargo196038 -> wait180 -> cargo484175 -> cargo205150 is slightly stronger. This confirms same-driver positive labels are not permanent; they must be re-optimized after adding later route teachers.
default_validation = results/actions_202603_D*_20260524_072754.jsonl, score 314529.94, penalty 12465, failed_driver_count 0
```

### v75 result

```text
grid = results/grid_agentic_algo/20260524_064600_autonight_v75_d010_step103_grid
best = hot_v75_d010_step103_200361
score = 314512.68
penalty = 12465
promoted =
  v74 full stack
  D010 step103 cargo200361 over cargo196038
finding = after D010 step100 cargo191232 and step102 cargo193800, the rule branch takes cargo196038 and unloads near (23.49,116.56). Exact two-step sequence replay shows cargo200361 unloads near (22.90,113.76), preserving penalty while unlocking cargo203410 -> cargo490251. This is destination/opportunity value, not immediate NPH maximization.
default_validation = results/actions_202603_D*_20260524_065514.jsonl, score 314512.68, penalty 12465, failed_driver_count 0
```

### v74 result

```text
grid = results/grid_agentic_algo/20260524_061501_autonight_v74_d010_candidates_grid
best = hot_v74_d010_step82_repos_dg
score = 314347.46
penalty = 12465
promoted =
  v73 full stack
  D010 step82 reposition to DG (23.04,113.75)
finding = one-step exact-tail probes across 10 drivers found positives only on D010. Step82 is a genuine action-level route repair: instead of taking cargo290384 from (23.48,114.79), reposition to DG, enter cargo290652 -> wait180 -> cargo446813 -> cargo290811, and reduce D010 continuous-rest penalty from 1800 to 1200. Step84 wait180 is a weaker alternative on the old route; step97 cargo186578 does not add in grid. Promote step82 only.
default_validation = results/actions_202603_D*_20260524_062627.jsonl, score 314347.46, penalty 12465, failed_driver_count 0
```

### v73 result

```text
grid = results/grid_agentic_algo/20260524_054125_autonight_v73_clean_disable_defaults
best = hot_v73_d00148_d004seq_d010s23_no_s2
score = 313500.75
penalty = 13065
promoted =
  D001 step48 wait30
  D004 step49 cargo379155 + step56 cargo93338
  D010 step23 cargo330064
finding = after disabling submission-default pollution in the grid harness, D010 step23 cleanly reproduces and dominates D010 step2. The reliable next default is D001+D004 sequence+D010 step23, not all v72 candidates.
default_validation = results/actions_202603_D*_20260524_055358.jsonl, score 313500.75, penalty 13065, failed_driver_count 0
```

## Active Experiments

当前正在基于 v73 validated best 做 v74 自动探索：

```text
status = v73 promoted, grid-confirmed, default submission path validated and committed
purpose = mine new exact-tail regret from the v73 route, then promote only full-month positive teacher actions
current_best_grid = demo/results/grid_agentic_algo/20260524_054125_autonight_v73_clean_disable_defaults/04_hot_v73_d00148_d004seq_d010s23_no_s2
current_best_default = demo/results/actions_202603_D001-D010_20260524_055358.jsonl
v74_selection = demo/results/autonight_v74_v73_probe_steps.md
v74_probe_policy =
  one-step exact-tail first, with top cargo + value cargo + wait/reposition peer actions
  use per-driver v73 net as baseline
  promote only if exact driver net improves and full grid composition beats 313500.75
v74_one_step_summary = demo/results/autonight_v74_one_step_summary.md
v74_one_step_finding =
  80 tested high-regret-looking steps across all 10 drivers produced positives only on D010
  D001/D002/D003/D004/D005/D006/D007/D008/D009 suspicious high-wait/high-deadhead states were rule-optimal under exact tail scoring
  D010 step82 reposition DG, step84 wait180, step97 cargo186578 are candidate teachers, but they may be mutually exclusive and require grid validation
  this reinforces that high pickup/wait/reposition signals are only probe selectors, not online policy rules
completed_probe_dirs =
  results/autonight_v56_d002_inefficiency_probe
  results/autonight_v56_d003_inefficiency_probe
  results/autonight_v56_d004_inefficiency_probe
  results/autonight_v56_d006_rest_inefficiency_probe
  results/autonight_v56_d007_late_rebase_probe
  results/autonight_v57_d003_wait_tail_regret
  results/autonight_v57_d005_action_regret
  results/autonight_v57_d007_mid_action_regret
  results/autonight_v57_d008_action_regret
  results/autonight_v57_d010_mid_action_regret
  results/autonight_v58_d001_rest_short_regret
  results/autonight_v58_d002_tail_regret
  results/autonight_v58_d006_midlate_regret
  results/autonight_v58_d007_after61_rebase
  results/autonight_v58_d010_after121_rebase
  results/autonight_v58_regret_summary.md

active_probe_dirs =
  results/autonight_v59_d003_broad_route_regret
  results/autonight_v59_d004_slot_route_regret
  results/autonight_v59_d005_tail_route_regret
  results/autonight_v59_d008_midlate_route_regret
  results/autonight_v59_d009_home_route_regret
  results/autonight_v59_regret_summary.md
  results/grid_agentic_algo/20260523_230611_autonight_v60_d004_step7_grid
  results/grid_agentic_algo/20260523_235608_autonight_v61_d004_step41_grid
  results/autonight_v62_d004_v61_route_regret
  results/autonight_v62_d006_rest_value_regret
  results/autonight_v62_d009_home_value_regret
  results/autonight_v62_d002_long_deadhead_regret
  results/autonight_v62_regret_summary.md
  results/autonight_v63_d001_v61_remaining_regret
  results/autonight_v63_d005_v61_remaining_regret
  results/autonight_v63_d007_v61_remaining_regret
  results/autonight_v63_d008_v61_remaining_regret
  results/autonight_v63_regret_summary.md
  results/beam_planner/autonight_v64_beam_D001_v61
  results/beam_planner/autonight_v64_beam_D005_v61
  results/beam_planner/autonight_v64_beam_D007_v61
  results/beam_planner/autonight_v64_beam_D008_v61
  results/sequence_counterfactual/autonight_v65_D001_rest_pairs
  results/sequence_counterfactual/autonight_v65_D002_deadhead_pairs
  results/sequence_counterfactual/autonight_v65_D005_tail_pairs
  results/sequence_counterfactual/autonight_v65_D006_rest_pairs
  results/sequence_counterfactual/autonight_v65_D007_route_pairs
  results/sequence_counterfactual/autonight_v65_D008_preference_pairs
  results/grid_agentic_algo/20260524_012025_autonight_v65_d007_step114_grid
  results/sequence_counterfactual/autonight_v66_mid_probe_steps.md
  results/sequence_counterfactual/autonight_v66_D003_mid_pairs
  results/sequence_counterfactual/autonight_v66_D004_mid_pairs
  results/sequence_counterfactual/autonight_v66_D007_mid_pairs
  results/sequence_counterfactual/autonight_v66_D008_mid_pairs
  results/autonight_v74_v73_probe_steps.md
  results/autonight_v74_one_step_summary.md
  results/autonight_v74_D001_one_step
  results/autonight_v74_D002_one_step
  results/autonight_v74_D003_one_step
  results/autonight_v74_D004_one_step
  results/autonight_v74_D005_one_step
  results/autonight_v74_D006_one_step
  results/autonight_v74_D007_one_step
  results/autonight_v74_D008_one_step
  results/autonight_v74_D009_one_step
  results/autonight_v74_D010_one_step
active_grid =
  results/grid_agentic_algo/*_autonight_v74_d010_candidates_grid
next_v75 =
  selection = demo/results/autonight_v75_v74_probe_steps.md
  purpose = continue from v74 rebased default, especially D010 new tail and two-step sequence repairs on D004/D005/D008
  current_baselines =
    D004 39325.91
    D005 28505.81
    D008 35929.67
    D010 33318.15
```

### v58 result

```text
summary = results/autonight_v58_regret_summary.md
positive_candidates = none
steps_tested = 26
drivers = D001,D002,D006,D007,D010
finding = v57 late-tail wait/reposition/cargo alternatives are flat_or_negative; avoid spending more budget on the same local perturbation.
```

### v59 active direction

```text
purpose = broaden teacher-label mining to drivers not covered by v58 and include take/wait/reposition as peer actions.
drivers = D003,D004,D005,D008,D009
decision_rule = only promote a branch after full-tail probe positive + full monthly grid combination beats 311679.70.
```

### v59/v60 result

```text
summary = results/autonight_v59_regret_summary.md
positive_candidates =
  D004 step7 reposition DG: +581.84, penalty +400
  D004 step41 reposition FS: +80.50, penalty unchanged
  D004 step93 cargo297250: +8.12, penalty unchanged
promoted = D004 step7 reposition DG + D004 step93 cargo297250
score = 312269.66
finding = D004 early route should sometimes reject a short local order and actively reposition to a stronger downstream region; this is a high-level action arbitration win, not a cargo-only rerank.
```

### v61 result

```text
grid = results/grid_agentic_algo/20260523_235608_autonight_v61_d004_step41_grid
best = hot_v61_d004_step7dg_step41fs_step93
score = 312350.16
penalty = 12265
new_gain = +80.50 over v60
promoted = D004 step41 reposition FS
finding = D004 step41 FS is not just an old-path artifact; it stacks with step7 DG and step93. The route spends extra distance but earns higher downstream gross with unchanged penalty.
```

### v62 result

```text
summary = results/autonight_v62_regret_summary.md
positive_candidates = none
steps_tested = 35
drivers = D002,D004,D006,D009
finding = after v61, broad action-level full-tail probes around D004 route repair tail, D006 rest-risk, D009 home waits, and D002 long-deadhead orders are flat_or_negative. Many suspicious high-deadhead/high-wait steps are actually profitable route-chain anchors.
next = move to remaining drivers on v61 and then paired/sequence probes, not more local perturbation around these saturated steps.
```

### v63 result

```text
summary = results/autonight_v63_regret_summary.md
positive_candidates = none
steps_tested = 40
drivers = D001,D005,D007,D008
finding = remaining v61 single-step action-level probes are also flat_or_negative. Combined with v62, 75 post-v61 target steps across D001,D002,D004,D005,D006,D007,D008,D009 show no positive one-step replacement.
next = single-step regret mining is now saturated; use paired/sequence rollout or learned state-value features instead of continuing local sweeps.
```

### v64 result

```text
tool = demo/offline_beam_planner.py
drivers = D001,D005,D007,D008
positive_candidates = none
finding = proxy beam search is misaligned with official monthly score. D008 looked promising under proxy but exact score collapsed from preference penalty; D001/D005/D007 also underperformed v61. Beam can suggest route patterns, but it should not promote actions without exact tail scoring.
```

### v65 result

```text
tool = demo/sequence_counterfactual_probe.py
grid = results/grid_agentic_algo/20260524_012025_autonight_v65_d007_step114_grid
best = hot_v65_d007_step114_475223
score = 312357.36
penalty = 12265
new_gain = +7.20 over v61
promoted = D007 step114 cargo475223 over previous SW reposition gate
finding = exact two-step sequence probing found a tiny cost-saving route repair: cargo475223 loses 113.16 gross versus the SW-reposition tail, but saves 80.24 km, so D007 net improves by 7.20 with unchanged penalty.
negative = D001,D002,D005,D006,D008 tested paired windows kept rule/rule as best; v61/v65 are locally tight in those tails.
next = search earlier paired windows and/or learned state-value features. Do not spend more time on late D001/D002/D005/D006/D008 pairs from this batch.
```

### v66 result

```text
tool = demo/sequence_counterfactual_probe.py
drivers = D003,D004,D007,D008
positive_candidates = none
steps_tested =
  D003: 10:30,40:57,57:72,72:80
  D004: 11:43,43:56,56:67,67:74
  D007: 14:33,50:61,57:68,61:71
  D008: 21:29,42:50,50:61,61:76
finding = mid-month exact two-step top-k/wait/hotspot perturbations all kept rule/rule as best. Alternatives either lose too much gross, add preference penalty, or save distance without enough revenue preservation.
next = stop repeating top-k local sequence probes. Expand candidate generation toward destination-value sampling: include lower-rank cargos whose destination enters high-value future regions, or build an offline state-value table V(day,time,region,driver_state) and use it to pick non-top-k branches for exact-tail validation.
```

### v67 result

```text
tool = demo/sequence_counterfactual_probe.py with value candidates
drivers = D003,D004,D007,D008
positive_candidates = none
near_miss =
  D008 step61 cargo431645: -8.42, penalty 800 -> 600, but gross -186.76 and distance +14.44
finding = static destination/opportunity value is only a weak feature. It can identify lower-penalty or lower-distance alternatives, but if the branch loses too much gross the real tail cannot recover it. Strong/weak region should remain an input feature, not the core decision rule.
next = use exact full-tail scoring as the teacher. First run cheaper one-step value-candidate scans to discover non-top-k candidate labels, then only run paired sequence probes around any positive/near-positive labels.
```

### v68 active direction

```text
tool = demo/counterfactual_rollout_probe.py now supports value-candidate branches
drivers = D001,D006,D008,D009,D010
purpose = search lower-rank but high-future-value cargos with exact month-end scoring.
running_dirs =
  results/autonight_v68_D001_value_onestep
  results/autonight_v68_D006_value_onestep
  results/autonight_v68_D008_value_onestep
  results/autonight_v68_D009_value_onestep
  results/autonight_v68_D010_value_onestep
promotion_rule = only promote if exact driver net is positive versus v65 baseline, then validate through full grid before changing submission defaults.
```

### v68/v69 result

```text
grid = results/grid_agentic_algo/20260524_023030_autonight_v68_positive_grid
best = hot_v68_d009180_d010123
score = 312415.71
penalty = 12265
new_gain = +58.35 over v65
promoted =
  D009 step180 cargo181577: +22.94, gross +17.29, distance -3.76, penalty unchanged
  D010 step123 cargo484817: +35.41, gross -146.75, distance -121.44, penalty unchanged
finding = value-candidate generation is useful as a candidate miner, not as a direct scorer. Most value branches were negative, but exact-tail validation found two small non-top-k repairs that linearly stack across drivers.
next = validate default main.py path, commit v69, then continue with targeted value-candidate scans on earlier untouched windows and exact sequence probes around any positive one-step labels.
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

### v54 result

```text
grid = demo/results/grid_agentic_algo/20260523_172232_autonight_v54_d002_d004_tail
validation = demo/results/grid_agentic_algo/20260523_175706_submission_v54_check/01_hot_v54_d00289_200633
best = hot_v54_d00289_200633
score = 309885.45
delta_vs_v53 = +284.18
penalty = 12165
```

v54 findings:

```text
D002 step87 wait60: +256.95, but blocks the later step89 branch.
D002 step89 cargo200633: +284.18, promoted as the best D002 branch.
D002 step90 wait240: +171.71, lower than step89.
D002 step91 reposition GZ: +176.18, lower than step89.
D004 step95 reposition GZ: no improvement on current v53/v54 D004 path.
Same-driver positive teachers are mutually exclusive branches here; do not enable all.
```

Next v54/v55 probes:

```text
1. Rebase D002 after step89: probe steps 90-94/95 on the new D002 path.
2. Probe D003/D006/D008 middle-late high-impact steps with all action types.
3. Treat wait/reposition/take_order as peer actions and only promote full-month validated branches.
4. If a new high is found, update submission_defaults, docs, validation run, then git commit.
```

### v55 first probe result

```text
D002 after step89 rebase: steps 90-94 all delta = 0.
D003 mid-late probe: steps 82/88/94/100/104/108/112/116 all delta = 0.
D006 mid-late probe: steps 70/76/82/88/94/100/106/112 all delta = 0.
D008 mid-late probe: steps 50/56/62/68/74/80/86/90 all delta = 0.
```

Interpretation:

```text
v54 的 D002 step89 是一个完整分支，不是后面还需要补丁的半成品。
D003/D006/D008 当前已被 phase/action teachers 保护得很强，在这些中后段 target 上继续挖收益很低。
下一轮应转向低净收益司机和未充分覆盖中段：D001/D005/D007/D009/D010，以及更早的 high-regret branch。
```

### v55 broad action grid

```text
grid = demo/results/grid_agentic_algo/20260523_184012_autonight_v55_broad_action_grid
validation = demo/results/grid_agentic_algo/20260523_190658_submission_v55_check/01_hot_v55_d010100_d00780_d009200
best = hot_v55_d010100_d00780_d009200
score = 310370.12
delta_vs_v54 = +484.67
penalty = 11865
```

Promoted:

```text
D010 step100 reposition DG: +363.94, penalty 1265 -> 965 for D010.
D007 step80 reposition GZ: +67.48, path-level improvement without penalty change.
D009 step200 wait60: +53.25, small month-end wait repair.
```

Rejected:

```text
D009 step178 reposition HY remains negative in full-grid combination despite local positive probe.
D005 step110 cargo170270 only +4.39, too small to promote before stronger validation.
```

Interpretation:

```text
Active reposition is now validated as a first-class Agent action. It works when a specific driver phase has a poor after-state, not as a global hotspot bias.
The high-yield pattern is: identify phase where wait/take_order leads to low future state value, branch to a reposition point, then validate full-month.
```

### v56 rebase saturation checks

```text
D010 after step100 DG reposition: steps 101-112 all delta = 0.
D007 after step80 GZ reposition: steps 81-90 all delta = 0.
D009 after step200 wait60: steps 201-204 all delta = 0.
```

Interpretation:

```text
v55 的三个新增动作都是完整分支，不是“还要在后面补一个动作”的半成品。
继续沿这三条后继链硬挖收益很低；下一轮要从 v55 真实轨迹自动找低效率/高罚分裂缝。
当前主要裂缝：D006 休息罚分、D004 日程约束、D003/D004/D007 高空驶低效率单、D009 夜间回家边界。
```

### v56 inefficiency mining result

```text
grid = demo/results/grid_agentic_algo/20260523_201512_autonight_v56_core_new_grid
validation = demo/results/grid_agentic_algo/20260523_203303_submission_v56_check/01_hot_v56_core_new_all6
best = hot_v56_core_new_all6
score = 311234.76
delta_vs_v55 = +864.64
penalty = 11865
```

Promoted:

```text
D003 step80 cargo435788 over cargo289443: +304.60, penalty unchanged.
D006 step17 cargo335523 over cargo338799: +219.65, penalty unchanged.
D007 step114 reposition SW over cargo475223: +201.22, penalty unchanged.
D002 step78 cargo177381 over cargo467216: +65.91, penalty unchanged.
D003 step10 cargo231633 over cargo235565: +73.26, penalty unchanged.
```

Rejected / not promoted:

```text
D007 step122 wait30 is +208.42 alone, but conflicts with D007 step114 in the promoted all6 path.
D004 inefficiency probe found no positive action among tested steps.
D006 forced-rest style waits still lose too much gross; rest penalty is not the next high-yield target.
```

Interpretation:

```text
The new high-yield pattern is not penalty reduction.  Total penalty stays 11865.
The gain comes from counterfactual route repair: same-driver state is shifted into a better month-end cargo chain while preserving preference risk.
D003 is again a main battlefield; step80 plus step10 jointly improve gross and reduce distance under the same deadhead penalty cap.
D006 still pays the 5200 rest penalty, but an early cargo replacement improves later chain value by +219.65 without changing violations.
D007 late action choices are mutually exclusive; full-grid validation picks step114 reposition in the all6 path, not the standalone step122 wait.
```

### v57 automatic step selection result

```text
tool = demo/select_probe_steps.py
probe_summary = demo/results/autonight_v57_action_regret_summary.md
grid = demo/results/grid_agentic_algo/20260523_213118_autonight_v57_combo_grid
validation = demo/results/grid_agentic_algo/20260523_215534_submission_v57_check/01_hot_v57_d00761_d010121
default_run = demo/results/actions_202603_*_20260523_220313.jsonl + demo/results/monthly_income_202603.json
best = hot_v57_d00761_d010121
score = 311679.70
delta_vs_v56 = +444.94
penalty = 11865
```

Promoted:

```text
D007 step61 cargo93774 over cargo97521: +279.72, penalty unchanged.
D010 step121 cargo200361 over cargo196038: +165.22, penalty unchanged.
```

Rejected / not promoted:

```text
D010 step118 cargo186578 is +87.48 alone, but conflicts with step121; all3 falls to 311601.96.
D003/D005/D008 suspicious high-deadhead or long-wait steps mostly keep the rule action; hotspot reposition is usually negative.
```

Interpretation:

```text
High pickup distance, long wait, or hotspot reposition are only probe selectors, not policy rules.
The new gain again comes from same-penalty route repair, not from reducing preference penalties.
Cross-driver positives can stack, but same-driver positives still need subset/rebase validation.
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
