# 凭据交付与旧库迁移（PT2）

更新时间：2026-09-27T17:35:00.000Z。实现入口为 `platform/delivery.py`、`platform/credential_migration.py`、HTTP ACK 和 bridge `credential-handoff.ts`。PT2 整体验收以 Trellis 任务中的 verification 记录为准。

## 交付边界

交付元数据采用 [CredentialDelivery Schema](../../protocol/schemas/queries/credential-delivery.schema.json)。`tools/codegen/generate_audit.py` 同时生成 audit/delivery Python 与 TypeScript DTO，ACK 路由在 OpenAPI 中直接引用该生成模型。

`agent.ticket.create.user`、`agent.ticket.create`、`agent.enroll`、`session.rebind`、`session.reconnect` 保留既有的认证命令响应形状。只有这条私有交付响应可包含必要的 `secret`、`secret_token`、`reconnect_nonce`；普通查询、模型工具结果、CLI stdout、日志、事件与 SQLite command receipt 不包含可用秘密。

SQLite 的安全回执保存身份摘要及 `receipt_id`、`delivery_ref`、`delivery_status`、`created_at`、`expires_at`、`delivered_at`、`recovery_expires_at`、`consumed_at`、`revoked_at`。交付时间在数据库为 UTC 毫秒，在 HTTP 为 RFC3339 `.sssZ`；尚未发生的时间为 null。T principal 存 ticket 哈希，不能把 bearer 当作审计 actor 或幂等主键。

vault 放在项目本机 `local/state.sqlite3.deliveries` 中，Windows 使用当前用户 DPAPI 与 SID 专属 ACL；POSIX 使用用户专属目录/文件权限。vault 绑定 project、principal、command kind、command ID、request digest。引用本身没有读取权限。秘密有效期最多 10 分钟，首次读取后恢复窗口最多 2 分钟且不超过原过期时间。

## 保存与 ACK

1. bridge 在发送凭据命令前，把完整 envelope 和恢复所需证明存入逐 conversation 私有 pending journal；并发进程争用同一 journal，不重新生成命令 ID。
2. 网络响应丢失时重放同一命令。daemon 复用已经提交的身份与 receipt。旧 reconnect token 只允许原命令的精确重放，不能调用其他命令。
3. bridge 校验 conversation/目标身份，先用受保护的临时文件、fsync 和原子替换保存 session，再发 ACK。保存失败时保留原请求，不 ACK。
4. `POST /api/v1/credential-deliveries/{delivery_ref}/ack` 接受空 body 或 `{}`，认证为原 U ticket 签发者，或交付结果对应的有效 session/epoch。不能在 body 自报 actor。响应与凭据命令均设置 `Cache-Control: no-store`。
5. ACK 把 vault 标为 consumed 并移除秘密；重复 ACK 返回同一元数据。ACK 响应丢失时 bridge 保留已保存的 session，仅补 ACK。ACK 状态单独保存，迟到的 ACK 不能覆写较新 session。

已 consumed、expired 或 revoked 的 receipt 重试只返回安全状态与 `recovery_action=reconnect_required`，不创建新 Agent。若 bridge 已保存 session，直接继续使用或正常 reconnect；若私有交付从未保存且恢复窗口已过，按接入恢复流程重新签发/绑定，不能把 receipt 当永久取密接口。

## 离线迁移

daemon 在打开 writer 和恢复 authority 前只读检查旧凭据；没有迁移标记或标记已完成，都不能使后来放回的旧库绕过检查。检测到旧明文 command receipt/escrow 时返回 `credential_migration_required`。同一项目 bridge 的 session 比较/保存使用短进程互斥，避免慢响应覆写新 epoch；网络请求和 ACK 不在互斥内等待。

`daemon migrate-credentials --coordination-root <项目>` 默认仅预览；`--dry-run` 显式表达同义行为。预览基于 SQLite Backup API 的一致只读快照，生成数据库和待隔离文件内容绑定的 `plan_digest`。只有带 `--confirm-plan-digest <原摘要>` 才执行。

执行必须取得 daemon/runtime 和数据库 writer 锁；命令不会替用户停止活跃 daemon。输入变化时返回 `migration_plan_changed`，须重新预览。流程为：

1. 创建 SID/权限保护的一致备份并验证 integrity；保留原始数据库 digest。
2. 写入受保护的 `credential-migration.json` 进度标记。未完成标记阻止 daemon 启动。
3. 单事务撤销旧 session、ticket、grant 和主权限，轮换 runtime fence，清理普通表中秘密副本并写 `credential.migrate` 事件。
4. 把含秘密的共享文件/旧交付文件移到私有 quarantine，再清除 WAL 可见副本、VACUUM、验证 integrity 与 secret sentinel。
5. 标记 completed，输出 `recovery_action=enroll_and_appoint_again`。用户重新接入并任命主 Agent；历史任务不删除。

中断后使用**原 plan digest**重跑同一命令，不能重新创建迁移或把原备份直接放回运行位置。数据库已提交而文件清理失败时，进度仍保持 in_progress，重试完成剩余步骤。备份和 quarantine 位于 `.tsunagou/local/credential-migrations/<operation_id>/`，包含已撤销的历史秘密，仅供私有取证与离线修复；不进入 checkpoint/Git。当前不自动删除备份，由用户在验收后决定保留期限。迁移不能抹除先前复制到其他介质的文件。

## 验证入口

```powershell
uv run pytest -q tests/unit/test_trace_secret_receipts.py tests/unit/test_secret_delivery.py tests/unit/test_credential_migration.py tests/unit/test_credential_migration_cli.py
corepack pnpm --filter @tsunagou/bridge-server run test:credentials
uv run python tools/dev/smoke_standalone.py --skip-build
```

它们分别覆盖真实 dispatcher/SQLite/HTTP、Windows DPAPI/ACL、旧库撤销和中断恢复、用户 CLI、两独立 bridge 进程的丢响应/保存失败/ACK 丢失，以及临时项目的 CLI→daemon→MCP→重启闭环。真实业务项目的迁移另需用户明确指示。

依据与限制：[Microsoft CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)、[SQLite Backup API](https://sqlite.org/backup.html)、[SQLite WAL](https://sqlite.org/wal.html)、[SQLite VACUUM](https://sqlite.org/lang_vacuum.html)。
