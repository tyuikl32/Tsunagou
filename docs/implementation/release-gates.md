# 集成与发布门禁

T23 把工程正确性和宿主支持分开验收。`tests/integration/` 使用真实临时 SQLite、持久 inbox 和模块状态机验证回滚、ACK、单 owner、旧 epoch 和未知外部结果；`tools/dev/release_check.py` 再读取脱敏宿主 evidence，要求首发必需的 Codex、OpenCode、DeepSeek Harness 三者各自 11 项 baseline 全部 `supported` 且有 `evidence_refs`。ZCode 保留为可选的 post-release 适配器，不阻塞首发门禁。

当前门禁预期失败：Codex 只有 disposable app-server 的部分证据，OpenCode 1.18.31 与 DeepSeek Harness 0.1.5-rc.2 已各自取得临时无模型 probe 的身份隔离部分证据；三个首发宿主都未完成 11 项共同基线，故仍输出三个 `live_baseline_missing`。ZCode 的 unknown 证据继续保留，但不进入首发失败列表。这是保护性结果，不是测试失败被隐藏，也不阻止继续开发内核和报告。

命令输出同时包含 `missing_capabilities`，逐宿主列出缺少 `supported` 状态或 `evidence_refs` 的具体 baseline 名称；它只解释 gate，不改变 gate 判定，也不会把部分证据提升为 ready。

工程检查示例：

```text
uv run pytest tests/integration -q
uv run ruff check src/tsunagou/application/release_gates.py tools/dev/release_check.py tests/integration
uv run mypy src/tsunagou/application/release_gates.py tools/dev/release_check.py tests/integration
uv run python tools/dev/release_check.py   # 当前因真实宿主证据不足返回 1，并列出每个宿主缺失的 baseline 行
```

真实发布还需要故障集合中的 DB commit 前后崩溃、旧 epoch、并发 claim、Lease orphan、pull/ACK 恢复、契约变化、Git receipt unknown、completion checkpoint repair、lineage reset、manifest/path 诊断和私信隔离。模拟适配器测试只能证明判定逻辑，不能替代真宿主记录；Windows 是首要基准，macOS/Linux 只在实际执行后报告 smoke 或 supported。
