# Manban Truck-Agent Experiments

本仓库记录 2026-05-09 版本卡车司机连续找货决策比赛的代码、实验结论、当前最好结果 artifact，以及可复现所需的官方数据快照。

## 当前最好结果

```text
best_artifact = demo/results/hybrid_submission/v169_d003_d008_exacttail
score = 376333.36
total_preference_penalty = 76515
failed_driver_count = 0
tokens = 0
summary = demo/results/hybrid_submission/v169_d003_d008_exacttail/monthly_income_202603.json
steps = demo/results/hybrid_submission/v169_d003_d008_exacttail/actions_202603_D*.jsonl
```

注意：`v169_d003_d008_exacttail` 是离线 oracle/tail-mining 高收益 artifact，使用了全量未来货源搜索结果；它用于研究和最高分轨迹讨论，不等同于无未来信息的合法在线 Agent。

当前在线/Agent profile 对照：

```text
submission_score_v105 = 316546.84
official_clean = 275973.46
official_clean_flash = 275973.46, tokens=0
official_distilled_value_v1 = 272961.58
```

## 仓库包含什么

```text
demo/agent/                         Agent 决策代码
demo/run_agentic_algo_grid.py        实验 preset / grid harness
demo/exact_tail_enumerator.py        离线 exact-tail 搜索工具
demo/results/hybrid_submission/      当前保留的高收益 artifact
demo/resources/official_data_20260509.tar.gz  0509 官方数据快照
demo_docs_release_20260529/          0529 二版/复赛方向 release、提交包和验证记录
demo/ALGORITHM_EXPLORATION.md        最完整的实验发现与正负例分析
demo/SUBMISSION.md                   当前提交版本、profile 和 artifact 说明
AUTONIGHT_PLAN.md                    夜间探索/新对话恢复用状态索引
docs/agent_algorithm_design.md       Agent 算法设计总结
```

## 恢复 0509 官方数据

仓库不直接提交 `demo/server/data/` 原始目录，而是提交压缩快照。clone 后运行：

```bash
cd /path/to/demo_docs_release_20260509
tar -xzf demo/resources/official_data_20260509.tar.gz -C demo/server
```

压缩包内容：

```text
data/cargo_dataset.jsonl
data/drivers.json
```

其中 `drivers.json` 为 0509 版本 D001-D010 共 10 个司机的官方快照，仅用于本仓库旧实验复现；它不是 20260529 二版/复赛隐藏数据。

`demo/server/config/config.json` 不入库。需要从模板复制：

```bash
cd /path/to/demo_docs_release_20260509
cp demo/server/config/config.example.json demo/server/config/config.json
```

真实 API key 通过环境变量传入，不要写进仓库：

```bash
export DASHSCOPE_API_KEY='your_key_here'
```

## 20260529 Release

`demo_docs_release_20260529/` 是后续二版/复赛方向的独立归档目录，包含：

```text
demo_docs_release_20260529/README.md
demo_docs_release_20260529/codex_change_log_20260605.md
demo_docs_release_20260529/submission_*.zip
demo_docs_release_20260529/demo/agent/model_decision_service.py
```

这个子目录不提交 `demo/server/data/` 原始数据。公开调试数据、隐藏司机与复赛新数据的边界见子目录 README。当前已记录的 20260529 方向最好线上成绩是：

```text
1780641880699_submission_hidden_guard_20260605.zip
submitted_at = 2026-06-05 14:44:40
score = -49585.3900
preference_penalty = 86559.2500
```

## 常用运行命令

验证当前在线 score profile：

```bash
cd /path/to/demo_docs_release_20260509/demo
/home/zrr/anaconda3/envs/llava/bin/python run_agentic_algo_grid.py --python /home/zrr/anaconda3/envs/llava/bin/python --tag score_v105_check --grid "submission_score_v105"
```

验证官方合规 clean profile：

