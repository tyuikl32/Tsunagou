# ZCode 适配器实施与诊断

ZCode 适配器把实际启用的 SessionStart/session_id、Hook 和 MCP 工具翻译到 bridge-sdk。T02 记录为未安装，2026-09-18 的 npm/GitHub 研究只找到明确标注非官方的客户端或社区桥接，没有可锁定的官方 CLI/API 版本；hook 文档或配置文件存在不代表运行时启用，缺少运行事件和连续性证据必须保持 unknown。

安装和卸载只管理用户选定 profile 中由 Tsunagou 生成的非秘密 Hook/MCP 引用，操作可重复且可回滚。Full Access 只是宿主设置，不能改变 command dispatcher 的 principal、Grant 或项目范围；适配器不动态扩大用户授权。

适配器要求 host-issued `host_conversation_id_digest` 才能建立 identity，重复通知和 clear/fork/resume 事件只进入 `observeLifecycle`。wake、gate、presented evidence 等增强没有实际证据时不导出为 enforced。

真实验收要锁定版本并在新会话中验证 Hook 真的生效，完成 11 项共同基线、重启和重复事件测试，保存脱敏结果。当前状态为 diagnostic-only。验证：`corepack pnpm --filter @tsunagou/adapter-zcode run check`、`corepack pnpm exec vitest run packages/adapter-zcode/tests`、`python tools/docs/validate_docs.py`。
