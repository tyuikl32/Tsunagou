# 主 Agent 的 Git 控制协议

> 核对日期：2026-09-17。
> 状态：第 161 题已确认选项 A；作为 D84 的主 Agent Git 分级自治基线。

## 责任划分

### 调度中心

- 生成、封存并物化协作 checkpoint；维护项目、任务、契约、权限和审计状态。
- 通过本地只读 Git 命令验证 repository identity、工作树状态、commit tree、checkpoint hash、ref 可达性和 ancestry。
- 创建语义化 `GitActionRequest`，追踪 Operation/Job/消息义务，并接收 `GitActionIntent`、`GitActionReport` 与 reconcile 结果。
- 不执行 add/commit/checkout/reset/merge/rebase/fetch/pull/push、ref 更新或 remote 查询，不持有 Git remote 凭据。

### 当前主 Agent

- 在自身 IDE/Harness 的 Full Access 环境中选择和执行具体 Git 命令，包括本地历史、跨任务集成和远端交互。
- 执行前读取项目状态、checkpoint 和约束；对受协议管理的动作先提交 intent，对完成/失败/不确定结果提交结构化 report。
- 不手工编辑 `.tsunagou` 的机器生成共享文件；先让调度中心完成 materialization/checkpoint，再将精确受管路径纳入 commit。
- 负责发现冲突、解释 Git 结果和提出恢复方案；不能借 Git 操作扩大用户授予的 roots、权限上限或主 Agent authority。

### 用户

- 可随时在系统外执行 Git，并拥有主 Agent 任免、权限上限与高风险动作的最终决定权。
- 外部 Git 变更由核心只读检测后进入 reconcile，不能因为绕过 intent 就被忽略或自动覆盖。

## 为什么需要分级

