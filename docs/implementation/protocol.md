# HTTP、MCP、消息与版本契约

## Schema 与版本

唯一 DTO 源：`protocol/schemas/<module>/*.schema.json`，JSON Schema 2020-12。每个 schema 使用稳定 `$id`、完整 required、枚举、限制、可空定义与描述；禁止远程 `$ref`，禁止不受控任意 JSON；代码生成支持的 subset 由 T03 lint 明确验证。DTO PascalCase，字段 snake_case，领域 command 为 `module.action` 的小写点分名字，事件为 snake_case。

生成 Python 到 `src/tsunagou/generated/protocol/`，TS 到 `packages/protocol-ts/src/generated/`；FastAPI 导出 `protocol/openapi/v1/openapi.json`，HTTP 类型生成到 bridge-sdk。每份生成物包含 schema digest/生成器版本，无当前时间；同输入字节稳定。严禁手改生成物。

## A2A 边界

初版设计要求 Agent 之间通过 A2A 协商；daemon 当前提供一个独立的本机 JSON-RPC adapter。它复用同一 authenticator、command dispatcher、项目范围和持久化消息/任务事实，MCP bridge 不等于 A2A 实现。端点、Agent Card、Message/Task 映射、幂等、错误和 wake 能力声明见 [A2A 边界实现](a2a-boundary.md)。

协议协商支持当前 N 与 N-1，未知 bundle digest 拒绝。`protocol_version`、`schema_bundle_digest`、`shared_format_version`、Alembic revision 是四个独立维度，不按字符串猜兼容性。未来 shared format 默认只读诊断，不能自动降级覆盖。

## 认证与入口

- HTTP 地址为 `127.0.0.1` 随机端口；endpoint manifest 保存 instance ID、PID、port、启动时间，不含token。首发关闭CORS、无Cookie，不监听LAN或`0.0.0.0`。公共业务前缀 `/api/v1/projects/{project_id}`（下文 P）。daemon `/api/v1/health` 只返回存活/版本，不暴露项目列表。
- Bearer session token 识别 agent_session；另一个独立 control token 识别 user_control。不得通过请求体、query、MCP 参数或环境变量提交 actor/token。TLS/OAuth/浏览器登录不在首发。
- header：`Tsunagou-Protocol-Version`、`Tsunagou-Schema-Digest`、Agent 的 `Tsunagou-Session-Id`、`Tsunagou-Connection-Epoch`、`Tsunagou-Runtime-Epoch`。服务端验证 header 与 token 绑定，不信 header 自报身份。
- 主权限写入附 `expected_authority_epoch`；Attempt 执行附 `attempt_id,expected_execution_epoch`。权威对象不能靠路由 ID 绕过 lineage/runtime 校验。
- MCP 入口 `P/mcp`，一个项目共享服务；每连接单独鉴权、绑定 HostSession/connection epoch。HTTP 的 MCP session ID 是传输句柄，不替代业务身份。stdio-only 宿主用逐会话薄转发器。
- 控制端点只给 CLI/外部本机控制客户端，不在 Agent MCP tools 中发布。工具名把点转双下划线，如 `task__claim`；与领域命令一对一，查询工具使用 `query__*`。

HTTP与MCP在传输适配后进入同一command dispatcher；共享语义不要求MCP handler经网络回调本机HTTP。`P/events:stream`是业务高水位提示，与MCP传输内部SSE分开。MCP协议规范版本、Tsunagou协议版本与baseline profile也分别协商/记录。

## Mutation envelope

REST body：`{command_id,protocol_version,schema_bundle_digest,expected_authority_epoch?,attempt_id?,expected_execution_epoch?,payload}`。路径中的主 aggregate revision 以 `If-Match: "rev-7"` 提交；MCP 使用 `expected_revision:7`。转换后内部 TypedCommand 一致。create 没有主对象 revision；多对象写在 payload 放精确 `expected_revisions`（id→revision）。无条件更新已有 aggregate 返回 428。

header与body都声明protocol_version/schema_bundle_digest时必须一致，否则400 malformed_request。其他epoch/attempt字段按该命令Schema固定唯一位置：X执行上下文位于envelope，B协调命令中catalog明确列入payload的attempt/expected_execution_epoch仍在payload，不同时填两份。T03通过规范化映射得到同一内部上下文；相互冲突的重复字段直接拒绝，不能按某一来源静默覆盖。

响应：`{command_id,result:{...},revisions:{id:revision},event_seq,operation_id?,materialization:{status:pending|caught_up|failed,through_event_seq},replayed:boolean}`。普通变更 200，创建 201，有外部未完成 Operation 返回 202；每项在命令目录按 result 类型确定。幂等重放保持第一次业务 result，replayed=true；读取 Operation 获得后续进度，不在重放响应中伪造新结果。

