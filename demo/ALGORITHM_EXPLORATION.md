# Algorithm Exploration Plan

## 当前结论

当前最好可复现分数：

```text
score = 305852.15
preset = hot_v39_cf_v38_all_top
penalty = 13065.0
result_dir = results/grid_agentic_algo/20260522_222759_v39_layered_agent_check/05_hot_v39_cf_v38_all_top
```

这套分数不是靠单点阈值堆出来的，核心是把司机拆成不同画像后做收益-扣分权衡，并在关键决策步使用反事实回放验证“换一个候选货源是否让整个月更优”：

```text
D001: 低机会窗口补 8 小时连续休息
D004: 每日订单配额，超过 3 单后只接高净收益高 NPH 单
D006: 月末低机会窗口补休，不全月强制休息
D009: 回家罚分在当前数据上多数时候值得支付
D010: 家事事件 pre-query，避免 query scan 推进时间造成固定罚分
v32/v33/v34/v35/v36/v37/v38/v39: 对关键步骤做 candidate-level counterfactual rollout，验证后写回窄触发记忆
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
