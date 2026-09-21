# R1 设计与责任边界

细化 [PRD](prd.md)，公共语义以[独立成品方案](../../../docs/standalone/implementation-plan.md)及其引用的模块规范为准。

## 文件责任

- pyproject.toml；tools/codegen/；protocol/；src/tsunagou/protocol_data/（待建）
- src/tsunagou/generated/、interfaces/runtime.py、api/ 与 packages/protocol-types/
- tests/protocol/ 及独立安装资源测试（按现有测试目录落位）

路径带“待建”或包含规划目录时，按现有代码逐模块迁移；不得保留旧单文件和新包中的两套独立实现。

## 设计约束

1. 协议 Schema 是 DTO 真相，命令目录登记路由和权限，两者交叉校验。不得继续由 Markdown 推断空对象类型或把 optional 全改 required。
2. 路径参数、请求 payload 与 principal/envelope 分开；flat 仅适配已有 bridge，再进入同一鉴权/执行入口。不得复制领域 handler。
3. 只为 M1 清单接通接口；其他动作保留明确未实现状态，不返回成功。不得扩展 U 权限或创建 root.register.user。
4. R1 完成协议与包资源基础；统一数据库事务、真实 CLI 由 R2 接入。R1 不能以临时内存实现宣布 M1 已完成。

## 依赖与交接

本任务是新计划起点；以当前审计和已锁定技术栈为基线，不等待旧宿主/实验任务。

后继任务复用公开端口、DTO、持久数据与运行结果。workflow 组合端口，领域事实归所属模块。成功响应和日志不得含控制秘密。

## 验证方法

1. 执行已有协议/fixture 检查与相关 Python/TS 测试，新增 optional、未知字段、path 冲突和版本拒绝案例。
2. 按调试执行单 A5 的隔离安装步骤定位现状；修复后在全新 venv 验证包资源，从临时 cwd 构建入口。
3. 对同一业务输入分别走 REST 和 flat，断言规范命令、错误和版本行为相同。不得用仅导入 Python 类的测试替代入口契约。

故障操作和停止条件见[调试执行单](../../../docs/standalone/debugging-runbook.md)。实际结果写入 implement.md，不能只以任务状态表示验证成功。