唯一幂等键 `(project_id,principal_id,command_kind,command_id)`。hash 包含规范命令输入、目标、前置版本；排除 token、传输 header、连接代次与重试计数。相同语义 REST/MCP hash 相同。幂等条目与相应事件/checkpoint 索引保留，不按普通日志 30 天清理。

### PT2 凭据命令的交付例外

凭据命令的认证响应是私有交付通道；SQLite 和普通查询只保留安全 receipt。bridge 原子保存后调用 `POST /api/v1/credential-deliveries/{delivery_ref}/ack`，空 body 或 `{}`，由原 ticket 签发者或交付对应的当前 session/epoch 认证。ACK 不发布为 MCP 取密工具；引用不是授权。响应统一 `Cache-Control: no-store`，所有交付时间为 RFC3339 UTC 毫秒。稳定命令重放、恢复窗口、ACK 丢失与旧库迁移的完整约定见 [凭据交付](credential-delivery.md)。

## Error envelope

HTTP 使用 RFC 9457 `application/problem+json`：`type,title,status,detail,instance` 加 `code,command_id?,current_revisions?,blockers?,remediation?,retry_after_ms?`。detail 不是客户端控制输入。MCP tool error 的 structuredContent 保存同一 problem 对象；认证握手错误由传输处理。

| HTTP | code 类别 | 行为 |
|---|---|---|
| 400 / 413 / 422 | malformed_request / payload_too_large / schema_validation_failed | 修输入，不自动重试 |
| 401 | authentication_failed / session_ended | 停止业务调用，恢复或重新接入 |
| 403 | capability_denied / relationship_denied / scope_denied / user_only | 不用别的 transport 绕过 |
| 404 | not_found | 不泄露其他项目/私信是否存在 |
| 409 | idempotency_conflict / invalid_transition / stale_epoch / resource_conflict / condition_stale | 拉取最新状态后构造新命令 |
| 412 / 428 | revision_conflict / revision_required | 更新版本；不得无条件覆盖 |
| 423 | action_blocked | 返回全部适用 blocker 与处理角色 |
| 429 / 503 | queue_capacity / temporarily_unavailable | 受控退避，原 command_id 不变 |

## Query、分页与事件

GET 单对象返回 `ETag: "rev-N"`。共享协调对象对就绪项目成员可读；inbox、私信正文、绝对路径、ceiling 与敏感 evidence 单独授权。

列表 `{items,next_cursor,snapshot_event_seq}`；limit 默认 50、最大 200；keyset 默认 `(created_at,id)` 升序，可注册固定排序，不支持任意 SQL。HMAC cursor 有效期 15 分钟、最长 2 KiB，绑定 principal/project/lineage/query/filter/sort；换 principal 或 filters 失效。cursor 不保证跨页面长事务一致，客户端按 revision 去重；要稳定导出使用 checkpoint。

### PT5 审计时间线与持久化查询契约

`GET P/audit`、`GET P/{id}/history` 和 `GET P/tasks/{task_id}/history` 使用已认证的 user_control 或当前项目 Agent session，并共享 [AuditPage Schema](../../protocol/schemas/queries/audit-page.schema.json)。CLI、HTTP 通过同一 query dispatcher 和 `AuditPageModel`；生成 OpenAPI 的命令为 `uv run python tools/codegen/generate_openapi.py`，实际产物是 `protocol/openapi.json` 和安装包内同名镜像。`GET P/{id}/history/export` 额外包装为 `tsunagou.audit-export.v1`，包括 `source.project_id`、`source.lineage_id`、`exported_at`、`projection_version`、`as_of_event_seq` 和当前可见事件。

请求参数为 `limit`（1–200，默认 50）、`cursor`、`from`、`to`、`actor_ref`、`subject_ref`。时间输入必须带时区；返回统一为 UTC 毫秒 `.sssZ`。首屏冻结 `as_of_event_seq` 高水位，`snapshot_event_seq` 是值相同的兼容字段。按 `event_seq` 升序翻页，服务端签名游标绑定项目、lineage、当前认证身份、过滤条件、排序、页长和高水位；新事件留待重新查询。游标过期或 daemon 重启后重新查询，不把游标当凭据，也不接受数字偏移替代它。

事件中 `event_id/event_seq` 是规范字段，`source_event_id/source_event_seq` 是兼容别名。`changes` 仅描述相关实体的状态和版本前后值、创建/更新时间；不附私信正文、秘密或状态快照。`revision_source=domain` 表示领域拥有的 CAS 版本，`audit_observation` 表示该实体没有领域 CAS 时的审计观察次数，不能拿后者提交业务写入。`actor_session_id` 是已登记的运行时会话 ID，不公开原始宿主 conversation 内容。