Git 的“可恢复”不是单一类别。普通 commit 新增历史且通常保留旧对象；`git push` 的 fast-forward 更新保留祖先历史；官方 [git-push 文档](https://git-scm.com/docs/git-push)明确指出非 fast-forward 更新可能丢失其他人的工作，远端 ref 删除也有独立语义。`git clean --force`会删除未跟踪文件，`reset --hard`会让工作树和 index 匹配目标状态。即使主 Agent拥有 Full Access，协议也必须区别这些影响。

## 选项

| 选项 | 自主边界 | 优点 | 代价 |
|---|---|---|---|
| A（推荐） | 分级授权：常规 additive/fast-forward Git 由主 Agent自主；会丢弃工作、重写已发布历史或删除远端 ref 的动作需用户对具体 intent 批准 | 日常协作不卡审批；不可逆风险仍由用户掌握；可随宿主能力机械门禁或审计 | 需要动作分类、审批摘要与执行后核对；Full Access 宿主可能只能逻辑约束 |
| B | 所有会修改 index/ref/worktree 或访问 remote 的动作逐次由用户批准 | 控制最严格；行为最容易追责 | commit/fetch/push 都阻塞，主 Agent难以承担持续协调职责 |
| C | 主 Agent在用户上限内完全自主，包括 force push、remote ref delete 和丢弃本地修改 | 自动化程度最高 | 一次误判即可丢失未提交或已发布历史；authority 交接时风险最大 |

## 选项 A 的动作级别

### L0：观察

本地 status/diff/log/show/rev-parse/cat-file/merge-base 等只读检查。核心可以自行运行受限 allowlist；主 Agent也可运行。无需 Git intent，但读取越过授权 roots 仍受项目权限约束。

### L1：常规可追加操作

主 Agent在明确 repository/ref scope 内可自主执行：

- 对指定 path set 执行 add/restore-staged，并创建包含已核对 checkpoint 的普通 commit；
- 创建本地 branch/tag、fast-forward 本地 branch，或在隔离 workspace 中形成结果 commit；
- fetch 指定已配置 remote/ref，普通 fast-forward push 到策略允许的目标 ref；
- 无冲突且不改写已发布 ancestry 的 merge/cherry-pick，以及显式创建 merge commit；
- 在确认 clean/已保留结果后清理系统创建的临时 branch/worktree。

每项仍需 `GitActionIntent`，但 policy 可以自动授权，无需等待用户。intent 必须绑定 expected before OID、checkpoint、path/ref allowlist 和 `authority_epoch`。

### L2：有损或历史重写操作

默认要求用户批准具体 intent：

- `push --force`、`--force-with-lease`、任何 non-fast-forward remote update、remote ref/tag 删除；
- 对已发布或其他任务依赖的 commit 执行 rebase/filter/history rewrite；
- `reset --hard`、`clean -f/-d/-x`、checkout/restore 覆盖未保存修改；
- 删除含未合并 commit/脏文件的 branch/worktree，prune 可能是唯一剩余副本的对象；
- 修改 coordination repo 的 remote URL、默认 publication ref、签名/credential/hook 配置；
- 绕过 hooks/signing/protection 的 flags，或运行任意 remote helper/custom upload-pack。

批准绑定 action digest、repository identity、before OID、精确 ref/path scope、预计 after OID（可得时）、风险摘要和短有效期。参数或状态变化使批准失效，不能复用“允许 force push”这种宽泛许可。

项目 policy 可以把 L1 提升为需审批，不能把上述 L2 降为普通 Agent可执行。未来若用户明确建立更宽的持久策略，可单独设计，不在首版默认范围内。

## `GitActionRequest` 与 `GitActionIntent`

调度中心请求是目标而非 shell：

- `kind`：checkpoint_commit、integrate_attempt、resolve_divergence、publish_checkpoint、refresh_remote_state、prepare_replica_handoff、cleanup_workspace 等受控 enum；
- project/lineage/replica/runtime、coordination root/repository ID、相关 task/attempt/checkpoint；
- desired outcome、required evidence、允许的 refs/paths/remotes、deadline；
- request revision、authority epoch、risk class 和 correlation/causation IDs。

主 Agent intent 补充执行计划：动作级别、expected before state、将修改的 refs/paths、remote target、是否可能重写/删除、回滚或保留点、简短理由。不得提交原始 shell 作为授权边界；实际命令可在受限审计字段中摘要化。

主 Agent也可主动提出 intent，例如发现需要提交 checkpoint。核心按同一 policy 决定自动授权、等待用户或拒绝；不能通过“主动”绕过级别分类。

## `GitActionReport`

完成报告至少包括：

- request/intent/approval ID、main agent ID、session/host、`authority_epoch`；
- repository/common-dir fingerprint 和 root ID；
- action kind、started/finished time、status；
- before/after HEAD/branch/ref OID，受影响 refs/path summary；
- checkpoint ID/hash、commit/tree OID、remote/ref 与 observed remote OID（适用时）；
- conflict/authentication/hook/signing/transport result code；
- stdout/stderr 的脱敏摘要和可选本地 artifact hash，不采集凭据或大段源码；
- Agent 对 outcome 的 `confirmed`、`partial` 或 `unknown` 置信状态。

核心收到报告后先检查 identity、epoch、intent digest 和时效，再运行本地只读 reconcile。能独立验证的本地结论标记 `core_verified_local`；远端结论保持 `main_agent_reported_remote`。报告不会直接改写 checkpoint ancestry。

## 失联、交接与外部操作

- Git action 开始后主 Agent失联，Operation 进入 `outcome_unknown`；不自动重试 commit/push/merge。
- 新主 Agent或用户先运行只读 reconcile，比较 before/after refs、工作树、checkpoint 和报告残片，再决定补报、继续或恢复。
- authority epoch 改变使尚未开始的 intent/approval 失效；已经启动的外部进程可能继续，系统只能按宿主能力取消并记录执行强度。
- 检测到没有 intent 的 Git 写入时，记录 `external_git_change_detected`，暂停依赖旧基线的新操作并请求当前主 Agent reconcile；不自动 reset 用户工作。

## 后续待细化

- L1/L2 动作分类的完整 enum、不同 repository role 的例外和 Windows Git 行为 spike。
- intent/approval/report schema、REST/MCP tools、消息 obligation 与 Operation 状态机。
- 主 Agent如何在多个 ProjectRoot/repository 间组织原子目标，及部分成功的补偿协议。
- hooks、签名 commit、LFS/submodule 和 provider branch protection 的首版支持范围。
