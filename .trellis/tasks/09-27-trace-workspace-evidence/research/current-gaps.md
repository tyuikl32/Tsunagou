# PT3 接续审计

observed_at: 2026-09-27T17:47:00.000Z；branch: codex/persistence-traceability；基于 PT1/PT2 工作树读取，尚未表示 PT3 已实现。

## 确认的缺口

- `modules/workspaces.py::scan_root` 只为 Git status 中发生变化的路径计算内容摘要，未接受 task scope；symlink 使用 `is_file/read_bytes` 会跟随目标。`index_digest` 仍只来自 name-status。应使用授权范围内路径、内容、类型/模式及 index blob 身份；Git NUL 输出避免带空格、Unicode、换行路径误解析。
- `_patch_bytes` 对 tracked 文件执行无 pathspec 的全局 diff；即使 `changed_paths` 排除了 `.tsunagou`，patch 仍可能包含其已跟踪私密文件或范围外改动。必须从同一授权路径集合生成内容，不将先前 artifact 再收入 patch。
- `handlers.workspace_prepare/result` 只扫描 coordination root，未按 registry local bindings 解析多根范围；caller 的 changed_paths 与系统结果直接取并集。caller 不能用列表或 digest 扩大范围；root refs 也不能替代已有授权。
- 现有 `ArtifactService` 有 domain/recipient 读取概念，但未装配进运行时/持久化。实际 HTTP artifact 路由无需认证，query provider 直接按 hash 读 `.patch`。应把已存在的 artifact 服务接入 durability 持久层，先验证 domain reference/project/lineage/owner/recipient，再核对 blob hash；不能再留并行裸 hash 旁路。
- `ResultManifest` 已有 submitted_by、observed_at、evidence_level、validation_metadata，但 handler 未接 validation metadata；当前任意验证字符串没有开始/结束、工具版本、退出码或输入 workspace digest。文件扫描 system_verified 不能把 worker 自报测试自动升级为系统验证。
- `ServiceStateRuntime` 能持久化 workspace manifest；后续新增字段必须有旧数据默认值，不伪造历史时间。现有 task.submit 流程由 TaskExecutionWorkflow 协调，继续复用其 owner/attempt fence。

## 实施边界

保持八模块：artifact 属 durability 既有服务，不新增第九领域；任务 scope 仍由主 Agent 决定，机械层只验证根、路径和身份。Scan 只观察，不判断逐行作者，不执行用户命令。测试命令自报保留 agent_asserted；daemon 自身扫描保存独立 system_verified 观察。

PT4 将处理所有文件物化的提交后 operation/outbox；PT3 的 artifact 写入设计要为此提供准备内容/元数据与提交后物化的清晰接口，不能扩大既有事务内 Git/文件副作用。先同步 workspace/ArtifactRef/validation Schema，再更新安装包镜像、fixtures、HTTP/CLI 与重启测试。

## 必须新增的验证

同路径不同内容、已暂存内容变化、tracked/untracked、scope 外 sentinel、已跟踪 `.tsunagou`、artifact 递归、symlink/junction/特殊文件、多个授权根、caller 伪造 patch、同 hash 不同领域/私信 recipient、匿名读取、损坏 blob、重启后受权读取，以及自报验证不能声明 system_verified。
