# Manban Truck-Driver Agent Competition Notes

本仓库整理了天池 Agent 开发大赛“司机找货 Agent 连续决策仿真赛”的赛题包、提交包、验证记录与重要实现说明。

## 给协作者快速上手

这个目录的目标不是只保存一个提交包，而是让后续协作者能继续分析、复现和改进 Agent：

- 阅读赛题规则：从 `docs/`、`demo/README.md` 和本文的“赛题需求重点”开始。
- 改进策略代码：主要入口是 `demo/agent/model_decision_service.py`。
- 对照历史方案：查看各个 `submission_*` 目录和 ZIP，以及 `codex_change_log_20260605.md`。
- 复现实验：需要把官方赛题包中的原始数据放回本地 `demo/server/data/`。

本目录默认不提交 20260529 赛题原始数据。协作者本地需要准备：

```text
demo/server/data/
├── cargo_dataset.jsonl
└── drivers.json
```

注意：远端仓库根目录已有旧版 `demo/resources/official_data_20260509.tar.gz`，里面包含 0509 版本 D001-D010 共 10 个司机和对应货源，用于旧实验复现；它不等同于 20260529 二版/复赛数据。

公开调试包中当前只有 D001、D002 两个司机；正式评测/复赛使用的隐藏司机和新货源由赛方在评测环境注入，不会提前公开。不要为了拟合公开司机写死 `driver_id`、固定货源 ID 或固定日期规则。

推荐本地复现命令：

```bash
cd demo/server
pip install -r requirements.txt
export DASHSCOPE_API_KEY="your_api_key"
python main.py --simulation-days 1 --max-steps 8 --model-name qwen3.5-flash

cd ..
python calc_monthly_income.py
```

完整 31 天自测可以去掉 `--simulation-days 1 --max-steps 8`。结果会写入 `demo/results/`，该目录只用于本地分析，不需要提交到比赛平台，也不建议上传到公开仓库。

## 原始司机数据是否要提交

不建议把“10 个司机数据”或任何完整原始数据直接提交到公开 GitHub，也不要放进比赛 ZIP。

- 比赛 ZIP：复赛要求提交 `demo/agent/` 为主，数据由赛方评测环境提供，提交数据没有必要，还可能不符合规则。
- 公开 GitHub：除非确认赛方允许再分发，否则不要上传 `drivers.json`、`cargo_dataset.jsonl` 这类原始数据。
- 团队协作：如果确实要让队友复现，应让队友从官方赛题包获取数据，或在私有受控渠道共享，并保持本目录的路径约定 `demo/server/data/`。
- 代码策略：允许基于运行时 `get_driver_status` 返回的偏好做通用解析和 LLM 编译，不要把某几个公开司机的偏好硬编码成专用逻辑。

## 当前推荐提交包

平台已出分的当前最好包：

```text
submission_hidden_guard_20260605.zip
```

对应平台文件：

```text
1780641880699_submission_hidden_guard_20260605.zip
```

该包 2026-06-05 14:44:40 线上测评完成，分数 `-49585.3900`，偏好扣分 `86559.2500`。

另有一个经过完整 live API 本地仿真的最新版，适合作为后续继续改进的代码基线，但尚未记录平台出分：

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

以下为平台已完成测评的历史提交。平台文件名前缀为提交系统生成的 ID，本仓库内保留的是对应的本地 ZIP 文件。

| 平台文件名 | 本地对应 ZIP | 提交时间 | 状态 | 分数 | 偏好扣分 | 提示 |
| --- | --- | --- | --- | ---: | ---: | --- |
| `1780641880699_submission_hidden_guard_20260605.zip` | `submission_hidden_guard_20260605.zip` | 2026-06-05 14:44:40 | 测评完成 | -49585.3900 | 86559.2500 | - |
| `1780585172364_submission_selective_guard_20260604.zip` | `submission_selective_guard_20260604.zip` | 2026-06-04 22:59:32 | 测评完成 | -51920.5400 | 84899.2500 | ok |
| `1780503995670_submission_flash_qwen35_agent_only_20260604.zip` | `submission_flash_qwen35_agent_only_20260604.zip` | 2026-06-04 00:26:35 | 测评完成 | -129332.6600 | 188259.3600 | - |

2026-06-05 14:44:40 的 `submission_hidden_guard_20260605.zip` 是当前已记录线上最好分。相比 2026-06-04 22:59:32 的 `submission_selective_guard_20260604.zip`，平台分数提高了 2335.1500，但偏好扣分增加了 1660.0000。

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

若只看平台已出分结果，优先参考 `submission_hidden_guard_20260605.zip`；若继续做 live API 偏好编译方向，优先从 `submission_profile_compiler_livechecked_20260605_152621.zip` 开始。

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
