# Git 持久性证据的作用域

> 核对日期：2026-09-17。
> 状态：第 158 题确认区分本地与远端轴；第 160 题及后续澄清规定远端 Git 由主 Agent执行。远端轴来源为 `main_agent_reported`，不是 core 独立在线 evidence。

## 需要区分的事实

- checkpoint 已物化到工作树，只证明当前目录有文件。
- checkpoint 已进入本地 commit，只证明当前 Git object database 与可达 ref 中有内容。
- checkpoint 已发布到远端 ref，才提供从该远端重新获取的证据。
- 上述任何证据都不保证永久备份：本地仓库可删除，远端 ref 也可能被强制更新或删除。系统记录的是带时间、对象 ID 和来源的观察事实。

Git 官方文档明确分开这些动作：

- [git push](https://git-scm.com/docs/git-push)更新远端 ref 和关联对象；本地 commit 本身不会更新远端。
- [git ls-remote](https://git-scm.com/docs/git-ls-remote)显示远端仓库当前公开的 ref 与 commit ID，可作为一次远端观察。
- [git fetch](https://git-scm.com/docs/git-fetch)下载历史并更新本地 remote-tracking refs；remote-tracking ref 只代表上次 fetch 的结果，不等于远端当前值。
- [git merge-base --is-ancestor](https://git-scm.com/docs/git-merge-base)可验证 anchor commit 是否为已知远端 tip 的祖先，但前提是相关对象已在本地。

## 选项

| 选项 | 对外状态模型 | 优点 | 风险与代价 |
|---|---|---|---|
| A（推荐） | 分别跟踪本地 commit anchor 与远端 publication evidence；本地锚定不宣称跨机器可恢复 | 语义准确；离线可工作；未来支持多个 remote/离线 bundle 时可扩展 | API/UI 多一维状态，需要显式远端验证 |
| B | 有本地 commit 就统一标记 `anchored`/可恢复，远端状态不属于调度中心 | 模型最简单；不需要网络检查 | 用户可能把本地 commit 误解为 clone 可恢复；无法为切换机器提供可靠预检 |
| C | 只有验证远端 ref 包含 checkpoint 才称为 anchor；本地 commit 仍算 unanchored | 跨机器语义最严格 | 离线、本地专用仓库和无 remote 项目长期处于警告态；远端故障会影响本地生命周期判断 |

## 选项 A 的两个状态轴

### Local checkpoint coverage

- `none`：没有 checkpoint 被验证存在于本地可达 commit。
- `current`：当前最新封存 checkpoint 已由本地可达 commit 覆盖。
- `lagging`：存在本地 commit anchor，但最新 checkpoint 晚于它。
- `diverged`：当前共享状态与已登记 checkpoint ancestry 不可 fast-forward。
- `unavailable`：Git 元数据暂时无法读取；保留上次证据但不提升状态。

每条 local anchor evidence 至少记录 `checkpoint_id/hash`、commit object ID、tree ID、ref/reachability snapshot、repository common-dir fingerprint、verified_at 和 verifier version。只有 commit tree 中的 manifest 与全部引用文件 hash 验证成功才建立证据。

### Publication report state

- `unconfigured`：项目没有指定可移植恢复所使用的 remote/ref 目标。
- `unreported`：存在目标，但当前主 Agent尚未提交适用于当前 checkpoint 的远端结果。
- `reported_current`：当前主 Agent报告远端 ref 等于或包含当前 checkpoint 的 anchor commit。
- `reported_lagging`：主 Agent报告远端只覆盖较早 checkpoint。
- `reported_diverged`：主 Agent报告远端与预期 ancestry 分叉。
- `outcome_unknown`：远端动作已开始但主 Agent/宿主失联，或报告明确无法确认结果。
- `unavailable`：主 Agent报告认证、网络、transport 或 provider 拒绝；不得误写成 unpublished。

publication report 记录 main agent/session/host、`authority_epoch`、Git action request/intent、remote target ID、完整 ref、before/observed/after OID、覆盖 checkpoint、reported_at 与结果。凭据和带 secret 的 URL 不进入事件或共享文件。

## 核验原则

- daemon 不运行任何远端 Git 命令。当前主 Agent在其 Full Access 宿主中执行远端查询、fetch/push 等动作，再提交结构化 `GitActionReport`。
- 核心验证报告的身份、权限、authority epoch、request/intent digest、目标快照、字段一致性和时效；能在本地对象库证明的 commit/checkpoint/ancestry 部分另标 `core_verified_local`。
- 远端结论始终保留 `main_agent_reported_remote` provenance。即使报告附带命令输出 hash，也不能标成 core 独立观察。
- 主 Agent不能仅因 remote OID 与本地不同就报告分叉；应先取得足以判断 ancestry 的对象或明确返回 inconclusive。
- 只使用项目绑定的完整 ref，不用远端 `HEAD` 猜默认分支。主 Agent执行时发现 remote/ref 配置变化，应中止旧 intent 并重新申请。
- 报告有时效；跨机器切换或清理最后副本前需要当前主 Agent重新核验。新报告可降低当前状态，但不删除旧审计记录。

## 与共享状态的关系

- local anchor evidence 与 publication report 是 SQLite 中来源强度不同的审计事实；后续 checkpoint 可以物化摘要，但不能把“包含自身 commit”的信息写进被该 commit 承载的 checkpoint。
- remote 名称和凭据是本机配置。Git 共享策略可声明“发布证据是否为某些生命周期操作的前置条件”，但不能提交用户机器上的 secret URL。
- 普通 clone 注册时从共享 checkpoint 恢复，再独立验证它来自哪个本地 commit/ref；源机器的 publication report 只作为历史记录，当前主 Agent必须重新核验远端状态。
- project fork、replica 切换、lineage reset 或本机最后副本清理所需的证据强度单独定义，不由一个模糊 `anchored=true` 推断。

## 后续待细化

- 主 Agent Git 动作的自主/审批分级、report schema 与 outcome-unknown reconcile。
- publication report 的默认有效期、目标绑定和不同宿主可提供的远端证据摘要。
- 是否支持 Git bundle、外部备份目录或签名 release tag 作为其他 portability evidence。
- 哪些高影响动作要求 local coverage，哪些要求新鲜 publication evidence。
