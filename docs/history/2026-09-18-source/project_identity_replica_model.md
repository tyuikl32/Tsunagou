# 项目身份、Git 副本与活动写入权

> 核对日期：2026-09-17。
> 状态：第 155 题已确认选项 A；作为 D78 的项目副本基线。

## 问题边界

同一个协调仓库可以被普通 `git clone` 到多个目录，也可以通过 `git worktree` 建立多个 linked worktree。两者不能使用同一套运行身份：

- 普通 clone 有独立的 Git repository/common directory；它从共享 `.tsunagou/` 恢复协作上下文，但拥有自己的 `.tsunagou/local/state.sqlite3`。
- linked worktree 与主工作树共享 Git common directory，只把 `HEAD`、index 等少数文件按 worktree 分开。Tsunagou 创建的任务 worktree 属于同一项目副本的执行环境，不是新项目副本。
- SQLite 只对一个本机运行代次权威，Git 共享 checkpoint 只允许可证明的 fast-forward 自动导入。两个 clone 同时写入会产生两个合法但分叉的本地历史；普通 Git 合并不能替代租约、任务 owner 和权限状态的业务收敛。

官方依据：

- Git 的 [git-worktree 文档](https://git-scm.com/docs/git-worktree)说明 linked worktree 与主仓库共享大部分 repository 数据，只有 `HEAD`、index 等为 per-worktree。
- Git 的 [git-rev-parse 文档](https://git-scm.com/docs/git-rev-parse)分别提供 `--show-toplevel` 与 `--git-common-dir`，足以区分工作树根和共享 repository identity。
- Git 的 [git-clone 文档](https://git-scm.com/docs/git-clone)将 clone 定义为新目录中的新 repository；即使共享同一 `.tsunagou/project.toml`，它也应有新的本机副本身份。

## 三层身份

| 身份 | 存放位置 | 生命周期 | 用途 |
|---|---|---|---|
| `project_id` + `lineage_id` | Git 跟踪的 `.tsunagou/project.toml` | 随 clone 保留；显式 fork/reinitialize 才改变 | 标识逻辑协作项目及 checkpoint 因果谱系 |
| `replica_id` | Git 忽略的 `.tsunagou/local/replica.toml` 和用户注册表 | 每个独立 clone 首次注册时新建 | 标识这一份本机可写状态和路径绑定 |
| `runtime_epoch` | 当前 replica 的 SQLite | 每次从共享层重建、恢复性接管或明确重启代次时新建 | 使旧 session、lease、token 与 event sequence 不会跨代复活 |

`replica_id` 不因目录重命名自动改变；注册表更新规范路径并再次验证 `project_id`、`lineage_id` 和 Git common directory。复制整个工作目录时如果复制了 `local/`，注册必须识别路径/common-dir 不匹配并拒绝复用 replica identity。

## Worktree 与 clone 判定

注册时记录并交叉核对：

- `git rev-parse --show-toplevel` 得到当前工作树根；
- `git rev-parse --path-format=absolute --git-common-dir` 得到 repository common directory；
- `.tsunagou/project.toml` 的共享身份与当前 checkpoint；
- 本机 `replica_id`、规范化路径和 common-directory fingerprint。

同一 common directory 下的 linked worktree 归属于同一 replica。由 Tsunagou 管理的任务 worktree 只能作为 workspace 资源登记，不能打开自己的项目 SQLite、获得项目 writer role 或物化 `.tsunagou` 共享状态。

不同 common directory 但共享相同 `project_id`/`lineage_id` 的目录视为独立 replica。remote URL、目录名和分支名不参与项目身份判断，因为它们都可变且不唯一。

## 选项比较

| 选项 | 规则 | 优点 | 主要代价 |
|---|---|---|---|
| A（推荐） | 每个用户级 daemon 对同一 project/lineage 只允许一个活动可写 replica；其他 clone 可登记为 standby，只读检查共享状态；切换必须执行 checkpoint 与显式接管 | 保持 SQLite 单写权威；与 fast-forward-only 导入一致；异常恢复可审计 | 在两个 clone 间切换多一步；跨机器只能检测分叉，不能靠本机锁预防 |
| B | 同一机器允许多个 clone 同时写，各自在 checkpoint 时尝试实体级自动合并 | 多目录并行最自由 | 任务 owner、租约、权限、消息 ACK 和副作用无法用通用 merge 安全收敛；实质上需要分布式多主协议 |
| C | 每个 clone 自动成为新 `project_id`，不共享协作身份 | 实现最简单；不会发生本地多主 | clone 后无法延续任务、契约和历史，违背项目内持久化与跨机器恢复目标 |

## 选项 A 的具体语义

### 活动副本

- 用户级 daemon 注册表记录每个 `project_id`/`lineage_id` 的 `active_replica_id`；daemon 自身的单实例锁使本机选择唯一。
- 只有活动 replica 可以打开 SQLite 为读写、签发 Agent 凭据、推进任务、持有资源租约和物化 checkpoint。
- standby replica 只允许 `doctor`、状态比较、导入预检和激活预检；它不能使用另一 replica 的 SQLite 或凭据。
- 该约束只在当前用户安装范围机械强制。首版没有跨机器分布式租约；两台机器同时活动时，通过 checkpoint 父哈希分叉检测停止写入。

### 正常切换

`project activate <path>` 先对当前活动 replica 执行切换屏障：

1. 阻止新 claim、session attach 和副作用 job 入队；
2. 要求没有 `running`、`cancel_requested` 或 `orphaned` attempt，没有活跃资源 lease 和 outcome-unknown operation；
3. 清空 materialization outbox，完成 checkpoint，并验证目标 replica 能 fast-forward 到该 checkpoint；
4. 撤销旧 replica 的 session/token family，关闭 SQLite，更新活动登记；
5. 目标 replica 导入 checkpoint，创建新的 `runtime_epoch`，再开放写入。

如果目标工作树有未提交的 `.tsunagou` 共享修改、checkpoint 分叉或未知格式，激活进入诊断状态，不自动覆盖。

### 恢复性接管

旧活动路径损坏、离线或 daemon 非正常退出时，用户可执行显式 takeover。内核必须：

- 验证目标共享 checkpoint 与已知 last checkpoint 的祖先关系；
- 创建新的 `runtime_epoch` 和接管审计事件，使旧代次的 lease、session、token、job claim 全部失效；
- 对没有停止证据的外部进程和不可验证副作用建立 residual-risk/outcome-unknown 记录；
- 若 checkpoint 已分叉，保持只读并进入既定的显式分歧解决流程。

恢复性接管不声称终止另一个目录或另一台机器中的 Agent；它只改变当前 daemon 接受谁写入。

## 实现影响

- 项目模块拥有 shared identity、replica registration、activate/takeover/archive 状态机。
- 持久化模块验证 checkpoint ancestry，执行切换屏障并生成新 runtime epoch。
- 身份模块在 token/session 中绑定 `replica_id` 和 `runtime_epoch`；切换后旧凭据必然失效。
- 工作区模块用 Git common directory 判断 linked worktree 归属，禁止任务 worktree 成为项目 writer。
- CLI 至少需要 `project register`、`project replicas`、`project activate`、`project takeover` 和 `project doctor`，JSON 模式返回稳定 reason code 与阻塞项。

## 后续待细化

- `project_id` 与 `lineage_id` 在显式 fork、backup restore、reinitialize 中各自何时变化。
- 正常 activate 与恢复性 takeover 的完整 Operation 状态机、阻塞 reason code 和回滚点。
- 用户级注册表的格式、锁、损坏恢复与路径移动协议。
- checkpoint 分叉的实体级三方合并输入与敏感冲突升级规则。
