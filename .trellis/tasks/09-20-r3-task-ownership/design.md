# R3 设计与责任边界

细化 [PRD](prd.md)，公共语义以[独立成品方案](../../../docs/standalone/implementation-plan.md)及其引用的模块规范为准。

## 文件责任

- src/tsunagou/modules/tasks*、projects 授权端口、agents 会话读取端口
- src/tsunagou/application/workflows/ 与 interfaces/API task handlers
- 任务授权、状态机、并发和跨模块事务集成测试

路径带“待建”或包含规划目录时，按现有代码逐模块迁移；不得保留旧单文件和新包中的两套独立实现。

## 设计约束

1. Task owner、session、attempt 和 epoch 共同绑定执行操作；main 身份不构成任意接管，换 owner 必须显式恢复/继任，M1 不偷加继任捷径。
2. TaskExecutionWorkflow 仅组合公开领域端口，无自有领域表、私有字典读写或绕过 ports 的 _save。
3. 只存在一个 PreflightResult，记录 input_digest、attempt、各领域 revisions、blockers 和有效状态；start 在同一写事务重验。
4. R4 尚未闭环的准备条件应明确阻塞。R3 集成用实际已持久化领域事实构造前置条件，不能在生产路径默认 ready=True。
5. 用户是 U 主体，不借 main token 审查任务。用户待决只影响相应 blocker，resolve 后不会自动 start。

## 依赖与交接

开始前读取 R2 的验收记录，确认产物可从正常入口使用。依赖有缺陷则先回补，不能临时绕过。

后继任务复用公开端口、DTO、持久数据与运行结果。workflow 组合端口，领域事实归所属模块。成功响应和日志不得含控制秘密。

## 验证方法

1. 对照 F03/F06-F09 通过公开入口重现越权与部分写入，断言状态及关联表没有变化。
2. 并发 claim、陈旧 preflight、依赖 revision 变化、缺 Lease、错误 attempt 的用例必须落到同一个生产 workflow。
3. 覆盖 running→blocked→resume、submit→review.accept、request_changes→新 Attempt；验证项目仍 active。

故障操作和停止条件见[调试执行单](../../../docs/standalone/debugging-runbook.md)。实际结果写入 implement.md，不能只以任务状态表示验证成功。
