# 集成与发布门禁

T23 把工程正确性和宿主支持分开验收。`tests/integration/` 使用真实临时 SQLite、持久 inbox 和模块状态机验证回滚、ACK、单 owner、旧 epoch 和未知外部结果；`tools/dev/release_check.py` 再读取脱敏宿主 evidence，要求首发必需的 Codex、OpenCode、DeepSeek Harness 三者各自 11 项 baseline 全部 `supported` 且有 `evidence_refs`。ZCode 保留为可选的 post-release 适配器，不阻塞首发门禁。

**当前门禁实跑（2026-10-07）返回 1，`failures` 是 2 个，不是 3 个**：`codex:live_baseline_missing` 与 `deepseek:live_baseline_missing`；**OpenCode 已通过**（门禁读到的 `docs/research/evidence/opencode-2026-09-28-retest-merged-tree.json` 是 11/11 `supported`）。

两个失败要分开说，因为**门禁不读验收报告，它读 `docs/research/evidence/{host}-*.json` 里按文件名排序的最后一个**（`load_host_evidence()` 的 `sorted(...)[-1]`）：

| 宿主 | 门禁实际读到的文件 | 那份文件里的状态 | 缺几项 |
|---|---|---|---|
| codex | `codex-gap-tools-2026-09-19T2317-http.json` | 只有 3/11 `supported`（09-19 的缺口记录，字典序 `codex-g` 排在 `codex-2` 之后） | 8 |
| deepseek | `deepseek-2026-10-01.json` | `review.verdict = "not_accepted"`；11 项里只有 `inbox.pull_fetch_ack` 是 `supported` | 10 |

⚠️ **不要引用 [宿主矩阵](../research/host-matrix.md) 里"Codex 已 11/11 supported"那句话来推断门禁状态**：矩阵引用的是 `codex-2026-09-20-final-two-live.json`，而门禁消费的是另一份文件。这是本仓库一处已知的口径不一。

另外本文原先写"OpenCode 1.18.31 与 DeepSeek Harness 0.1.5-rc.2 已各自取得临时无模型 probe 的身份隔离部分证据" —— 两处都不成立：OpenCode 已经**通过**；而门禁读到的 DeepSeek 文件是 **0.2.0-rc.2** 期的，其中 `identity.session_isolation` 是 `unknown`（理由写着"反例未关闭"），并非 supported。

ZCode 的 unknown 证据继续保留，但不进入首发失败列表。这是保护性结果，不是测试失败被隐藏，也不阻止继续开发内核和报告。

命令输出同时包含 `missing_capabilities`，逐宿主列出缺少 `supported` 状态或 `evidence_refs` 的具体 baseline 名称；它只解释 gate，不改变 gate 判定，也不会把部分证据提升为 ready。

工程检查示例：

```text
uv run pytest tests/integration -q
uv run ruff check src/tsunagou/application/release_gates.py tools/dev/release_check.py tests/integration
uv run mypy src/tsunagou/application/release_gates.py tools/dev/release_check.py tests/integration
uv run python tools/dev/release_check.py   # 当前因真实宿主证据不足返回 1，并列出每个宿主缺失的 baseline 行
```

真实发布还需要故障集合中的 DB commit 前后崩溃、旧 epoch、并发 claim、Lease orphan、pull/ACK 恢复、契约变化、Git receipt unknown、completion checkpoint repair、lineage reset、manifest/path 诊断和私信隔离。模拟适配器测试只能证明判定逻辑，不能替代真宿主记录；Windows 是首要基准，macOS/Linux 只在实际执行后报告 smoke 或 supported。
