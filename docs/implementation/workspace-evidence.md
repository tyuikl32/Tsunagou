# 工作区差异与验证证据

本页是 PT3 的可执行契约。工作区扫描属于第六、七模块的机械核验；它只记录当前绑定目录的事实，不推断哪一个 Agent 或用户逐行写入了文件。

## scope

主 Agent 通过 Task 的 `execution_scope.resources` 或 `execution_scope.roots` 决定范围。worker 的 `workspace.prepare.root_binding_refs` 只能从该范围选取根，空列表表示使用全部已授权根；worker 不能传入绝对路径或自行设定 scope。没有显式 task scope 时继承已注册项目根，没有注册根时使用协调仓库。daemon 从本地 `ProjectRegistry` 的绑定解析相对路径 allow-list，并将 `scope_paths`、`scope_roots` 与 `scope_digest` 持久化。空的显式任务范围会被拒绝。

`scope_digest` 绑定排序后的每个根描述：

```json
[{"root_id":"...","paths":["src","tests"],"binding_revision":1,"physical_identity":"inode:...","task_scope_revision":1,"task_scope_digest":"sha256:...","project_id":"...","lineage_id":"..."}]
```

完整根的 `paths=null`。描述采用 canonical JSON SHA-256；不包含本机绝对路径。绑定、任务 scope 或 lineage 改变后，旧工作区必须重新准备。单根结果使用相对路径；多根结果使用 `<root_id>/<relative_path>` 避免同名歧义。跨目录、跨仓库根均独立扫描。

## scan

daemon 使用 `git status --porcelain=v1 -z --untracked-files=all` 和 `git ls-files --stage -z`，因此包含空格、Unicode 和换行的路径不会依赖 Git 的引号显示。内容摘要覆盖允许范围的完整 tracked/untracked 文件，index 摘要含模式、blob OID 和 stage。每个允许路径记录相对路径、类型、SHA-256、大小和文件模式；删除记录 `missing`，符号链接记录链接目标摘要而不跟随目标，特殊文件和越界 reparse point 只记录类型。非 Git 目录使用不跟随链接的目录扫描；不声称有 Git 基线。扫描排除 `.git`、`.tsunagou` 和指定 artifact 存储目录。

patch 只用同一次扫描得到的安全允许路径作为 Git pathspec 生成，禁用 external diff/textconv。符号链接和特殊文件只进入观察摘要，不输出目标内容。ArtifactService 将字节内容寻址保存至 `.tsunagou/local/artifacts/blobs/sha256/`，另生成独立 UUID `artifact_ref`，在 SQLite 记录 project/lineage/domain/owner/scope。相同内容可共享 blob，但不同领域保持独立授权引用。worker 外部引用必须与该 workspace、owner、scope、project/lineage 完全匹配，且在有系统扫描时字节也必须一致。

HTTP `GET /api/v1/artifacts/{artifact_ref}` 必须携带用户控制 Bearer 或已认证 Agent session，读取者必须是用户、当前主 Agent、提交者或该 Attempt owner。hash 本身不是引用，不能用于读取。检查引用与领域权限后再次验证 blob 摘要；损坏返回 `artifact_unavailable_or_corrupt`。私信 recipient 限制不会因 main 身份而放宽，recipient-only 引用禁止提升为共享附件。历史 hash-only patch 未具备明确授权引用时拒绝读取，不推测其 owner。

## validation_metadata

`workspace.result` 可携带验证回执数组。每项至少包含：

```json
{
  "started_at":"2026-09-27T17:00:00.000Z",
  "finished_at":"2026-09-27T17:00:01.000Z",
  "command":"pytest -q",
  "exit_code":0,
  "tool":"pytest",
  "tool_version":"8.x",
  "workspace_digest":"sha256:...",
  "evidence_level":"agent_asserted"
}
```

`workspace_digest`、可选的 `stdout_digest` 和 `stderr_digest` 必须为完整 `sha256:<64 hex>`，不能放入输出正文。工具及版本同时生成 `tool_version_digest`。worker 自报的高等级会保留为 `reported_evidence_level`，规范等级仍为 `agent_asserted`。daemon 自己的扫描会追加独立的 `workspace.scan` 记录并标为 `system_verified`，版本来自实际安装包。结果的 `evidence_subject=workspace_filesystem_observation` 限定整体等级的对象；它不会验证 Agent 提交的测试结果、commit 意义或逐行作者。

## 查询和验收

工作区查询至少显示 `scope_digest`、`changed_paths`、`patch_artifact_domain`、`patch_artifact_owner`、`evidence_level`、`validation_metadata` 和 `observed_at`。遇到基线摘要变化时记录 `baseline_conflict=true`，由主 Agent 决定是否继续；扫描器不执行命令、提交 Git 或接受逐行作者结论。

对应协议来源是 [命令目录](command-catalog.md) 的 `workspace.prepare`/`workspace.result`、[数据库规范](../../.trellis/spec/backend/database-guidelines.md) 和 [隔离模块说明](modules/06-workspaces.md)。
