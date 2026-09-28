# PT6 实施步骤

1. 盘点现有 reconnect/wake/coordination 事件，给其归类而不删除历史。
2. 为常驻 bridge no-op、epoch 变化、callback 重试、host unknown、Agent pull/turn 建 fixture。
3. 让 history CLI 显示证据类型和关联 ID，验证 callback 不冒充 turn。
4. 用一个验收后缺陷创建新 task/result，验证关联可查且旧记录不被追补。

## 完成记录

- completed_at: 2026-09-28T01:48:27Z
- implemented: durable secret-free diagnostic journal in `WakeDispatcher`, lifecycle evidence correlation, restart/no-op deduplication, authenticated diagnostics HTTP query, CLI `project diagnostics`, shared strict diagnostic DTO, and user/protocol docs.
- diagnostic storage: `.tsunagou/local/diagnostic-events.json`; it is separate from SQLite domain events and does not advance domain revisions.
- verification: see `research/verification.json` and `research/review-noise.md`.
- acceptance: callback, wake request, thread, turn and Agent presentation remain separate evidence; repeated delivery is idempotent and restart uncertainty is explicit.
