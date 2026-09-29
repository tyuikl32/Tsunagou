# FX5 追踪设计

## 复用三类记录

领域事件记录 Task/Contract/权限等事实；现有 diagnostic-events 记录传输/宿主失败；OpenTelemetry 只记录技术调用耗时与因果。后两者不重新计算任务真相。查询复用 bootstrap/container.py 的 query provider、shared_kernel/query_models.py 和 CLI。

dispatcher.py 当前 _record_evidence 仅转存已有 evidence，provider 返回 failed 而无失败 evidence 时遗漏。改为每次 attempt 状态转移都产生对应诊断，再附上实际观测；保存失败、直接抛错、超时和 unknown 都有终点记录。追加诊断与保存 attempt 走统一更新入口，不散落重复写入。

每条诊断固定 diagnostic_id、kind、occurred_at（源事实时间）、recorded_at（daemon 落盘时间）、project_id、actor_id、agent_id、command_id、task_id、attempt_id、message_id、wake_attempt_id、trigger_source、error_code；无关联字段为 null，不能猜值。保留 observed_at 作为实际宿主观测语义并统一 UTC 序列化，避免把读到旧事件的当前时间填成发生时间。当前旧格式无需迁移。

trigger_source 为 daemon_delivery/user_followup/developer_followup/unknown。只有该 provider 实际发起且返回/观察到的回合才能记 daemon_delivery；读到消息已 ACK 不能反推。追踪知道的来源，未知如实 unknown。外层宿主请求 ID 与真正 turn ID 区分，公开输出 digest/ref。

## 时间与耗时

复用 shared_kernel/time.py：内部 UTC 毫秒，公开 RFC3339 UTC 毫秒。测量同进程动作时使用 monotonic 计算 duration_ms，另存 wall-clock 起止。跨进程阶段用时间戳差并标记 elapsed，不把有时钟异常的负值修饰成成功耗时。

安装器记录 install_started_at/finished_at、connect_started_at/ready_at；Task 使用已有 begin/submit/review 事件；用户完成确认保持独立。投递等待、工作经过、审查等待分别展示。挂起重试按 Attempt 分段，不能把所有 Worker 并行时长相加当总工期。未实际记录的旧耗时为 null，不补造。

## 最小 OpenTelemetry

新增可选 telemetry 依赖组：opentelemetry-api、opentelemetry-sdk、opentelemetry-exporter-otlp-proto-http；实施时通过锁文件固定兼容版本。遵守现有 opt-in/local OTLP 约定。核心时间线不依赖它，关闭 tracing 仍有所有业务和失败记录。

新增 platform/telemetry.py，手工覆盖 command 执行、A2A 入站提交、outbox 投递、host wake RPC、接入/恢复五个边界。接收/传播有效 traceparent，将必要上下文保存到 outbox；后台新 span 使用 parent 或 Link 关联已结束的提交，不让一个 span 跨越任意长的用户等待。SDK API/Link 依据 [官方手工埋点](https://opentelemetry.io/docs/languages/python/instrumentation/)，OTLP 依据[官方 exporter](https://opentelemetry.io/docs/languages/python/exporters/)。

默认不抓取全部 HTTP、文件、prompt 或每次读取，不对每个函数打点，不增加常驻 LLM。配置 TSUNAGOU_OTEL_ENDPOINT 后仅允许本机 OTLP HTTP 端点；没有端点则不开 exporter。导出失败不回滚已成功业务事务。普通日志带 trace_id/span_id，权限判断不相信外来 trace ID。

实施细化：OTel API/SDK/OTLP HTTP exporter 锁定 1.45.0。既有 outbox 仅保存 payload_digest，没有 JSON payload；因此将 traceparent 与业务事件同事务持久化，投递通过已有 outbox.event_seq 关联 events.payload_json 恢复上下文。无需新增 outbox 列或重建本轮验收库。导出的 span 使用真实 SDK parent context；不把整个等待期撑成一个 span。

共享任务命令附带私信时，只裁去不可见的 ancillary changes，保留共享主事实；明确 evidence_refs 仍整体授权。诊断对非私信受众隐藏 message_id，U/main 可看脱敏故障概况；不能通过过滤器取得原本无权访问的引用。

验收使用本机临时 collector/测试接收器，保存脱敏 spans；不在产品中内置观测 WebUI或第二个协调数据库。不新增“必须先跑 OTel 才能开工”的门槛。

## CLI

保留 project history、task history、project diagnostics、audit event、checkpoint list/verify。扩展 diagnostics 的 --message-id、--task-id、--from、--to 过滤及 --json；复用当前授权和边界。agent list 来自 FX4。所有新增过滤参数同步 HTTP 查询模型和示例。

同库重启仍可查失败和最终状态；只读查询不触发 session 重连。真实 credential/epoch 变化仍记录。main 可看调度状态、失败类别、关联 task/message 的可见引用，不自动获得私信正文。数据导出先做同一可见性过滤。

## 实测补充：公开 Result 时间汇总

2026-09-28 实测发现，显式私信证据使完整 task.submit audit 行对 U 隐藏。此前将提交时间一并判为不可查，遗漏了已有 `/projects/{id}/results` 返回独立公开 Result 的 `created_at`。它由现有实体元数据与 Result 创建事务一起记录，不依赖读取私信事件。这是查询汇总缺口，无需改 audit 授权或新增持久化时间字段。

新增只读 `project timings PROJECT_ID [--task-id TASK_ID] [--json]`：复用已有 attempts、results 与分页完整的 project history HTTP 查询，按 Attempt 关联三者。开始时间使用可见 begin 事件；提交持久化时间优先使用实际可见 submit 事件，否则使用唯一匹配 Result 的 created_at 并明确来源 `result_created_at`；审查使用实际可见 review 事件。开始与提交来自不同事实时分别标注来源，不混用 Attempt.ended_at（它可能表示回收/取消/失败），不使用 updated_at 或查询当前时间补缺失。

没有 Result/时间元数据就保持 null；多个 Result 或矛盾时间不得挑一个伪装成功。只输出公开 ID、状态、UTC 时间、时间来源、经过时间及 unknown/clock_inconsistent；不输出 payload/evidence/private message refs。原 history/event/export 继续执行完整显式证据授权。查询无写入，幂等重放/重启不能更改已存 Result.created_at。

边界：新增纯读取时间汇总 helper、typed CLI 输出和命令；FX6 采集复用这个实际 CLI 输出并保留原 audit rows/count，不把补充 Result 时间伪装为已看见 submit 事件。协议命令目录、CLI 用户说明、查询说明和测试同步。无需新后台 API、数据库、迁移或权限放宽。独立只读 Worker 任务 7271e347-82ee-4bb4-8cfd-ef29e055cfa3 正在复核该口径；若发现真实不一致，先修订本节再实施相关分支。
