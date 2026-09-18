# 多仓库任务的 Git 一致性模型

> 核对日期：2026-09-17。
> 状态：第 162 题已确认选项 A；作为 D85 的多仓库一致性基线。

## 事实边界

Git commit 从当前 repository 的 index 创建一个 commit，并推进该 repository 的 branch。Git 的 `push --atomic`只承诺一次 push 中的 refs 全部更新或全部不更新，而且服务端可能不支持；它不覆盖多个独立 repository 或多个 remote。

[Git submodule 文档](https://git-scm.com/docs/gitsubmodules)说明 superproject 的 gitlink 可以记录另一个 repository 的预期 commit OID。这能形成版本清单，但前提是项目本身采用 submodule；各 repository 的 commit、push 和权限仍然独立。Tsunagou 不应为了协调而擅自把用户的多仓库项目改造成 submodule。

因此首版只能保证调度中心内部的任务/租约/checkpoint 事务一致，不能宣称外部 Git 多仓库原子性。

## 选项

| 选项 | 模型 | 优点 | 代价 |
|---|---|---|---|
| A（推荐） | 用不可变 repository state vector 绑定任务基线和结果；多仓库集成是 parent Operation + 每仓库 child Git action 的 saga，部分成功后冻结并 reconcile | 支持真实多仓库项目；不虚构原子性；每一步可审计和恢复 | 状态机与补偿复杂；用户可能看到短暂部分完成状态 |
| B | 首版禁止一个任务修改多个 repository，强制拆成单仓库任务，最终由用户手工集成 | 实现简单；每个 attempt 基线清晰 | 跨仓库 API/客户端联动成为大量人工步骤，违背常见使用场景 |
| C | 要求所有多仓库项目改为 submodule/superproject，由一个 manifest commit 代表全局状态 | 有标准 gitlink 记录版本组合 | 入侵用户仓库结构；仍没有多 remote 原子 push；不适合任意外部仓库组合 |

## 选项 A：Repository State Vector

### Repository identity

- 一个或多个 ProjectRoot 可以落在同一个 Git common directory；它们归并为一个 `repository_id`，不能因 root 数量重复执行 Git action。
- 独立 common directory 产生不同 `repository_id`。本机 fingerprint 用于绑定路径；共享层使用用户声明的稳定 repository key/role，不提交绝对路径。
- repository role 至少区分 `coordination`、`source`、`dependency_readonly` 和 `external_managed`。coordination repository 唯一，其他仓库可为零到多个。
- submodule 被检测并显式登记时仍有独立 repository identity，同时保存 superproject/gitlink 关系；不能把嵌套目录简单视为普通 root。

### Vector fields

`RepositoryStateVector` 是按 `repository_id` 排序后 JCS/hash 的不可变对象：

- `vector_id`、project/lineage、schema version、created_at、created_by、purpose；
- 每项的 repository ID/role、相关 root IDs、Git object format；
- branch/detached 状态、HEAD commit OID、用于任务的 baseline ref/OID；
- worktree/index/untracked 的规范化状态摘要及 `clean` 标志；
- submodule/gitlink OID（适用时）；
- local checkpoint coverage 与已知 publication report 的引用，而非复制其可变结论；
- 对缺失/不可读/non-Git root 使用显式 status，不能用空 OID 表示。

Git OID 按 repository object format 保存为带算法的值，如 `sha1:<hex>` 或 `sha256:<hex>`；不得与领域 `sha256:` checkpoint hash 混淆。

TaskAttempt 在 claim/preflight 时绑定 `base_repository_vector_id/hash` 和实际影响的 repository subset。结果提交绑定 `result_repository_vector`、每仓库 diff/status evidence 和 GitActionReport refs。基线改变会使尚未开始的 preflight 陈旧；running attempt 进入 `baseline_changed`/协商，不静默换基线。

## 多仓库集成 Operation

### 前置阶段

1. 计算目标 repository set、预期 before vector、任务结果、契约和 checkpoint。
2. 原子取得所有相关 repository/ref/path 的逻辑 resource leases；任一不可得则全部不取。
3. 阻止依赖这些 refs 的新 claim/integration，等待或处理现有 attempt。
4. 要求 coordination state 物化并形成 checkpoint；每个 repository 的工作树状态满足 action plan。
5. 当前主 Agent提交一个覆盖完整 vector 的 `GitActionIntent`；策略按 D84 对每个 child action 分类，任何 L2 先完成用户批准。

### 执行阶段

parent `MultiRepoIntegrationOperation` 创建有序 child actions。默认顺序：

- 先准备/提交被依赖的 source repositories；
- 再提交依赖它们的 repositories；
- 最后让 coordination repository 的 checkpoint/manifest 引用最终 commit vector；
- 远端发布按依赖顺序进行，coordination publication 最后，使其不先宣称一个尚未发布的组合。

具体拓扑由显式 repository dependency DAG 决定；没有声明依赖时使用稳定 repository ID 顺序，但必须标记该顺序仅用于确定性，不代表业务依赖。

每个 child 完成后主 Agent提交 report，核心本地只读 reconcile 并持久记录 before/after。下一步只在前一步达到计划结果或经显式策略接受后开始。

### 完成与部分成功

- 全部 child 本地集成完成后生成 `integrated_repository_vector`；全部要求的 publication reports 到位后 parent 才进入 completed。
- 任一 child 冲突、拒绝、失联或 outcome unknown 时 parent 进入 `partially_applied` 或 `reconcile_required`，保留已成功步骤，不谎称回滚。
- 受影响 repositories、任务完成和新 integration 被阻塞；无关 repository 的只读/独立任务可继续。
- 主 Agent提出 forward-fix、显式 revert commit、继续剩余步骤或用户批准的有损恢复方案。已经 push 的 commit 默认只做新 commit 补偿，不自动重写远端历史。
- compensation 是新的 GitActionIntent/report 链，不能删除原 child 记录。最终 vector 记录实际收敛结果以及所有中间 OID。

## 不提供的保证

- 不保证多 repository commit、push 或 branch protection 审批原子完成。
- 不在普通任务中自动创建 submodule、monorepo、临时 remote 或跨仓库 two-phase commit refs。
- 不通过删除已成功 commit/force push 来伪装事务回滚。
- 不假定所有 repository 使用相同 branch 名、remote 名、Git object format、签名策略或访问权限。
- 不把 coordination repo 的 checkpoint commit 当作其他 repository 对象已经存在于远端的证明。

## 接口与状态

parent Operation 建议状态：`queued`、`preflighting`、`awaiting_approval`、`prepared`、`applying`、`partially_applied`、`reconcile_required`、`publishing`、`completed`、`failed`、`cancel_requested`、`cancelled`。

取消只阻止尚未开始的 child；已启动 Git 外部动作遵循 outcome-unknown 规则。`failed` 仅用于确认没有外部部分结果或已按批准方案收敛的失败；存在未解释的部分状态时必须保持 `reconcile_required`。

REST/MCP 返回 parent、child refs、before/current/target vector 和 blockers。普通 Agent只读取与自身任务有关的 vector subset；只有主 Agent/用户可创建 integration intent 或完成 reconcile。

## 后续待细化

- repository registry、dependency DAG、nested repo/submodule 探测和稳定 repository key 的字段。
- vector 的 porcelain-v2 状态规范化、untracked 内容摘要与大型仓库性能预算。
- parent/child Operation 详细转移、幂等键、取消/恢复与消息 obligation。
- 多仓库任务在 shared/external driver 下的 workspace 绑定；D42 已规定自动 worktree 首版只正式支持单仓库。
