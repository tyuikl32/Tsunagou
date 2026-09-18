# 项目身份与历史谱系生命周期

> 核对日期：2026-09-17。
> 状态：第 156 题已确认选项 A；作为 D79 的身份生命周期基线。

## 为什么需要两个共享身份

单独使用 `project_id` 无法同时表达两件事：用户仍在操作同一个逻辑项目，以及该项目已经从旧 checkpoint 回滚并开始一条不能与旧记录混写的新历史。单独依赖 UUIDv7 也不够；[RFC 9562](https://www.rfc-editor.org/rfc/rfc9562.html)规定 UUIDv7 的时间排序与唯一性布局，并不定义项目恢复语义。

[PostgreSQL timelines](https://www.postgresql.org/docs/current/continuous-archiving.html#BACKUP-TIMELINES)提供了直接可借鉴的恢复原则：从过去状态恢复并继续产生记录时创建新 timeline，并永久保留它从哪个旧 timeline、哪个位置分出的历史。Tsunagou 的 checkpoint 父哈希负责验证祖先关系，`lineage_id` 负责标识当前允许继续追加的历史代次。

Git 的 commit ancestry 可以证明一个 checkpoint 是否可达，但 Git 仓库或分支名不能替代领域身份：分支可重命名，历史可 reset，同一 `.tsunagou` 内容也可存在于多个 clone。

## 选项比较

| 选项 | `project_id` | `lineage_id` | 影响 |
|---|---|---|---|
| A（推荐） | 用户眼中的逻辑项目；普通 clone、修复、归档/恢复和有意回滚均保持；只有“另建独立项目”才改变 | 当前可追加的历史代次；普通 clone/无回退恢复保持，回滚后继续、协作状态重置时改变 | 兼顾稳定项目引用与防止旧历史复活；需要让凭据、checkpoint 和导入都绑定 lineage |
| B | 每一条 fork/恢复分支都是新 project | 作为所有后代项目共享的历史家族 ID | 模型接近 Git 分支家族，但一次项目回滚会改变所有 API/配置引用；lineage 不能直接防止旧代次写入 |
| C | 所有场景只使用 project ID；删除 lineage | clone 保持 project，任何不连续恢复都生成新 project | 实现字段更少，但普通恢复与独立项目 fork 的语义被迫相同，用户级注册与外部引用频繁变化 |

## 选项 A 的身份定义

- `project_id`：逻辑协作命名空间。API 路径、用户注册表和跨模块外键使用它。它不是路径、remote URL 或 Git repository object ID。
- `lineage_id`：该项目当前持久协作历史的 incarnation。所有 checkpoint、共享快照、导入操作、恢复操作与长效凭据必须绑定它。
- `replica_id`：一个独立 Git clone 在一个 lineage 下的本机状态身份。lineage 改变时，即使目录未变，也创建新 replica identity。
- `runtime_epoch`：一个 replica 的可写运行代次。接管、从 SQLite/shared state 重建、归档后重新激活等需要废止运行态的动作会创建新值。

所有四者使用 UUIDv7，但含义只能由字段名和状态机决定，不能从 UUID 时间戳推断父子关系。

## 身份变化矩阵

| 操作 | project | lineage | replica | runtime | 必需的来源记录 |
|---|---|---|---|---|---|
| 普通 `git clone` 后注册 | 保持 | 保持 | 新建 | 新建 | imported checkpoint |
| 创建 linked task worktree | 保持 | 保持 | 保持 | 保持 | workspace/base commit |
| 仓库路径移动并重新验证 | 保持 | 保持 | 保持 | 保持 | old/new canonical path audit |
| 在另一台机器从当前 checkpoint 恢复 | 保持 | 保持 | 新建 | 新建 | imported checkpoint |
| 同一 replica 从不落后的 SQLite backup 修复 | 保持 | 保持 | 保持 | 新建 | backup ID/hash + current checkpoint |
| 项目归档后重新激活 | 保持 | 保持 | 保持 | 新建 | archive checkpoint |
| 项目完成后重新激活 | 保持 | 保持 | 保持 | 新建 | completion decision + completion checkpoint |
| 从较旧 checkpoint 回滚并继续写 | 保持 | **新建** | 新建 | 新建 | `supersedes_lineage` + branch checkpoint |
| 清空任务/协作状态后重新开始 | 保持 | **新建** | 新建 | 新建 | sealed old lineage + reset reason |
| 从 checkpoint 另建独立项目 | **新建** | **新建** | 新建 | 新建 | `forked_from` provenance |

“不落后的 SQLite backup”必须覆盖当前已知 checkpoint，或能通过 event/outbox 重放严格恢复到它。任何退回到祖先 checkpoint 后继续写的操作都属于新 lineage，不能伪装成普通 backup restore。

## 回滚与重置规则

lineage transition 是持久 Operation，不是直接改 `project.toml`：

1. 将旧 lineage 写入 sealed 状态，保存最终 checkpoint、原因、actor 和时间；
2. 目标必须是旧 lineage 中可验证的 checkpoint，或明确的 empty genesis；
3. 创建新 `lineage_id`，记录 `supersedes_lineage_id`、`branched_from_checkpoint_id/hash` 和 operation ID；
4. 创建新 replica/runtime，重建 SQLite，只导入该 checkpoint 允许携带的持久领域状态；
5. 使旧 lineage 的 credentials、leases、sessions、job claims 和未完成 outbox 永久失效；
6. 原子物化新的 project manifest 和 genesis checkpoint，再开放写入。

旧 lineage 的共享事件与 checkpoint 不删除。默认保留为审计/诊断材料，不能再成为写入目标。

## 独立项目 fork

`project fork` 表达用户希望从某个 checkpoint 开始另一个可独立推进的项目：

- 生成新的 `project_id`、`lineage_id`、`replica_id` 和 `runtime_epoch`；
- 新项目记录只读 `forked_from`，包括 source project/lineage/checkpoint/hash；
- 不复制 session、token、lease、delivery state、worker job 或 runtime telemetry；
- 共享策略、roots、已接受契约、任务快照等是否复制由后续 fork profile 决定；
- 新项目的后续 checkpoint 与源项目互不具有 fast-forward 关系，不能自动合并回源项目。

## 不变量

- 每条可写命令都在鉴权上下文中绑定 `project_id`、`lineage_id`、`replica_id` 和 `runtime_epoch`；客户端 body 不能覆盖。
- `project_id` 相同但 lineage 不同的状态不能在普通导入中混合；必须走显式 lineage transition/merge 设计。
- 旧 lineage 的 event sequence、revision 或时间戳不能作为新 lineage 的并发依据。
- `forked_from` 和 `supersedes_lineage` 只表达来源，不授予访问权，也不允许读取源项目秘密。
- 共享 manifest 更新必须和 genesis/seal checkpoint 通过 materialization barrier 一致落盘；半完成时项目保持只读恢复状态。

## 后续待细化

- lineage transition Operation 的具体状态、崩溃恢复与原子文件交换顺序。
- reset/fork profile 精确允许携带哪些领域对象，以及复制对象是否重发 ID。
- 被 sealed lineage 的查询 API、保留策略与用户可见审计格式。
- 多个 lineage 的实体级人工 merge 是否进入首版；当前默认不自动支持。
