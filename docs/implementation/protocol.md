# HTTP、MCP、消息与版本契约

## Schema 与版本

唯一 DTO 源：`protocol/schemas/<module>/*.schema.json`，JSON Schema 2020-12。每个 schema 使用稳定 `$id`、完整 required、枚举、限制、可空定义与描述；禁止远程 `$ref`，禁止不受控任意 JSON；代码生成支持的 subset 由 T03 lint 明确验证。DTO PascalCase，字段 snake_case，领域 command 为 `module.action` 的小写点分名字，事件为 snake_case。

生成 Python 到 `src/tsunagou/generated/protocol/`，TS 到 `packages/protocol-ts/src/generated/`；FastAPI 导出 `protocol/openapi/v1/openapi.json`，HTTP 类型生成到 bridge-sdk。每份生成物包含 schema digest/生成器版本，无当前时间；同输入字节稳定。严禁手改生成物。

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

事件查询 `P/events?after_seq=N&limit=...` 返回脱敏可见事件和 `through_event_seq`；过滤不能泄露隐藏消息。SSE `P/events:stream` 只推高水位提示 `{event_seq,inbox_revision,blocker_revision}`，连接后先 REST sync。15 秒 comment keepalive、30 秒 send timeout；断流重连不保证 replay，无单独 SSE replay 表。

## 消息 DTO

`Message={id,kind:notification|request|response,sender_agent_id,subject_ref,summary,payload,payload_digest,artifact_refs[],routing_snapshot_id,created_at}`。summary UTF-8 ≤4 KiB，整个消息 payload ≤256 KiB；更大内容转附件。发送者由身份生成。路由收件列表发送时固化，不因主 Agent 更换自动泄露给继任者。

request 增 `response_contract={required_recipients[],optional_recipients[],response_schema_ref?,deadline_at?}`；response 增 `in_reply_to,obligation_id,response_payload`。发送 response 与满足对应 obligation 同事务。ACK、同意契约、业务响应分开命令。

`Delivery={message_id,recipient_agent_id,status,pull_lease_id?,fetch_at?,presented_at?,ack_at?,defer_until?,attempt_count}`。leased/fetched/presented/acknowledged 是不同证据；fetched 后不反复自动塞全文，可提醒待办数和引用。正式 wire status 详见 agents 模块，终态不得靠 push 失败次数判定。

## 附件

blob 默认写 `.tsunagou/local/artifacts/sha256/<prefix>/<hex>`。先由拥有领域创建受限 upload intent（引用目标、visibility、最大字节数），二进制 PUT 上传，finalize 核对长度和 SHA256，再把 ArtifactRef 附加领域对象；读取必须授权该领域引用，知道 hash 不够。

建议默认单附件上限 64 MiB、最大 256 MiB，由用户项目 policy 设定；上传临时文件有可清理的过期状态，已 final 的 blob 首发无自动 GC。共享 checkpoint 只带显式 promote 的 project_shared 附件。私信、凭据、宿主配置不因“归档”自动共享。

## 固定限制与工程补全

通用 JSON request 默认 1 MiB；字符串可读摘要默认 4 KiB；批量 mutation 默认最多 100 对象，过大拒绝而非部分提交；identifier 最大 128 ASCII，路径最多 256 segments、每段 255 UTF-8 bytes（同时受 OS 限制）。这些是本次工程默认值，由版本化配置与 Schema 同步调整，不是新增用户回答。
