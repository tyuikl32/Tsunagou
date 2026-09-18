# 列表分页、排序与 Cursor 协议

> 核对日期：2026-09-17。
> 状态：已确认选择 A（签名 opaque keyset cursor）。

## 设计依据

- RFC 8288 定义 HTTP `Link` header 和 link relation；下一页可使用 `rel="next"`，但 cursor 的内部语义由本项目定义。
- RFC 4648 定义 URL-safe Base64 alphabet；协议可以明确省略 padding，避免 query string 中的额外转义。
- HMAC 可验证 cursor payload 的完整性。cursor 签名只防止篡改和错误复用，不替代 bearer 鉴权或资源授权。
- SQLite 同一 read transaction 可以提供快照，但跨多个独立 HTTP 请求保持事务会占用连接和历史页面；持久化每次列表快照则会增加状态、清理与恢复负担。

来源：

- [RFC 8288: Web Linking](https://www.rfc-editor.org/rfc/rfc8288.html)
- [RFC 4648: Base64url](https://www.rfc-editor.org/rfc/rfc4648.html#section-5)
- [RFC 2104: HMAC](https://www.rfc-editor.org/rfc/rfc2104.html)

## 选项

| 选项 | 方案 | 优点 | 代价与一致性 |
|---|---|---|---|
| A（推荐） | 有效期内的签名 opaque keyset cursor；默认只允许不可变排序键 | 并发新增时不因 offset 漂移；无服务端 cursor 表；REST/MCP 易统一 | 状态过滤是逐页当前视图，不提供跨请求历史快照 |
| B | `offset` + `limit` | 实现和手工调用最简单；可直接跳页 | 并发插入/删除会重复或漏项；深页查询越来越慢；不适合 inbox/event 等持续变化集合 |
| C | 服务器持久化精确 snapshot token | 多页严格一致；可稳定回看一次搜索结果 | 要保存成员集合/历史投影并清理 TTL；崩溃恢复、权限变化和磁盘成本显著提高 |

## 推荐 A：请求与响应

- 首次 REST list 请求使用 allowlist filters、`sort`、`direction` 和 `limit`；默认 limit 50、最大 200。每个端点有固定默认 sort 和允许字段。
- 响应统一为 `{ "items": [...], "next_cursor": "..." }`；最后一页省略 `next_cursor`，不使用 null。存在下一页时同时返回 RFC 8288 `Link: <...cursor=...>; rel="next"`。
- 后续请求只传 `cursor`；cursor 与 filter/sort/direction/limit 同时出现返回 `400 cursor_parameter_conflict`，避免两份条件不一致。
- MCP list tools 使用相同 response schema，后续 tool call 同样只传 `cursor`。CLI 的 `--all` 逐页消费并设置总 items/bytes 安全上限。
- v1 不返回默认 `total_count`，因为它与 live filters 会迅速失真并增加查询成本。确有产品需求时定义独立 count query/明确时点语义。

## Cursor 结构

cursor 是两个无 padding base64url 段：`base64url(JCS(payload)).base64url(HMAC-SHA256(payload))`。

payload 包含：

```json
{
  "cursor_version": 1,
  "key_id": "...",
  "list_kind": "tasks",
  "project_id": "...",
  "principal_id": "...",
  "filter_hash": "sha256:...",
  "sort": ["created_at", "task_id"],
  "direction": "asc",
  "last_values": ["2026-09-17T10:00:00.000Z", "019..."],
  "limit": 50,
  "issued_at": "2026-09-17T10:05:00.000Z",
  "expires_at": "2026-09-17T10:20:00.000Z"
}
```

- cursor 默认有效 15 分钟，最大编码长度 2048 bytes。签名 key 来自 daemon service secret 的派生 key；`key_id` 支持有限轮换宽限。
- signature 使用恒定时间比较。project/principal/list kind/filter/sort 都参与签名；每页仍重新执行当前鉴权，cursor 不授予任何新权限。
- 格式、签名、scope、过期分别返回稳定 `400 invalid_cursor`、`403 cursor_scope_mismatch`、`410 cursor_expired`；问题响应不回显整个 token。
- cursor 只是 continuation position，不是可长期保存的业务资源，也不进入 Git shared layer、审计正文或日志。

## Keyset 与排序规则

- 每个 sort 都必须以唯一且稳定的 ID 作最后 tie-breaker；SQL 使用与 cursor 完全一致的 tuple comparison 和 index direction。
- 默认排序只用创建后不可变字段，例如 tasks `(created_at, task_id)`、agents `(registered_at, agent_id)`、operations `(created_at, operation_id)`。
- inbox 默认使用不可变 `(priority_rank, enqueued_seq, message_id)`；priority 在路由时固化，后续 disposition 不改变排序键。
- v1 不允许按 title、自由文本、动态 progress 等不稳定字段分页。若允许 `updated_at`，必须作为明确 opt-in live sort，并在文档说明可能移动。
- filters 也经过 canonicalize/hash。状态在翻页间变化时，集合成员可以变化；cursor 仍从稳定 sort position 继续，不承诺重建旧状态。需要“当前完整集合”的客户端从第一页刷新。

## 专用顺序接口

- project event/audit timeline 使用不可变 `after_seq`、`limit`，返回 `next_after_seq`；sequence 本身就是授权后的 continuation key，不再包 opaque cursor。
- SSE `high_watermark` 可直接作为 timeline 的目标上界，但 REST timeline 仍根据当前权限过滤内容；看见更高 sequence 不表示有权读取每条事件 payload。
- 资源 wait queue 等只供内部/诊断使用的严格顺序列表可以使用对应单调 sequence，不强制套用通用 cursor。

## 索引与测试

- 每个公开 list endpoint 在实现计划中必须同时列出 filter allowlist、sort tuple、SQL index 和最大 page size；没有匹配索引不得发布。
- conformance 覆盖并发插入、状态变更、同 timestamp tie、正反方向、篡改、跨 principal/project 复用、过期/key rotation 和最大 token。
- 性能检查在 10 万行合成表上比较第一页与深 cursor 页延迟，不能退化成 OFFSET 扫描。

## 后续细化

- 每个 REST/MCP list 的具体 filters、sort 和 index 表。
- cursor signing key 的派生 label、轮换宽限和 daemon secret 丢失后的错误路径。
- CLI `--all` 的默认 items/bytes 上限和流式 JSON/NDJSON 输出需求。
