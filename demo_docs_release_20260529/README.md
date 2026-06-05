# Manban Truck-Driver Agent Competition Notes

本仓库整理了天池 Agent 开发大赛“司机找货 Agent 连续决策仿真赛”的赛题包、提交包、验证记录与重要实现说明。

## 当前推荐提交包

推荐使用已经过 live API 检查的最新版：

```text
submission_profile_compiler_livechecked_20260605_152621.zip
```

该 ZIP 内只包含复赛提交所需的 `demo/agent/`：

```text
demo/
└── agent/
    ├── __init__.py
    ├── model_decision_service.py
    └── requirements.txt
```

完整 31 天 live `qwen3.5-flash` 仿真记录见 `codex_change_log_20260605.md`：

- 237 completed steps
- remaining cargo count: 0
- driver failures: 0
- D001: normal, 115 steps, 113009 tokens
- D002: normal, 122 steps, 109665 tokens

## 线上历史提交成绩

以下为平台已完成测评的两次历史提交。平台文件名前缀为提交系统生成的 ID，本仓库内保留的是对应的本地 ZIP 文件。

| 平台文件名 | 本地对应 ZIP | 提交时间 | 状态 | 分数 | 偏好扣分 | 提示 |
| --- | --- | --- | --- | ---: | ---: | --- |
| `1780585172364_submission_selective_guard_20260604.zip` | `submission_selective_guard_20260604.zip` | 2026-06-04 22:59:32 | 测评完成 | -51920.5400 | 84899.2500 | ok |
| `1780503995670_submission_flash_qwen35_agent_only_20260604.zip` | `submission_flash_qwen35_agent_only_20260604.zip` | 2026-06-04 00:26:35 | 测评完成 | -129332.6600 | 188259.3600 | - |

22:59:32 的 `submission_selective_guard_20260604.zip` 相比 00:26:35 的 `submission_flash_qwen35_agent_only_20260604.zip`，平台分数提高了 77412.1200，偏好扣分减少了 103360.1100。

## 赛题需求重点

比赛主题是司机找货 Agent 连续决策仿真。Agent 需要在一个完整自然月内，持续根据司机状态、货源状态、时间、空间位置和个性化偏好做决策，目标是在遵守规则的前提下提升月度综合表现。

核心动作只有三类：

- `take_order`：从当前可见货源中选择一单并执行，环境推进到卸货完成后的时间和地点。
- `wait`：原地休息指定分钟数，位置不变。
- `reposition`：空驶到指定经纬度，按距离和速度消耗时间及成本。

评测不看单步最优，而是看整月策略质量。单笔高收益订单如果破坏偏好、导致长时间低效空驶或错过后续机会，最终可能得不偿失。

## 必须特别注意的规则

1. Agent 决策代码禁止直接读取 `demo/server/data/cargo_dataset.jsonl`、`demo/server/data/drivers.json`，也不能换路径整表扫描或缓存原始数据。
2. 决策所需信息必须通过评测环境接口获取，例如 `SimulationApiPort.query_cargo`、`get_driver_status`、`query_decision_history`。
3. `query_cargo` 本身会产生浏览耗时，返回条数越多，`query_scan_cost_minutes` 越高。
4. 正式评测会使用赛方统一环境重新运行并重算收益，本地 `monthly_income_202603.json` 只能作为自查参考。
5. 复赛提交包至少包含 `demo/agent/`，不要提交 `demo/results/`，也不要提交 `demo/server/data/`。
6. 不要把真实 API key 写入 `config.json` 或源码，使用 `DASHSCOPE_API_KEY` 环境变量。
7. 复赛约束包含总仿真运行时长上限和单司机 token 上限。当前赛题包配置中单司机 token 上限为 500 万。

## 评测口径

本地评测流程：

```bash
cd demo/server
python main.py

cd ..
python calc_monthly_income.py
```

主要产物：

- `demo/results/actions_202603_*.jsonl`：逐步动作记录。
- `demo/results/run_summary_202603.json`：仿真汇总。
- `demo/results/monthly_income_202603.json`：收益、token、偏好罚分和校验结果。

收益公式以赛题包为准：

```text
net_income = gross_income - distance_km * cost_per_km - preference_penalty
```

动作合法性会校验时间推进、位置变化、接单耗时、货源有效期、装货窗口和结果一致性。某个司机失败会按司机隔离处理，但该司机收益计算会受影响。

## 当前方案要点

最新版 `model_decision_service.py` 的重点是“模型理解偏好 + 本地规则兜底 + 防脏输出”：

- 缓存式 LLM 偏好编译，避免重复编译同一组司机偏好。
- 模型编译结果与本地解析结果合并，而不是替换本地结果。
- 对模型输出进行严格过滤，避免 schema 占位值、异常坐标、凭空 home deadline、过长休息窗、整月 blocked days 等污染策略。
- 保留本地确定性兜底，使 API 异常时仍可跑完仿真。
- 软偏好罚分不再简单“一刀切”，允许收益优势足够大的候选单通过风险门控。

## 本地保留的 ZIP

```text
submission_flash_qwen35_agent_only_20260604.zip
submission_flash_hidden_general_20260604.zip
submission_selective_guard_20260604.zip
submission_hidden_guard_20260605.zip
submission_profile_compiler_20260605_150710.zip
submission_profile_compiler_livechecked_20260605_152621.zip
```

建议后续提交优先从 `submission_profile_compiler_livechecked_20260605_152621.zip` 开始。

## 目录说明

```text
demo/
├── agent/                  # 参赛 Agent 决策代码
├── server/                 # 本地仿真入口和评测编排
├── simkit/                 # 仿真动作、状态管理和接口协议
├── results/                # 本地运行产物，正式复赛提交不需要
└── calc_monthly_income.py  # 本地收益与规则校验脚本

docs/                       # 赛题说明、数据说明、评测规则、提交方式
codex_change_log_20260605.md
```

## 上传与提交提醒

GitHub 仓库用于代码和记录归档；比赛平台正式提交仍只接受 ZIP。正式提交前请确认 ZIP 根目录为 `demo/`，且复赛包只带必要的 `demo/agent/`。
