# 跨模块流程与事务清单

实现位置 `src/tsunagou/application/workflows/`。流程层持有公开端口与共享 UoW，没有自有领域表。外部动作与逻辑提交分开，所有恢复依赖持久 Operation 阶段。

## 初始化与首个主 Agent

1. user_control 指定已有 Git 仓库。projects 验证 root/repo identity，durability 取得项目 lock 并创建 SQLite/genesis 待物化记录；Project active、Authority unassigned。init 失败不能留下被当作成功的 registry。
2. materializer 落盘 `.tsunagou` 共享结构和本机忽略配置。尚无 commit 可运行，明确显示 unanchored，不阻塞普通协作。
3. user 或已任命 main 签发适当 ticket。agents 兑换完成 identity/probe/Grant 事务；malformed 全回滚，能力不足保留 diagnostic-only。token 交付丢失走 rebind，不随机创建第二 Agent。
4. user 任命 ready Agent，projects 签发 main_authority，agents 更新 authority epoch，同事务事件。主 Agent 提示中包含 Git 职责、用户边界与黑板入口。

## 从任务到结果

main create→选择任务范围与工作区策略→ready→publish；Worker begin 一次取得 Attempt、基线、资源占用和执行授权，完成后 submit 自动采集结果，main review。

begin 的领域写在一个 UoW 成功或整体回滚；文件观察/物化在写事务外。submit 固化 Result 并释放占用、撤执行 Grant、通知 main；review 接受普通任务，项目完成仍需用户。

## 分歧、等待与恢复

报告触发确定性规则或参与者显式创建 Discrepancy；cognition 保存协商和契约，participants 接受 exact hash。需要用户方向判断时 main 创建 UserDecision 和精确 action blocker；相关 owner 提交 SuspensionSnapshot，释放 Lease，Task blocked，正常结束当前 LLM 轮次。

用户批准/拒绝只解决决定，不自动恢复执行。相关 owner 挂起后重新读取黑板和任务版本，再 begin；无关任务继续，没有用户等待计时器。

## 主权限移交和 Agent 继任

handoff 先建立 transition 并冻结旧执行授权；旧 holder 仅 H Grant 允许报告/释放/停止。target 在用户 ceiling 内明确 adopt，不足 scope 的对象保持 blocked。120 秒执行收敛窗口不替用户决定，不证明物理进程已停止。

succession 一个 UoW：校验 revisions→关闭旧 Attempt、撤 Grant/Lease→建立新的责任或重新开放 Task→supersede 待响应义务→创建新契约 proposal→事件与 outbox。Workspace 不自动转移。外部停止由 Operation 跟进，outcome_unknown 仅阻塞相交动作。

main 可以在可授权范围内留证接受风险、证明结果或授权新 Operation；原 unknown 历史不改写。重大冲突、用户保留动作或越过 ceiling 才交用户。普通子 Agent 不能确认自己接管主 Agent 任务。

## 完成、归档与重激活

1. objective owner 或 main 创建 CompletionProposal，含精确目标、证据、未解决事项与 project revision。此时其自身 Attempt 可以仍在收敛。
2. 确认前所有 current Attempts 逻辑关闭，执行 Grant/Lease 归零。每项完成/取消/失败/封存有 reason；离线不等于 stop，残余外部风险明确交用户核对。
3. user_control 确认 exact digest/revisions。一个 UoW 写 Project completed、decision approved、completion event、强制 checkpoint Operation/outbox；没有 completing。
4. checkpoint 后续失败不撤销 completed；只阻塞依赖该证据的归档完成、发布、迁移。查询、repair、撤权仍可用。
5. archive Operation 等待 barrier 再 archived、结束 sessions、卸载 runtime；unanchored 不自动禁止 local archive。
6. reactivate 由 user 或完成前 policy 已授权 main 发起，新 runtime，不恢复旧执行权。main 路径先验证旧授权，再要求显式建立新 session/Grant；无法建立新会话就 unassigned 等待用户，不能复活 token。非终态 Task 显式 restore_open，completed 只可 follow-up。

独占 daemon 的进程收尾：仅对本次运行收到并提交的 `project.completion.confirm`，在对应 checkpoint Operation 成功且确认响应发送完毕后优雅退出。失败或未完成时保留运行，原 Operation 在同次运行重试成功后可触发退出。退出判断与项目注册共用锁；共享 daemon 保持运行。该收尾不等于归档，不改项目状态、权限或协议字段，不扫描历史完成项目，也不增加空闲计时或控制台自动启动策略。

## checkpoint 回退与 replica 切换

同 lineage 正常恢复保留历史，按 fencing 重建 runtime/session；clone 新 replica 不携带另一台机器运行权限。激活核验 checkpoint、恢复证据和本机唯一 writer；旧 writer 不可协调则明确 user takeover，没有分布式锁承诺。

回退旧 checkpoint/empty：旧 lineage 封存并生成最终 checkpoint；新 manifest/genesis 经 barrier 切换；新 replica/runtime、Authority unassigned；全部 ticket/token/session/Grant/Lease/worker claim 失效。只导入领域历史，非终态 Task blocked/recovery_review，无 current Attempt。用户重新任命后 main 显式恢复所选任务。

切换中崩溃按 Operation 阶段和不可变 manifest 恢复，不凭半文件猜活动身份。sealed 历史可读；跨 sealed 合并和独立项目 fork 首发不做。同 lineage 分叉按共同祖先三方消歧。

## 失败映射

| 情况 | 保持的事实 | 恢复 |
|---|---|---|
| DB 事务失败 | 无部分任务/Grant/消息变更 | 原 command_id 重试 |
| commit 后响应丢失 | 业务只执行一次 | 幂等重放；秘密交付丢失专门 rebind |
| push/SSE 失败 | 持久 inbox 仍在 | pull sync |
| 长时间静默或断线 | 不能据此推断宿主已停止 | 保留 owner/占用；owner 显式 block 或 main recover 才释放 |
| Git 效果不明 | 已提交逻辑责任不回滚 | unknown、核验、显式 Resolution |
| checkpoint 失败 | DB 已提交状态仍成立 | repair、barrier，不撤销用户完成 |
| 用户未回答 | decision pending、相关 Task blocked | 持久等待，无关任务继续 |
