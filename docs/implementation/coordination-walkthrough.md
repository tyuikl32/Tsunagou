# 一次三 Agent 协作的逐步事实轨迹

本文使用别名便于阅读：用户U、主Agent M、子Agent A（API）、子Agent B（调用方）。这些不是合法wire ID，真实请求使用UUIDv7。每一步都复用已注册命令；说明“什么事实成立、谁能写、何时commit”，不引入通用workflow DSL。

## 从用户操作到子 Agent ready

| 步骤 | 实际调用主体与动作 | 持久事实 | 此时仍不成立的事实 |
|---|---|---|---|
| 1 | U `project.initialize` | Project active，Authority unassigned，genesis Operation | 没有main；没有Agent |
| 2 | U为M所选宿主会话签worker票据；M bridge `agent.enroll` | 独立Agent/HostSession/能力快照，baseline满足则agent_base | 最先连接者不自动main |
| 3 | U `authority.appoint(M)` | current main=M，authority_epoch推进，main_authority | M不拥有任意其他Attempt |
| 4 | 用户打开A、B各自宿主对话；U或M各签worker票据 | 两份单次票据，受project/ceiling约束 | 票据不等于session，也不是权限声明 |
| 5 | A bridge、B bridge分别 `agent.enroll` | 不同Agent/session/token/conversation digest；各自ready | 加入项目不等于已经claim任务 |
| 6 | A/B query blackboard、self inbox | 分别拿到身份、职责摘要、blocking和详情入口 | 不能看到非收件人私信，不能接管父任务 |

步骤4的M只有在具备agent.enroll且scope可覆盖时才能签worker票据；主Agent也不能签主权限任命。用户不需要为每个普通子任务再批准一次。若宿主没有managed_launch，用户手动打开对话再attach即可，不牺牲共同基线。

两个enroll各自是单个UoW；不是“把票据发送给模型”再让模型填写actor。返回ready之前不能claim；degraded仅诊断。HostSession凭据由bridge保管，U只看receipt。

## 父任务与两个子任务

M拥有父任务P的Attempt。M创建TA、TB，parent_task_id=P，分别描述API字段和调用方适配。只有确实存在开始前置关系才建blocks边；parent自身不产生依赖。

M ready/publish；A `task.claim(TA)`，B `task.claim(TB)`。各自的Task→claimed并创建唯一owner Attempt。两个worker同时请求同一Task只能一个成功。M向哪个worker建议领取是业务协调，代码不自动给它选择owner。

claimed可提交cognition.report、risk.request、resource.intent等协调动作，不意味着已有文件执行权。M可继续父任务工作，也可自己block等待；系统不因为孩子未完成阻止其提交，也不因父终态取消孩子。

## 分歧与契约

A报告`status`可空，B报告`status`必填：两者以显式typed claims引用相同subject/equality key。固定规则或Agent显式创建Discrepancy，affected_actions仅涉及这项接口的任务。核心不从自由文本猜谁对。

参与者讨论后提交proposal Q1，required slots={A,B}，payload与slots共同计算digest H1。A/B各自 `contract.accept(Q1,H1)`，最后一个必需slot成功的事务使proposal accepted。ACK讨论消息不能代替这两条接受记录。

若A已接受后正文或参与者变了，必须Q2/H2并重新接受；不能将A的H1接受搬给H2。main proxy仅在既有policy许可时用独立命令、记录真实actor；这里的普通路径不需要用户介入。

## 准备、开始和协作执行

M risk.submit/workspace.select；A/B分别prepare workspace。worktree需要main实际执行Git后report，daemon只读核验。A/B在scope内acquire完整Lease set，preflight返回固定input revisions/digest，task.start事务重验后才running。

一次start必须同事务建立Task/Attempt运行事实、执行Grant与必要关联事件；资源/契约/workspace已变更则拒绝，没有部分执行授权。bridge每30秒续Execution Lease，不要求模型持续输出。Lease过期只使旧 Attempt orphaned 并撤销执行权，Task 回到 open 公共队列；不能反推物理宿主已停止，后来加入的合格 Agent 可以重新 claim。

## 等待用户时子 Agent 怎样工作

假设M认为需要改变项目整体API方向，建立UserDecision D并指明受影响actions。A正在写相关接口：先提交进展与SuspensionSnapshot，task.block，释放Lease并结束当前轮次。B若有不相交任务可继续；不是所有子Agent一起停机。

用户在CLI show D后resolve精确revision/digest。D解决不自动让A继续文件写；A稍后恢复对话，bridge重连/同步，读取黑板，owner显式resume到claimed，再准备Lease/preflight/start。无wake宿主由用户重开原会话，不要求新建Agent。用户几天不答也不自动reject/fail。

## 提交、返工与继任

A/B运行中记录workspace result，再task.submit，撤执行Grant/Lease，固定TaskResult和ReviewRound。指定reviewer、automated或已允self策略接受后completed；M仅在被指定reviewer时按对应Grant审查。项目整体完成仍须用户。

如果A会话真正丢失且无法证明连续性，不能让新A'拿同cwd冒充。M决定succession，关闭旧Attempt、新建责任、义务supersede并按需要重新契约；旧workspace/Grant/Lease不直接转移。外部停止未知只阻塞相交动作，证据与风险处置另记。

## 可核查的前后状态

| 动作 | 输入关键前提 | 成功后 | 竞争/失败 |
|---|---|---|---|
| task.claim | open+revision+ready session | 唯一claimed Attempt | 412或409，无第二owner |
| contract.accept | self slot+exact digest | 自己的Acceptance；全required才accepted | 旧digest拒绝，原接受记录不改 |
| task.start | claimed+当前preflight+lease/scope/epochs | running+执行Grant | 任一输入陈旧返回blockers/冲突 |
| task.block | current owner+允许状态 | blocked+快照，无执行Lease | 主Agent不能伪造别人的快照 |
| task.resume | 原owner连续session+恢复条件 | claimed，需后续start | 旧owner/继任后恢复拒绝 |
| user_decision.resolve | U+exact revision/digest | 持久决定与关联事务/Operation | 内容变化需重新审阅 |
| project.completion.confirm | U+提案+责任已收敛 | completed+必需checkpoint Operation | checkpoint失败保留completed |

T13先用simulator运行以上轨迹；T18–T21分别证明真实宿主能提供同一能力；T23注入故障。这个案例不证明现有宿主已兼容，验收必须保存actual版本/结果。
