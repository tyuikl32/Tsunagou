# PT4 实施步骤

1. 建立 genesis 和 checkpoint manifest DTO/版本，删除共享 JSON 中动态 runtime 字段。
2. 将 checkpoint 文件 I/O 移到提交后 operation，加入失败、重启、重复 reconcile fixtures。
3. 用真实临时 Git repo 验证 branch/tag/tree 内容；拒绝 OID 子串、remote ref、reflog 和不匹配内容。
4. 演练 clone restore preview/confirm，检查权限全部清除、历史 lineage 正确；不得操作真实用户库。

## PT1 衔接检查

- 项目 registry 已进入事务内 module snapshot 以观察配置/root 变化；现有 handler 的共享文件写入仍早于提交，须在本任务转为提交后幂等物化。
- dispatcher 已在写锁内 capture，但异常后的内存 restore 仍在锁外；同时，提交后 hook 失败可能让调用层误恢复旧内存。必须区分未提交回滚与已提交未应答，覆盖并发命令及进程中断窗口。
- Operation/Job 独立数据库状态变化不经过 ServiceStateRuntime，需接入同一审计包络并记录实际时间/执行主体，不能声称仅有领域快照事件便已覆盖它们。

- 维护循环另有在 writer lock 外 capture snapshot 的路径，需与 dispatcher 的提交/回滚窗口统一验证，避免失败恢复覆盖并发成功状态。

## 执行中记录（2026-09-27）

已落实提交后 CheckpointWorker、Job/outbox、固定重试输入、显式共享 DTO、项目文件投影、Operation/Job 审计、目录原子发布及 Git tree 校验。已接入 clean clone preview/confirm CLI 与恢复端口；恢复保留历史并撤销所有活动权限。

基础 checkpoint/storage/runtime 集成、真实 Windows Git clone 和恢复专项已完成。checkpoint 根目录现在直接承载 checkpoint 内容，避免 `.tsunagou/checkpoints/checkpoints` 重复嵌套；新目录使用 `sha256_<digest-prefix>` 紧凑键，旧的完整 digest 目录仍可读取。`.gitattributes` 将 checkpoint 内所有内容固定为二进制，避免 autocrlf 改变认证字节。

## 已实现的边界

- SQLite 是事实源；业务事务在同一 UoW 内保存冻结的白名单 DTO、Operation、Job 和 outbox，提交后才执行文件物化。重试复用同一 job payload/input_digest，不重新抓取后来状态；物化失败不回滚已提交业务事实。
- shared checkpoint 只包含公开项目、任务、认知、工作区、生命周期、审计和 operation 记录；运行时 epoch、grant、lease、job claim、宿主会话、私信、凭据和绝对路径被过滤。自由文本中的 Windows/UNC/POSIX 路径与 bearer/secret 哨兵也会脱敏。
- `project_shared` 且非 recipient-only 的 ArtifactRef 才能进入 checkpoint。worker 在提交后重新校验本机 CAS 的相对路径、字节长度和 SHA-256，将附件字节写入 checkpoint manifest 的 `artifact_files`；哈希引用没有字节时直接失败。
- Git anchor 只检查本地 heads/tags 的可达提交及完整 tree 内容，拒绝只匹配 OID 子串、remote/ref、reflog 或篡改的 manifest/附件。
- clone 恢复必须先 preview，再用完全相同的 plan digest 执行 user-only confirm。恢复在临时 local 目录同时构造 SQLite 和附件 CAS，验证完整性后一次发布；不导入 session、ticket、grant、lease、job claim 或 root binding。未完成任务进入 `blocked/recovery_review`，旧 running/claimed Attempt 变为 orphaned。

## PT4 验收证据（2026-09-28）

执行环境：Windows，PowerShell，工作树 `D:\Tsunagou`，分支 `codex/persistence-traceability`；未操作真实用户项目，未 commit/push。

- `uv run pytest -q --disable-warnings`：全仓库通过，3 个平台条件 skip。
- `uv run pytest -q tests/integration/test_clone_recovery.py tests/unit/test_checkpoint_materialization.py tests/unit/test_checkpoints.py`：23 项通过。
- `uv run ruff check src tests tools`：通过。
- `uv run mypy src`：63 个源文件通过。
- `uv run python tools/docs/validate_docs.py`：通过。
- `git diff --check`：无内容错误；仅显示 Git 的 LF/CRLF 提示。

任务状态可以从 `in_progress` 转为 `completed`；后续 PT5 负责只读时间线和查询接口，不再改变 PT4 的恢复边界。
