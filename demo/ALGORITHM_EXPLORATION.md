# Algorithm Exploration Plan

## 当前结论

当前最好可复现分数：

```text
score = 314347.46
preset = hot_v74_d010_step82_repos_dg
penalty = 12465.0
result_dir = results/grid_agentic_algo/20260524_061501_autonight_v74_d010_candidates_grid/01_hot_v74_d010_step82_repos_dg
```

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
