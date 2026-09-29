# FX5 实施进度

2026-09-28。状态：in_progress。开发 helper 实施，不作为运行时 Agent/A2A 证据。

## 本轮代码

- hostwake 的初始请求、每次状态变化、直接 failed、抛错、restart unknown、合并投递都进入诊断更新入口。新增发生/落盘/观测时间、触发来源和 command/task/attempt 关联。保留先前失败；inbox.presented 只增加 unknown 来源观测。
- 所有新时间为 UTC RFC3339 毫秒。较早的本轮 journal 缺失字段只在读取投影中置 null/unknown；不迁移旧库、不把当前时刻填成旧发生时间。
- 任务 submit 附带私信时，共享任务事实可查；私信 ancillary changes 不公开。显式私有 evidence_refs 仍整体授权。history、单事件与 export 复用该处理。
- diagnostics HTTP 增加 message_id/task_id/from/to，用户/main 只得脱敏概况，私信引用仍按受众过滤；不创建领域事件。CLI 参数由主会话接入，当前 help 已核对。
- 可选 telemetry extra 锁定真实 OTel 1.45.0，五个边界手工埋点。有效 traceparent 经事件同事务保存，后台 outbox 从 event_seq 恢复；没有新增 outbox 列。端点仅本机 HTTP，默认关闭，不抓 payload、prompt、原始宿主 ID 或异常正文。
- tools/dev/collect_acceptance_trace.py 接收实际 OTLP protobuf，输出允许的 span 字段。token_usage=unavailable。用户操作和字段说明见 docs/overview/diagnostics-and-tracing.md。

## 验证与发现

集中回归覆盖 hostwake、原 Desktop provider fixture、PT audit 权限、history CLI、协议和新增 failure timeline/telemetry。最新机器记录见 research/validation.json 与 focused-tests.log；2026-09-28T13:49:19.960Z 的 JUnit 统计为 93 项通过、0 跳过。mypy 73 源文件、Ruff、架构检查、99 command/115 schema 校验及 docs 校验通过。

新增用例验证 failed 无 evidence、异常正文 sentinel、失败后 presentation 不改状态、重启保留诊断、源时间与观测时间分离、跨时区过滤、只读无事件、共享 submit 仍可见、真实 SDK→本机 OTLP 解码、五个产品边界及 executor 跨线程 outbox parent。

测试发现并修复两项实现问题：原草稿试图裁去 explicit private evidence，违背原权限契约，已收窄为仅 ancillary changes；SDK 1.45 新根 span 的 trace flags 可含 03，原 00/01 白名单会丢失关联，已按两位十六进制字段校验并通过持久化因果测试。

## 待联合验收

- T1/T2/T5：代码与真实 SDK 接收测试通过；仍须在真实原 Desktop 通信链采集 span/诊断，明确自动唤醒与用户/开发者跟进，不能用 fixture 代替。
- T3：安装/接入计时、两名 Worker begin/submit、main 审查、用户确认和经过时间由主会话整合/实测；新增 `project timings` 已实测 begin/submit/review、来源和工作/审查经过时间，不能把测试墙钟当作 LLM 编码时间。现场新版 daemon 加载回归仍待完成。
- T4/T6/T7：机械/权限回归通过；需要升级当前 daemon 后用实际项目 CLI 查询失败到恢复，导出同一可见投影。
- 未改 CLI 安装/daemon 逻辑、handlers.py 或主任务指针；未安装依赖（仅 uv lock，主会话串行 sync）；未操作 live daemon/对话，未 commit。

外部依据：[SDK 手工埋点](https://opentelemetry.io/docs/languages/python/instrumentation/)、[OTLP exporter](https://opentelemetry.io/docs/languages/python/exporters/)。本机五边界测试产生真实 SDK span，但原 Desktop 验收仍不能据此标为已完成。

## 原始 Worker submit 在 U/CLI history 中的可见性核对 — 2026-09-28T15:01:54Z

核对原 parser task `74f34f37-f3df-44ef-a5f0-8991de6243b7`：真实 `task.submit` 已落 SQLite，event_seq=79、发生时间 `2026-09-28T14:10:33.066Z`；OTLP `command.execute` 也记录 submit 被接受。当前安装 CLI `task history` 的主历史视图没有此事件，CLI `audit event` 对对应事件返回 `audit_event_access_denied`。

原因不是事件未写入、游标跳过或 CLI 参数缺失。该 submit 事件的显式 `evidence_refs` 包含一条 Worker 发给 main 的 recipient-only 消息引用。现有 `can_read_event` 对显式证据要求整体可读；CLI 使用 user-control 身份，既非该消息发送者也非收件人，因此按既定规则隐藏整个事件。main 可以作为收件人读取该消息；user-control 不因此成为私信超级用户。已有规范 `.trellis/spec/backend/logging-guidelines.md` 明确规定显式 evidence refs 必须整体授权。

本轮没有放宽权限、删改事件或从 review 时间推算 submit。早期 FX6 快照按当时仅审计可见投影保留 `submitted_at=null`；新增 `project timings` 改用同一公开 Result 的 `created_at` 作为独立实体事实，并标记 `submitted_source=result_created_at`，可见 submit_events 仍为 0。若私信只是 `task.submitted` 通知，应继续留在私信/ancillary 通道；没有把隐藏证据引用公开给 U。
