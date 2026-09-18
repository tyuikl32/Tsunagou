# 消息、收件箱与请求响应协议

> 核对日期：2026-09-17。
> 状态：已确认选择 A（逐接收者 obligation）和投递策略 A（保守 at-least-once）。

## 既有约束与参考

- 已确认三种顶层 kind：`notification`、`request`、`response`；路由在发送事务中展开为逐 Agent 不可变收件记录。
- 已确认投递里程碑：enqueued、leased、fetched、能力允许时 presented、显式 acknowledged/disposition，以及 deferred、expired、dead-letter。
- ACK 不替代 request 的结构化响应或领域命令；SSE/主动唤醒也不承担可靠投递。
- CloudEvents 对 `id/source/type/subject/time/data` 的分离适合作为 envelope 参考，但本系统还需要项目权限、recipient snapshot、response contract 和投递状态，因此不直接采用完整 CloudEvents 格式。

来源：

- [CloudEvents specification](https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md)
- [CloudEvents JSON format](https://github.com/cloudevents/spec/blob/main/cloudevents/formats/json-format.md)

## 响应聚合选项

| 选项 | 完成模型 | 优点 | 代价与风险 |
|---|---|---|---|
| A（推荐） | 路由时为每个 recipient 建 required/optional obligation；所有 required 有合法 evidence 后消息请求 satisfied，领域模块决定业务完成 | 覆盖契约全员接受和单主 Agent评估；消息层保持确定性；不会重复实现领域 quorum | 需要 owning module 将领域命令/event 回报为 satisfaction evidence |
| B | 消息层支持 `all/any/quorum/percentage` 通用聚合表达式 | 广播问询灵活；部分流程可直接复用 | 引入小型规则语言；成员变化、弃权、权限撤销和领域共识语义容易混乱 |
| C | 首个合法 response 关闭整个 request | 实现最简单；适合竞速/抢答 | 不适用于契约共识、多方审查；慢响应会被无意忽略，不能作为全局默认 |

## 推荐 A：不可变 Message

`Message` 创建后不修改；投递与请求完成使用独立聚合。

| 字段 | 约束 |
|---|---|
| `message_id`, `schema_version`, `project_id` | UUIDv7、协议版本和项目 |
| `kind`, `topic`, `payload_schema` | 三种 kind；版本化 topic；schema URI + sha256 hash |
| `sender` | 服务器写入 principal/agent/session/authority epoch snapshot |
| `subject_refs[]` | 类型化 task/contract/resource/operation 等引用 |
| `correlation_id`, `causation_id`, `in_reply_to` | 链路、因果和 response 关联；按 kind 约束是否必填 |
| `priority` | `critical/high/normal/low`，默认 normal，只影响投递选择 |
| `created_at`, `not_before`, `expires_at` | 服务端时间；not_before/expires 可选且受策略上限 |
| `summary` | 可选、受长度限制的人类摘要，不能替代 payload |
| `payload` | 按 topic/schema 验证的 JSON，不允许未声明二进制 |
| `response_contract` | 仅 request：允许 evidence、response schema、deadline 和 timeout event |

- topic 使用反向域无关的稳定 dotted name，如 `risk_assessment.requested.v1`、`contract.acceptance_requested.v1`；major 进入 topic，minor additive 由 schema version 表达。
- payload canonical JSON 最大 256 KiB，summary 最大 4 KiB；更大正文、diff、日志或 artifact 通过受权限控制的 resource reference 提供。
- Message 保存 immutable sender snapshot，但每次 fetch/response/ack 仍重新验证当前授权；历史 sender 权限不自动延续。

## RoutingSnapshot 与 InboxEntry

- sender 提交 route intent：direct agent IDs、subscription topic 或 impact subject。routing service 在发送事务中验证权限并展开 recipient Agent IDs。
- 每个 recipient 生成不可变 `RoutingSnapshot`：recipient agent、route kind/basis、subscription/policy revision、permission decision ID、`response_required` 和创建时 capability snapshot ID。
- 同一消息/recipient 最多一个 `InboxEntry`，数据库唯一键 `(message_id, recipient_agent_id)`；多个路由命中合并 basis，不重复投递。
- 角色地址（如 current main Agent）在发送时解析为具体 agent ID；authority 换届不改写历史收件人。需新主 Agent处理时由领域事件创建新消息。
- 后加入订阅者不自动收到历史；显式 replay 创建新 message 或带 `replay_of` 的新 RoutingSnapshot，不能伪造原 enqueued 时间。

InboxEntry 保存 `inbox_entry_id`、message/recipient、state/revision、enqueued/available 时间、milestone timestamps、delivery counters、deferred_until、终态 disposition/reason 和 dead-letter 摘要。

## 投递状态与 attempt

状态机：`available -> leased -> fetched -> acknowledged`，并允许 `available/fetched -> deferred -> available`，以及从非终态进入 `expired` 或 `dead_letter`。

- 每次领取创建不可变 `DeliveryAttempt`，包含 attempt ID、bridge/session、lease ID/expiry、开始/结束、outcome/error classification 和可选 host receipt。
- `leased` 只表示 bridge 获得限时投递权；lease 过期可重投同一 message/inbox entry。bridge 必须以 message ID 去重。
- `fetched` 只证明 bridge/host 获得内容。`presented_at` 是可选 milestone，不是所有适配器都能证明，也不作为单独主状态。
- ACK disposition 固定为 `handled`、`rejected`、`superseded`；superseded 必须引用替代 message/evidence，rejected 必须提供稳定 reason code。ACK command 幂等且不能回退。
- defer 是单独动作，不是成功 ACK；必须给 `deferred_until` 且不晚于消息 expiry/项目上限。到期后回到 available 并保留历史 attempt。
- expiry 来自业务 deadline；dead letter 表示超过投递重试策略或持续宿主错误。两者不删除 message，也不会自动把所属 Task 标为失败。

## ResponseContract 与逐接收者 obligation

request 的 response contract 包含：

- `allowed_evidence[]`：每项为 `response_message` 或已登记的 `domain_event`，并给出 topic/event type、schema URI/hash。
- `deadline_at`：服务器绝对时间；不得晚于 message expiry。
- `timeout_event_type`：到期时由消息模块发出的稳定事件，owning module 决定任务/契约后果。
- routing snapshot 为每个 recipient 固化 `required` 或 `optional`；未显式标记时 direct recipient 默认 required，notification 没有 obligation。

每个 required recipient 建 `ResponseObligation`，状态为 `pending`、`satisfied`、`expired`、`waived`、`superseded`：

- response message 必须 `in_reply_to` 原 request、sender agent 等于 obligation recipient，并通过允许 topic/schema 验证。
- 合法领域命令完成后，owning module 在同一事务写入其 domain event，并通过公开端口登记 `(obligation_id, evidence_event_id)`；消息模块不读取领域表猜测结果。
- 所有 required obligations 为 satisfied/waived 时，request 进入 `satisfied` 并发事件；optional obligation 不阻塞。业务对象是否完成由 owning module 再按自己的状态机判断。
- waiver 必须由 owning module 的显式规则或用户权限命令产生，并记录理由；主 Agent不能用通用消息 API跳过契约所需参与者。
- Agent succession 自动把 predecessor 的全部 pending obligations 终结为 `superseded`，并为 successor 建立关联 replacement obligation、RoutingSnapshot 和 InboxEntry。replacement 继承 response contract 与原 deadline；旧项保存 `superseded_by_obligation_id`，不计作 waived/satisfied。
- predecessor 对 superseded obligation 的迟到 response 可保存为历史 evidence，但不满足 replacement；successor 必须以自身身份提交合法 evidence。契约等领域对象因参与者变化产生的版本后果由 owning module 状态机处理。
- deadline 到达时 pending obligation 变 expired，请求进入 `timed_out` 并发 timeout event。迟到 response 可保存并标记 late，但不自动重开或满足已关闭 obligation。
- ACK 与 obligation 完全独立：`handled` ACK 可以没有有效 response；合法 response 也不会自动替 Agent ACK 收件项。

## API 与工具轮廓

- `GET /api/v1/projects/{project_id}/agents/me/inbox`：签名 cursor 列表，默认 available/deferred-due 优先。
- `POST .../inbox/{entry_id}:lease`、`:fetched`、`:presented`、`:acknowledge`、`:defer`：均使用 command ID/revision 语义。
- `POST /api/v1/projects/{project_id}/messages`：授权系统模块/用户发送；普通 Agent只能使用 capability 允许的 topic/route。
- `POST .../messages/{request_id}:respond`：创建不可变 response message并原子登记 evidence。
- MCP common baseline 暴露 `inbox_list`、`inbox_fetch`、`inbox_acknowledge`、`inbox_defer`、`message_respond`；主动 push 只是 bridge enhancement。
- 业务工具如 `contract_accept` 直接执行领域命令并由系统登记 evidence，不要求 Agent再发送一份重复 response message。

## 投递策略选项

| 选项 | 策略 | 优点 | 代价与风险 |
|---|---|---|---|
| A（推荐） | at-least-once 领取；fetched 前失败可重投，fetched 后不自动重复注入正文，仅提示未处理计数 | 避免重复污染模型上下文；离线不丢消息；符合 ACK/response 分层 | fetched 但宿主未真正呈现时，要依赖 presented 能力、轮询和会话边界提醒 |
| B | 在 ACK 或 response 前按退避持续重新推送正文 | 更积极地促使 Agent 看见消息 | 宿主无法精确证明可见时会反复注入；可能导致重复响应、token 浪费和注意力干扰 |
| C | 只允许显式 inbox pull，不做主动 push/wake | 行为最可预测；适配器最简单 | 失去具备唤醒能力宿主的价值；任务切换前可能长期看不到紧急 request |

## 推荐 A：领取、批量与背压默认值

- delivery lease 60 秒，bridge/session 每 15 秒可续租；单次连续占有最多 2 分钟。超过后若仍未 fetched，旧 attempt 记为 lease_expired 并回到 available。
- batch lease 默认 10 条、最大 20 条，且单批 canonical payload 总量最大 1 MiB；达到任一上限即截断。每个 Agent session 最多 20 个 leased entries。
- 原子领取按 effective priority、available_at、enqueued sequence、message ID 排序。每等待 5 分钟提高一个 effective priority level，最高到 high；只有显式 critical 仍高于 aging 项。
- response deadline 早于普通 notification，并只影响相同 effective priority 下的顺序；排序绝不改变权限或 obligation 语义。
- bridge 取得正文后立即、显式提交 fetched；宿主支持注入回执时随后提交 presented。不能把“HTTP 返回了 message”自动记录成 presented。

## 重投、提醒与 dead letter

- fetched 前的 transient transport/session failure 结束当前 DeliveryAttempt，使用与 Job 相同的 full-jitter 公式（1 秒起步、60 秒封顶）重新 available。
- transient push/wake 失败不会仅因次数进入 dead letter；离线 Agent 的 inbox 仍持久存在。连续 5 次 push 失败后抑制该 session 的主动 push 5 分钟，期间继续允许 pull/SSE。
- non-retryable protocol/schema error、adapter 明确拒绝该必需 topic/capability，或管理员确认永久不可投递时进入 dead_letter；必须记录稳定 reason code 和最后 capability snapshot。
- 一旦 fetched，系统不自动再次向同一或后续模型回合注入正文。SSE 和会话连接/任务边界只提示未 ACK 数、最高优先级和最早 deadline，Agent 再通过 inbox_fetch 读取。
- defer 到期会重新 available，因此允许再次推送正文；显式 `redeliver` 也可创建新 DeliveryAttempt，但只允许 recipient、自身 owning module、主 Agent权限策略或用户触发，并要求 reason。
- presented 但未 ACK、fetched 但未 presented 都保持当前状态到 ACK/defer/expiry。普通消息没有默认“处理超时”；request 使用自身 response deadline，项目可另设 notification expiry 上限。
- `expired` 和 `dead_letter` 都产生审计/领域信号给 owning module；不自动 ACK，也不自动将 request obligation 标为 satisfied。

## 参考取舍

- SQS visibility timeout、Azure Service Bus Peek-Lock 和 RabbitMQ manual acknowledgements 都体现“限时占有 + 显式确认 + 可能重复”的基本模型。
- 这些系统也强调幂等消费与有界 in-flight/prefetch。Tsunagou 不照搬 broker API，而是用 message ID、DeliveryAttempt 和稳定领域命令实现同样的故障边界。

来源：

- [Amazon SQS visibility timeout](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html)
- [Azure Service Bus transfers, locks and settlement](https://learn.microsoft.com/en-us/azure/service-bus-messaging/message-transfers-locks-settlement)
- [RabbitMQ consumer acknowledgements](https://www.rabbitmq.com/docs/confirms)

## 后续细化

- 每个 topic 的 sender capability、route policy、payload/response schema 和默认 deadline。
- Message/Inbox/Attempt/Obligation 的完整表、索引与 event 列表。
