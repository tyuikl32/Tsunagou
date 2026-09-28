# PT5 实施步骤

1. 补齐 query DTO、CLI help、HTTP route 与统一错误；保持现有命令语义。
2. 验证超过 200 条、边界时间、unknown time、无效/过期 cursor、actor、私信和 artifact 越权。
3. 验证 CLI/HTTP 等价和 JSONL 导出；查询失败不写事件、不推进 revision。
4. 将命令示例与 `docs/overview/cli-http-manual.md`、command catalog 同步。

## 完成记录

- completed_at: 2026-09-28T01:26:49Z
- implemented: shared read-only query dispatcher; project/task history; single audit event; export envelope; checkpoint list/verify; task relation expansion; strict generated checkpoint/query DTOs; CLI and HTTP help/route parity.
- changed: `src/tsunagou/bootstrap/container.py`, `src/tsunagou/platform/db/sqlite.py`, `src/tsunagou/platform/checkpoints.py`, `src/tsunagou/api/app.py`, `src/tsunagou/cli/app.py`, `src/tsunagou/shared_kernel/query_models.py`, query schemas/codegen, docs and tests.
- verification: see `research/verification.json` and `research/review-timeline.md`.
- acceptance: all PT5 acceptance points passed; no query path appends domain events, operations or revisions.
