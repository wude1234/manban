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

`demo/server/config/config.json` 不入库。需要从模板复制：

```bash
cd /path/to/demo_docs_release_20260509
cp demo/server/config/config.example.json demo/server/config/config.json
```

真实 API key 通过环境变量传入，不要写进仓库：

```bash
export DASHSCOPE_API_KEY='your_key_here'
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

## 重要边界

- `v169`、`v157`、`v154` 等 `hybrid_submission` artifact 是离线 oracle 结果，适合研究“最优路线为什么赢”。
- `official_clean` 是合规在线方向，只使用当前可观测状态、候选货源、司机私有记忆和偏好解析。
- `official_clean_flash` 是 API Agent 方向，Qwen3.5-Flash 只做受控 top-k 仲裁，不应直接自由调度。
- 当前合法蒸馏 value v1 是负例，说明 oracle 经验必须逐司机、窄 gate、近似同分场景消融后再加入。

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

