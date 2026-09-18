# OpenCode 适配器实施与诊断

OpenCode 适配器只翻译官方 Sessions、plugin 事件和 MCP 工具入口到 bridge-sdk。T02/T19 已用 `opencode-ai 1.18.31` headless server 完成无模型真实 probe：同目录双 session、session 详情、fork 新 ID、消息历史和 `/doc` typed API 可观察；连续 resume、任务/认知/契约、bridge 重连和去重仍 unknown，不能用部分证据改成正式 ready。

安装时只在用户选定 profile 写入非秘密 bridge 命令和适配器版本。token 由 bridge 私有存储注入，不能出现在 prompt、tool args、静态 MCP 配置或环境变量。卸载删除适配器生成的 profile 引用，保留 OpenCode 原生 session 与项目持久化。

`OpenCodeAdapter.getIdentity` 需要 host-issued `host_conversation_id_digest`；`probeCapabilities` 返回完整 11 项并保留每项 evidence。plugin 关闭、事件乱序、重复通知和恢复失败都应产生 degraded/unknown 诊断，不能假 ready。当前包只提供 host-neutral 翻译接口，未假定 OpenCode 私有 SDK 方法。

真实验收需要继续锁定 OpenCode 版本，证明 resume/compact/new/clear/fork 连续性、typed tools、pull/fetch/ACK、重连和去重，再把脱敏证据写入 `docs/research/evidence/`。当前适配器仍是 diagnostic-only。

验证：`corepack pnpm --filter @tsunagou/adapter-opencode run check`、`corepack pnpm exec vitest run packages/adapter-opencode/tests`、`python tools/docs/validate_docs.py`。
