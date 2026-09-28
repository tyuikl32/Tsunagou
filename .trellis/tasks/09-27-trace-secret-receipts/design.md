# PT2 设计

created_at: 2026-09-27T14:39:38Z

命令完成时只在 SQLite 记录 `SafeReceipt`；秘密进入按项目/session/actor 隔离的 delivery bucket。bucket 使用平台保护（Windows DPAPI/ACL，其他平台严格权限），读取通过本机 bridge 认证标记 delivered，bridge 原子保存后 ACK 才消费。相同 idempotency key 只返回同一 receipt；丢响应时允许同一绑定命令在短恢复窗口重新取同一 delivery，跨 actor、过期或已撤销都拒绝。

旧库迁移是独立 operation：一致 backup → integrity/secret scan → 只读窗口 → revoke/rotate → 清理可见副本 → schema 打开 → 再 scan。保留只读原始备份的路径和风险，不声称文件系统取证清除。

## 实施细化（维持既有本机入口）

- 复用已认证的凭据命令响应作为私有交付，不另建普通 Agent 可调用的取密工具。命令 SQLite 回执只含安全摘要和 delivery_ref；交付结果由 vault 在同一调用边界按精确 command scope 恢复。
- 交付初始有效 10 分钟；首次读取后，只在至多 2 分钟且不超过初始过期时间的恢复窗口内允许同一绑定重读。bridge 原子保存 session 后调用独立认证 ACK；ACK 幂等并移除 vault 内的秘密，历史 receipt 仍保留。过期或已消费不能生成第二身份。
- vault 绑定 project/principal/command kind/command ID/request digest。T 的持久身份使用 ticket 哈希/ID，不能用原始 bearer；session.reconnect 的旧 credential 只可证明原来精确命令的丢响应重放，不恢复它调用其他命令的权限。
- ACK 路由为 `POST /api/v1/credential-deliveries/{delivery_ref}/ack`，仅原 user_control ticket 签发者或实际结果 session 使用有效凭据确认；仅持有 ref 无权确认。
- Windows vault 用当前用户 DPAPI 和私有 ACL；禁止 LOCAL_MACHINE 模式。其他平台使用私有目录/文件权限。密文先以私有临时文件原子持久化，随后事务提交引用；这是可回收、不可见的交付预备记录，不是事务内公开 checkpoint 物化。事务失败的孤立记录没有可认证 receipt，因此不可领取；返回交付只发生在提交之后。
- 旧库 scrub 不能把旧活跃凭据复制到新 vault。先撤销旧 session/ticket/grant、轮换 fencing，记录迁移，清理行值和可见 WAL/副本。备份保持私有并明确含有历史秘密，不能把它当作可直接恢复运行的库。
