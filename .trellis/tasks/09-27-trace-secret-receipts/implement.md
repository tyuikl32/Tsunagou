# PT2 实施步骤

1. 用 secret sentinel fixture 追踪 command result、异常、日志、checkpoint、artifact、WAL/SHM 和 API 输出。
2. 实现 SafeReceipt/delivery reference 和同 actor 恢复；测试 bridge 重启、响应丢失、重复请求、跨 actor、过期和 revoke。
3. 编写旧 schema dry-run/backup/rotate/scrub/integrity 命令，先在临时副本演练；不自动操作用户项目。
4. 记录平台保护机制、备份保留期限和已知取证限制；通过 PT1 的时间/actor 包络写迁移事实。

## 实施记录（2026-09-27T17:42:00.000Z）

- 后端：SQLite whitelist receipt、T principal 哈希、精确 reconnect 重放证明、epoch 受限 ACK、commit 后响应失败不回滚已提交身份；秘密进入 DPAPI/ACL 私有 vault。
- bridge：稳定 pending envelope、逐 conversation 绑定、受保护原子 session 保存后 ACK、单独 ACK sidecar、隐式宿主 session 路径重启恢复。审查继续检查跨进程保存竞态，未完成前不关闭 PT2。
- 迁移：预览内容绑定计划、offline locks、一致私有 backup、revoke/scrub/quarantine/VACUUM/integrity、受保护进度标记、中断恢复和 startup gate；不改用户真实项目。
- CLI：ticket 私有保存后 ACK；`daemon migrate-credentials` 默认预览，显式 digest 确认，错误不输出行值或凭据。
- 公共契约：[凭据交付](../../../docs/implementation/credential-delivery.md)、CredentialDelivery Schema、Python/TS DTO、OpenAPI 和 fixture 同步；[操作手册](../../../docs/overview/cli-http-manual.md#11-旧库凭据迁移pt2) 提供直接命令。
- 已通过：35 项 receipt/storage/vault/migration/CLI 测试、5 项 M1/A2A integration、20 项 audit/delivery schema 与迁移 CLI 测试，mypy/TypeScript/protocol/docs 检查。审查新增修复后的最终全量结果另写 verification.json。
- bridge `test:credentials` 已纳入 `tools/dev/check.ps1`；包括独立进程并发/故障测试和显式、隐式 session 的 MCP 重启烟测。
- PT2 共享输出防护：workspace patch 现在只对扫描允许的路径做 diff；即使用户误把 `.tsunagou/local` 跟踪到 Git，已暂存私密状态也不会被全局 diff 再次收入 patch。私有目录单独变化时不生成 patch；对应 tracked/untracked secret sentinel 测试已通过。完整 scope/ArtifactRef 改造仍由 PT3 承担。

## 最终验证

[verification.json](research/verification.json) 记录完整检查命令、实际 UTC 起止时间、退出码、输出摘要和源码摘要，结束于 `2026-09-27T17:55:55.691Z`，所有列出的检查通过。[独立审查](research/review-pt2.md) 的跨进程竞态、旧库启动拦截和 Windows ACL 问题均已修复。任务已完成；未迁移真实用户项目。
