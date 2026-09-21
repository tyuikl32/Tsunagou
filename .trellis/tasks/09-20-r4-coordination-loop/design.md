# R4 设计与责任边界

细化 [PRD](prd.md)，公共语义以[独立成品方案](../../../docs/standalone/implementation-plan.md)及其引用的模块规范为准。

## 文件责任

- src/tsunagou/modules/cognition*、resources*、workspaces* 和 durability 附件端口
- src/tsunagou/application/queries/blackboard.py、跨模块准备/结果 workflow
- 真实临时 Git/多 root 文件夹测试、Lease 注入时钟测试和附件授权测试

路径带“待建”或包含规划目录时，按现有代码逐模块迁移；不得保留旧单文件和新包中的两套独立实现。

## 设计约束

1. 分歧的业务判断与协调由主 Agent 完成；内核只检查关联、结构、scope、版本、状态与接受槽，不引入自动语义裁判。
2. 修改 proposal 或参与者集合使旧接受失效；接受绑定 digest，不能用 report 存在代替 contract 生效。
3. Lease 默认 TTL 120 秒、running bridge 每 30 秒续租；资源后台到期处理有事务边界。claimed 预留不冒充 X 执行授权。
4. shared 只表示 M1 支持的一条明确选择路径，不设为所有任务隐含默认。Git mutation 仍由 main 决定和执行。
5. 文件扫描与 blob 流式 I/O 在事务外执行，用 Operation/Job 和 expected revisions 回写；至少准备、执行前、结果检查点核验真实文件。

## 依赖与交接

开始前读取 R3 的验收记录，确认产物可从正常入口使用。依赖有缺陷则先回补，不能临时绕过。

后继任务复用公开端口、DTO、持久数据与运行结果。workflow 组合端口，领域事实归所属模块。成功响应和日志不得含控制秘密。

## 验证方法

1. 用两个独立 principal 通过实际 API 构造认知分歧、协商和契约变化，检查 start 的正反结果。
2. 使用临时 Git 项目执行真实文件写入、测试、结果采集与 patch 下载，验证字节/hash。
3. 模拟同物理路径 alias、资源部分冲突、TTL 到期、检查点间手改文件；断言不越权、不部分授予、不静默覆盖。

故障操作和停止条件见[调试执行单](../../../docs/standalone/debugging-runbook.md)。实际结果写入 implement.md，不能只以任务状态表示验证成功。