`GET P/audit/events/{event_id}` 返回同一 `AuditEventModel`，按 event 所属 project、lineage 和可见性重新授权；`include_evidence=false` 只省略证据引用，不改变事件身份。任务历史以 task、attempt、result、preflight、progress、workspace、report、contract 和可见 message 的已持久化引用组成关联集合，不把同项目无关事件加入结果。私信关联事件仍仅供发送者/收件人查询；main 和 user_control 不因此成为收件箱超级用户。领域读取失败或无变化的查询不新增事件、实体更新时间或版本。未知旧时间保持 `null`，不落入有界时间筛选；没有可靠旧证据时 `evidence_level=null`，不得自动声称 `system_verified`。

`GET P/checkpoints/{digest}/verify` 和 `GET P/{id}/checkpoints?verify=true` 是只读 checkpoint 投影：前者返回 `CheckpointVerificationModel`（manifest 内容摘要、through_event_seq、verified_at、允许的本地 heads/tags Git anchor），后者返回 current 指针与 `CheckpointSummaryModel` 列表。没有 Git 仓库时校验仍可成功，`git_anchors=[]`；remote ref、reflog、裸 OID 或内容不匹配不会被接受。两者不产生 event、operation 或 revision。

`GET P/{id}/diagnostics` 返回独立的 `DiagnosticPage`：`diagnostic_id`、`kind`、`agent_id`、`message_id`、`wake_attempt_id`、`evidence_digest`、UTC `observed_at` 和白名单 `details`。它读取 `.tsunagou/local/diagnostic-events.json`，不是 SQLite domain audit；稳定 delivery 重放不追加记录，重启造成的不可观察状态只追加 `wake_unknown`。诊断查询可由 U 或当前 B session 读取，不能用它反推隐藏私信正文或宿主 turn 内容。

事件查询 `P/events?after_seq=N&limit=...` 返回脱敏可见事件和 `through_event_seq`；过滤不能泄露隐藏消息。SSE `P/events:stream` 只推高水位提示 `{event_seq,inbox_revision,blocker_revision}`，连接后先 REST sync。15 秒 comment keepalive、30 秒 send timeout；断流重连不保证 replay，无单独 SSE replay 表。

## 消息 DTO

当前 `message.send` 输入为 `{recipient_agent_id,summary,kind?,subject_ref?,payload?,priority?,response_contract?,in_reply_to?}`，发送者由认证身份生成。kind 是开放字符串，默认 `message`；summary 非空且最多4096字符，序列化 payload 最多256KiB。一次只产生一个固定收件人的消息，不因主 Agent 更换自动泄露给继任者。输入不使用旧 recipient_ids 或 artifact_refs；较大内容使用已有附件领域能力。

`inbox.claim` 返回 `{messages,count}`，每项包含 message_id、sender_agent_id、recipient_agent_id、kind、subject_ref、summary、in_reply_to、payload_digest，以及存在时的 response_obligations；不含正文。`inbox.fetch({message_id})` 对原收件人返回同一视图和完整 payload。main 不因此获得其他 Worker 的私信。

`response_contract={required?:boolean,schema?:object}`：required 默认 true；schema 为回复 payload 的 JSON Schema。回复先 `message.send` 回原发送者并指定 in_reply_to，再 `message.respond({obligation_id,response_message_id})` 关联已存在的回复、校验回复发送身份/原消息关联/可选 schema 并关闭义务。两者是独立命令，不是一个原子操作；不能将 response_payload 直接交给 respond。ACK、同意契约、业务响应仍是不同事实。

当前内部 Delivery 记录 message_id、recipient_agent_id、status、attempts、lease_until、available_at、presented_at、acked_at 和 presentation_evidence，不把 delivery_lease_id 作为公开消息标识。claim、fetch、presented、ACK 是不同观察；presented 输入证据字段当前可省略且不做强度证明，ACK 当前也不要求已 presented。这是实现边界记录，不将其描述成已具有强展示证据的机制；唤醒失败不决定业务终态。

## 附件

blob 默认写 `.tsunagou/local/artifacts/sha256/<prefix>/<hex>`。先由拥有领域创建受限 upload intent（引用目标、visibility、最大字节数），二进制 PUT 上传，finalize 核对长度和 SHA256，再把 ArtifactRef 附加领域对象；读取必须授权该领域引用，知道 hash 不够。

建议默认单附件上限 64 MiB、最大 256 MiB，由用户项目 policy 设定；上传临时文件有可清理的过期状态，已 final 的 blob 首发无自动 GC。共享 checkpoint 只带显式 promote 的 project_shared 附件。私信、凭据、宿主配置不因“归档”自动共享。

## 固定限制与工程补全

通用 JSON request 默认 1 MiB；字符串可读摘要默认 4 KiB；批量 mutation 默认最多 100 对象，过大拒绝而非部分提交；identifier 最大 128 ASCII，路径最多 256 segments、每段 255 UTF-8 bytes（同时受 OS 限制）。这些是本次工程默认值，由版本化配置与 Schema 同步调整，不是新增用户回答。
