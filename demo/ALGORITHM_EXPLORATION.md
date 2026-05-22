# Algorithm Exploration Plan

## 当前结论

当前最好可复现分数：

```text
score = 307670.65
preset = hot_v48_cf_v47_d010_d004_d009178
penalty = 12465.0
result_dir = results/grid_agentic_algo/20260523_034757_v48_d009_split_combo/03_hot_v48_cf_v47_d010_d004_d009178
```

这套分数不是靠单点阈值堆出来的，核心是把司机拆成不同画像后做收益-扣分权衡，并在关键决策步使用反事实回放验证“换一个候选货源是否让整个月更优”：

```text
D001: 低机会窗口补 8 小时连续休息
D004: 每日订单配额，超过 3 单后只接高净收益高 NPH 单
D006: 月末低机会窗口补休，不全月强制休息
D009: 回家罚分在当前数据上多数时候值得支付
D010: 家事事件 pre-query，避免 query scan 推进时间造成固定罚分
v32-v48: 对关键步骤做 candidate/action-level counterfactual rollout，验证后写回窄触发记忆、状态蒸馏门和 phase-level action gate
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