```bash
cd /path/to/demo_docs_release_20260509/demo
/home/zrr/anaconda3/envs/llava/bin/python run_agentic_algo_grid.py --python /home/zrr/anaconda3/envs/llava/bin/python --tag clean_check --grid "submission_official_clean"
```

验证 Flash API profile：

```bash
cd /path/to/demo_docs_release_20260509/demo
DASHSCOPE_API_KEY="$DASHSCOPE_API_KEY" /home/zrr/anaconda3/envs/llava/bin/python run_agentic_algo_grid.py --python /home/zrr/anaconda3/envs/llava/bin/python --tag clean_flash_check --grid "submission_official_clean_flash"
```

批量探索合法在线 value scorer：

```bash
cd /path/to/demo_docs_release_20260509
JOBS=3 PYTHON_BIN=/home/zrr/anaconda3/envs/llava/bin/python demo/scripts/run_legal_value_batch.sh
```

这个脚本会批量跑：

```text
baseline: official_clean vs official_distilled_value
single_tight: D003/D008/D010 单司机 tight gate
pair_tight: 两两组合和 core tight
single_ultratight: 更保守 gate
single_light: 更放松 gate
```

日志在：

```text
demo/results/batch_logs/
```

## 重要边界

- `v169`、`v157`、`v154` 等 `hybrid_submission` artifact 是离线 oracle 结果，适合研究“最优路线为什么赢”。
- 赛事最终要求 Agent 不能使用未来信息、全量货源表或离线 oracle 轨迹来做路径选择判断；每一步只能基于当前合法接口可见的司机状态、候选货源和历史决策记忆。
- 因此，`v169` 这类静态最优结果不能直接作为最终在线策略提交，只能作为 teacher label / 事后分析样本，用来提取可泛化的状态规律。
- `official_clean` 是合规在线方向，只使用当前可观测状态、候选货源、司机私有记忆和偏好解析。
- `official_clean_flash` 是 API Agent 方向，Qwen3.5-Flash 只做受控 top-k 仲裁，不应直接自由调度。
- 当前合法蒸馏 value v1 是负例，说明 oracle 经验必须逐司机、窄 gate、近似同分场景消融后再加入。

## 最终算法目标

当前高分 artifact 给出的不是最终可提交算法，而是“未来最优路线的证据”。后续要做的是：

```text
离线 oracle / 静态最优轨迹
  -> 分析哪些状态选择带来长期收益
  -> 蒸馏成不使用未来信息的在线 value function / scorer
  -> 当前候选评分 = 当前净收益 + 完单后状态价值 - 偏好风险 - 闭环风险
  -> LLM 只在当前 top-k 近似同分或收益/偏好冲突时受控仲裁
```

最终提交版本应满足：

- 不读取 `demo/server/data/cargo_dataset.jsonl` 或任何全量未来货源。
- 不依赖固定 `driver_id + step + cargo_id` 的预录轨迹做路径选择。
- 只通过 `SimulationApiPort` 查询当前状态、当前可见候选和历史决策。
- 可以使用 v169 这类离线结果做离线训练、规则蒸馏和参数设计，但在线决策时不能查询或回放未来答案。
- 目标是在合规前提下尽量提高收益，而不是简单复刻 37w oracle 分数。

## 推荐阅读顺序

```text
1. AUTONIGHT_PLAN.md
2. demo/ALGORITHM_EXPLORATION.md
3. demo/SUBMISSION.md
4. docs/agent_algorithm_design.md
5. demo/README.md
```

## 当前主要启发

- 高分不是单步最高 NPH，而是路线链路、完单后位置、月末闭环和偏好罚分边际成本的组合。
- D001/D002/D003/D004/D005/D008 存在高毛利路线族，罚分可被 gross 覆盖；D006/D007/D009/D010 不能照搬。
- D009 的关键不是硬回家，而是保留高毛利骨架后做月末 home repair。
- D010 的关键不是 max gross，而是低距离、低罚分、能闭环的尾段路线。
- 将 oracle 结果转成合法在线 Agent 时，应该蒸馏成状态价值函数，而不是提交固定 step/cargo 轨迹。
