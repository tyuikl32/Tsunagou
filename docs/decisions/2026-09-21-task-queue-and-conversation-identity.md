# 任务队列与对话身份修正

日期：2026-09-21

## 结论

1. 执行 Lease 只约束当前 Attempt 的执行资格，不约束 Task 的存在、挂起状态或未来领取。
2. `task.block` 释放执行 Grant 和资源 Lease，但保留旧 Attempt 的 blocked 历史，使原 owner 可以显式 resume。
3. Lease 到期、daemon 重启或执行连接失去所有权时，旧 Attempt 变为 `orphaned`，Task 回到 `open` 公共队列。兼容历史数据中的 `orphaned` Task 也直接允许新 Agent claim。任何后来加入且拥有基础协调权限的 Agent 都可以重新 claim；不需要原 Agent、旧 bridge 或旧对话先恢复。
4. 新 Agent claim 时，如果 Task 仍指向旧的 blocked Attempt，该 Attempt 关闭为历史 orphaned，并创建新的不可变 owner Attempt。旧 Attempt 不会被改 owner，也不会继续持有 Lease 或 Grant。
5. `recover` 是主 Agent 对历史 Attempt 的显式处置接口，不是新 Agent 领取 open Task 的前置条件。原 owner 的 `resume` 只适用于仍保留的 blocked Attempt。
6. `installation_id` 只标识宿主安装。每个宿主 conversation、fork 出的 subagent 或新对话都必须拥有独立的 `agent_id`、`session_id`、凭据和私有 bridge session 文件。
7. 服务端 Agent 记录持久保存 conversation digest；`session.rebind` 在指定 `target_agent_id` 时必须同时匹配 conversation digest，禁止把另一对话绑定到旧 Agent。
8. bridge 未显式提供 `TSUNAGOU_SESSION_FILE` 时，不再使用全局 `~/.tsunagou/bridge-session.json`，而是按可信 conversation digest 选择 session 文件。没有可信 conversation identity 时不生成默认恢复文件。

## 原因

任务可能在用户等待、主 Agent 暂时离线或某个 worker 尚未加入时长期存在。把任务本身绑定在执行 Lease 或旧 worker 上，会把“等待执行”错误地变成“等待原身份回来”。Lease 的职责是防止陈旧进程继续获得执行权限，队列的职责是让合格 Agent 公平领取任务，这两者必须分离。

同一个 IDE 可以同时运行多个 Codex/OpenCode 对话和宿主 subagent。IDE 安装不是对话身份；共享一个默认 session 文件会让不同对话继承同一 token、Agent 和 Attempt owner，破坏主从边界。身份隔离必须在 bridge 私有文件和 daemon Agent 记录两端同时成立。

## 验证

- `tests/unit/test_tasks.py`：blocked Task 被后来 Agent claim；Lease orphan 后 Task 回到 open 并可由新 Agent claim。
- `tests/unit/test_runtime_maintenance.py`：后台 Lease 回收保留旧 Attempt orphaned，同时 Task 为 open。
- `tests/unit/test_authority.py`：同 installation 的两个 conversation 生成不同 Agent；rebind 不能跨 conversation retarget。
- `uv run pytest -q`：全量通过。
- `corepack pnpm --dir packages/bridge-server run check`、`corepack pnpm --dir packages/bridge-sdk run check`：通过。
