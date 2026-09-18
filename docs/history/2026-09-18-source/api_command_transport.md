# REST、MCP 与内部命令信封映射

> 核对日期：2026-09-17。
> 状态：已确认选择 A（传输原生投影）。

## 标准核对

- RFC 9110 定义 `ETag` 作为 representation validator；`If-Match` 对状态变更请求使用强比较，用于避免 lost update，条件失败通常返回 `412 Precondition Failed`。
- RFC 6585 的 `428 Precondition Required` 用于要求客户端提交条件请求，并应说明如何正确重试。
- RFC 9457 使用 `application/problem+json` 表达机器可读问题；客户端不应从人类 `detail` 文本解析业务信息，应使用扩展字段。
- IETF 的 `Idempotency-Key` 在核对日仍是 expired 的 draft-07，IESG 未发布为 RFC。因此 v1 不把该 header 作为必需协议；已确认的 UUIDv7 `command_id` 继续承担应用幂等身份。

来源：

- [RFC 9110: If-Match](https://www.rfc-editor.org/rfc/rfc9110.html#name-if-match)
- [RFC 6585: 428 Precondition Required](https://www.rfc-editor.org/rfc/rfc6585.html#section-3)
- [RFC 9457: Problem Details for HTTP APIs](https://www.rfc-editor.org/rfc/rfc9457.html)
- [IETF Datatracker: Idempotency-Key draft](https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/)

## 选项

| 选项 | 线协议 | 优点 | 代价与风险 |
|---|---|---|---|
| A（推荐） | 传输原生投影：REST 用 ETag/If-Match，MCP 用 `expected_revision` 字段；均映射到同一内部 envelope | REST 符合 HTTP 并发语义；MCP 保持自描述；应用层仍完全统一 | 两种传输字节表示不同，需 conformance fixtures 证明映射等价 |
| B | REST 与 MCP 都发送完全相同 JSON envelope，revision 只在 body | codegen 和抓包最直观；无映射差异 | 放弃标准 HTTP 条件请求、412/428 和缓存验证器；REST 客户端生态利用较差 |
| C | REST 同时强制 body `expected_revision` 与 `If-Match` | 标准 header 和统一 body 都保留 | 同一事实重复；代理/SDK 漏传一个就失败；两处不一致增加无价值错误分支 |

## 推荐 A：内部命令信封

应用层始终接收同一个不可变 `CommandEnvelope[T]`：

```json
{
  "schema_version": "1.0",
  "command_id": "019...",
  "project_id": "019...",
  "principal_id": "019...",
  "agent_id": "019... or null",
  "expected_revision": 7,
  "authority_epoch": 3,
  "request_context": {
    "transport": "rest",
    "session_id": "019...",
    "trace_id": "..."
  },
  "payload": {}
}
```

- `project_id`、principal/agent/session 和 transport context 由鉴权与路由层写入，不能信任客户端 body 中的同名字段。
- `expected_revision` 与 `authority_epoch` 按命令 schema 要求；不需要时必须省略，不使用 `0` 或 `null` 表示“不检查”。
- command handler 只接收完成鉴权、schema 验证和传输映射的 envelope，不读取 HTTP/MCP 对象。
- REST 与 MCP 使用同一 action payload JSON Schema 和同一 canonical request hash；hash 覆盖 command kind、目标、expected revision/epoch 和 payload，不覆盖 trace/transport。

## REST 投影

### 请求

- mutation body 为 `{schema_version, command_id, authority_epoch?, payload}`；`command_id` 是必填 UUIDv7。v1 不要求非标准/草案 `Idempotency-Key` header。
- 对已有 revisioned aggregate 的变更必须发送 `If-Match: "rev-7"`。创建命令和明确声明为 revision-free 的动作不发送 `If-Match`。
- URL/project/resource identity 与 body payload 必须一致；资源 identity 通常只出现在 URL，不允许 payload 另带可冲突副本。
- bearer token 只在 Authorization header；control token 只用于管理端点的独立鉴权机制，不进入 body。

### 响应

- 单资源 GET 和成功 mutation 返回当前强 `ETag: "rev-N"`。ETag 只表达该 resource representation revision，不使用 project event sequence。
- 同步创建返回 `201 + Location`；同步更新返回 `200`（含 representation）或预先固定为 `204` 的无 body 动作；异步工作返回 `202 + Location` 和 Operation representation。
- 相同 `command_id` 与相同 canonical hash 重试时返回首次命令的语义等价结果/Operation；同 ID 不同 hash 返回 409。
- 不依赖 HTTP cache 保存本地鉴权资源；ETag 在这里主要承担并发 validator 和条件 GET。

### 并发与错误状态

| 情况 | HTTP | problem `code` |
|---|---:|---|
| revision-protected mutation 缺少 If-Match | 428 | `precondition_required` |
| If-Match 语法合法但与当前 revision 不同 | 412 | `revision_mismatch` |
| command ID 被不同请求复用 | 409 | `command_id_reused` |
| 当前领域状态不允许动作 | 409 | 具体稳定 code，如 `invalid_task_transition` |
| schema/字段错误 | 422 | `validation_failed` |
| 无身份/无权限 | 401/403 | `authentication_required` / `permission_denied` |
| 资源不存在或对该主体隐藏 | 404 | `not_found` |

RFC 9457 extensions 固定支持 `code`、`command_id`、`trace_id`、`current_revision`、`issues[]` 和受限 `retry` 元数据。客户端不得解析 `title/detail` 决策。

## MCP/适配器投影

- 类型化 mutation tool 输入为 `{schema_version, command_id, expected_revision?, authority_epoch?, payload}`；bridge 凭据确定 project/principal/agent/session。
- tool 的 `inputSchema` 引用与 REST payload 相同的 schema；tool result 的 `outputSchema` 引用相同 resource/operation schema。
- MCP 结构化错误使用与 RFC 9457 extension 相同的稳定 `code` 和 details，但不伪装 HTTP status；bridge SDK 可以映射成本地异常类别。
- 同一个 conformance fixture 分别编码为 REST request 和 tool call，断言生成的内部 envelope canonical hash 相同。

## API 演进边界

- URL 主版本固定 `/api/v1`；JSON Schema 另有 `schema_version`。v1 内只添加具有明确默认/可省略语义的字段，不改变既有字段含义。
- response schema 默认拒绝未知字段只用于服务端/生成产物验证；客户端兼容策略必须容忍 v1 新增字段，但不得容忍未知 enum 值被当作已有状态。
- 如果 `Idempotency-Key` 将来成为 RFC，可作为 `command_id` 的可选 HTTP 投影加入；不能在 v1 内产生第二套幂等身份。

## 后续细化

- command/result/problem 的完整 JSON Schema 与正反 conformance fixtures。
- GET/list 查询参数、分页 cursor、字段命名和时间/空值编码。
- 每个资源哪些动作要求 If-Match、authority epoch 和异步 Operation。
