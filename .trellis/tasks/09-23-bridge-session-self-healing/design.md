# Bridge 会话自愈设计

bridge 是 MCP stdio 长进程，`codex mcp add` 只更新启动配置，不会替换已经存在的 Node 进程。会话文件可能在进程启动后才出现，所以 admission 文件必须在请求边界重新读取。

恢复函数只操作当前 bridge 配置指定的 ticket/session 路径。ticket 的 conversation binding digest 与 session 的 digest 不一致时拒绝；没有 session 时 ticket 只兑换一次；有 session 时 ticket 走 rebind；无 ticket 的重启走 reconnect。并发请求共享一个 recovery promise，避免多个 rebind 消耗同一张 ticket。

对 transport dispatch 的 authentication/epoch 错误，清空内存 session、执行一次恢复并复用原 `command_id` 重试。其他网络错误原样返回，避免把超时业务命令当成安全可重放操作。
