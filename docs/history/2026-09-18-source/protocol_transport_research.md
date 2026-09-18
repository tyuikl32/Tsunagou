# 传输、游标与投递语义研究

> 核对日期：2026-09-17。
> 状态：研究结论与候选方案；标为“已确认”后才构成实现约束。

## 已有约束

- REST 返回权威资源，SSE 只提示发生变化。
- 每个 Agent 有持久收件箱；消息需要显式 ACK，断线不能丢失。
- 项目事件使用单调递增的 project event sequence；领域历史长期保存。
- 浏览器 API 使用显式 bearer、无 Cookie，管理操作还需要 control token。

## 标准与库行为

- WHATWG EventSource 以 `text/event-stream` 接收事件，事件 `id` 会更新客户端的 last event ID；重连请求可携带 `Last-Event-ID`。
- 重连时间属于客户端状态，初值由实现决定，服务端 `retry` 字段可改变它。浏览器也可以在失败后增加额外退避。
- 原生浏览器 `EventSource` 构造器只接受 URL 和 `withCredentials`；标准接口没有自定义 Authorization header 参数。
- `sse-starlette` 支持事件 `id`、默认 15 秒 ping、发送超时、断线检测和优雅关闭。它解决连接生命周期，不提供持久投递语义。

来源：

- [WHATWG Server-sent events](https://html.spec.whatwg.org/multipage/server-sent-events.html)
- [sse-starlette README](https://github.com/sysid/sse-starlette)

## 候选方案：SSE 高水位信号

### 流与鉴权

- Agent 使用 `GET /v1/projects/{project_id}/stream`，通过 bearer token 鉴权；服务端只允许该 Agent 已授权项目的信号。
- 当前宿主桥接使用普通 HTTP 流客户端并发送 Authorization header。未来 Web 工作台必须使用支持 bearer header 的 Fetch 流式 SSE 客户端，不能直接使用原生 `EventSource`。
- 响应使用 `Cache-Control: no-cache`，15 秒注释 ping，30 秒单次 send timeout。ping 不进入事件表，也不推进游标。

### 游标与载荷

- SSE `id` 使用十进制 project event sequence；每条信号只包含 `project_id`、`high_watermark` 和有限的 `topics`，不含消息正文、源码、凭据或领域事件 payload。
- 服务端允许把连续提交合并为一条信号，`id` 和 `high_watermark` 取已观察到的最高 sequence。客户端不得假设每个 sequence 都会对应一条 SSE。
- 建连后立即发送 `sync` 信号，给出当前高水位。`Last-Event-ID` 和显式 `after_seq` 只用于诊断差距与减少无效拉取，不承诺逐条重放。

### 恢复与可靠投递

- 收到变化信号后，客户端用 REST 拉取自己的 inbox、任务/契约查询投影或事件时间线；写操作继续使用命令 envelope、幂等键和预期 revision。
- durable inbox 的 delivered/read/ack 状态与 SSE 连接无关。断线期间发生的消息在重连后仍由 REST 拉取并显式 ACK。
- 不建立独立 SSE replay 表，也不设置一套与领域事件不同的保留窗口。若客户端游标不可识别、超出可查询范围或属于旧 project generation，发送 `resync_required`，客户端丢弃缓存并读取当前投影。

### 关闭与卸载

- 守护进程关闭、项目归档或显式卸载前发送 best-effort `stream.closing` 后关闭连接；该信号本身不作为状态证据。
- 重连时以 REST 健康端点和项目状态为准。项目只是从内存卸载时可以按需重新加载；已归档项目返回当前只读状态并不再维持实时流。
- 客户端采用带抖动的指数退避，并服从服务端 `retry` 下限；任何一次重连都先执行 `sync`，不能从“连接恢复”推断中间事件已收齐。

## 需要验证

- Windows 下 Uvicorn + `sse-starlette` 的断线取消、15 秒 ping、30 秒发送超时与守护进程优雅退出。
- sequence 合并、重复信号、乱序网络到达、游标跨 generation 和 `resync_required` 的协议测试。
- Fetch 流式 SSE 客户端与四种宿主桥接的 bearer header、代理环境变量和 IPv4/IPv6 loopback 行为。
