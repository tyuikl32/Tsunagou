# FX5 失败时间线与最小追踪

状态：in_progress；FX-R06，依赖 FX2、FX3、FX4。已有 PT 历史/审计/checkpoint 功能复用。核心诊断、HTTP 过滤和 SDK 埋点已实现；部署/接入计时与原 Desktop 联合实测由主会话继续验收，未宣布完成。

## 目标与证据

用户能用 CLI 回答谁在何时做了什么、哪里失败、由谁恢复，以及部署和工作的实际经过时间。本轮 provider failed 只在状态文件出现，诊断仅有 requested/presented；169 条 session.reconnect 淹没正常进展；OTel 尚无实现。

## 验收

| ID | 结果 |
| --- | --- |
| T1 | 每次请求、宿主接受、真实开始、处理和失败有对应发生时间及关联；provider 直接返回 failed 也必有失败诊断 |
| T2 | daemon 自动、用户跟进和开发工具跟进分开记录；后者不能把先前自动唤醒失败改成成功 |
| T3 | 部署起止、Worker 开始/提交、main 审查、用户确认分别可查；明确流程经过时间，不冒充纯编码时间 |
| T4 | 正常只读不更改领域事件/修订/业务时间；无实际变化不重连 session；失败拒绝仍可诊断 |
| T5 | 关键因果链具有实际 OpenTelemetry span 及 message/command/task/attempt 关联；不要求运行观测平台 |
| T6 | 时间含 UTC 时区；token、私信正文、原始 host 标识不泄露；无 token 用量时显示 unavailable |
| T7 | CLI 可过滤和导出当前可见数据，不能为 main 放开 Worker 私有收件箱；已有 query/checkpoint 回归通过 |

设计见 [design.md](design.md)，实施见 [implement.md](implement.md)。
