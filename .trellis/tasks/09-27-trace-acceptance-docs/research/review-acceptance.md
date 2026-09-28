# PT7 整体验收复核

- reviewed_at: 2026-09-28T02:39:54Z
- reviewer: tyuikl32 / Codex
- evidence: `docs/standalone/persistence-traceability-2026-09-28.json`, `docs/standalone/persistence-traceability-acceptance-2026-09-28.json`

## 结果

临时 Git 项目上的 assembled-backend 审计退出码为 0，24 项运行检查和 8 项 A2A 子检查全部通过。覆盖双 Agent 的任务边界、消息持久化和幂等、A2A task/message/cancel/fail/retry 权限、daemon 重启后的任务/契约/消息可见性、CLI ticket 以及 SQLite 创建。

随后运行 PT1–PT7 非破坏性整体验收脚本，10 个门禁全部为退出码 0：协议和审计代码生成、协议校验、架构校验、Python lint、mypy、全量 pytest、文档链接校验、bridge-server workspace build 和 pnpm check。Windows 环境使用 `corepack.cmd`，命令本身成功，不是跳过 Node 门禁。

## 边界和留痕

验收只创建和删除临时项目，未打开用户指定的 state directory，未执行 credential migration、restore confirm、旧 session 撤销、真实项目停写或 Git commit/push。验收报告记录了 UTC 毫秒时间、版本、schema bundle digest、工作树 dirty 状态、命令、退出码和安全摘要；没有记录 token、nonce、私密消息正文或完整宿主输出。

`audit_standalone.py` 仍会报告 command catalog 中 111 个声明命令只有 67 个已注册 handler。缺失项属于后续产品范围；它们没有被伪装成 supported，也不阻塞本轮 PT1–PT7 的查询、时间线、诊断和恢复留痕验收。

## 可重复入口

人工操作、失败定位和关闭标准集中在 [PT1–PT7 非破坏性整体验收执行单](../../../../docs/standalone/persistence-traceability-runbook.md)。任何真实项目迁移仍需用户单独授权并使用专门的备份、plan digest 和回滚流程。
