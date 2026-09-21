# R2 设计与责任边界

细化 [PRD](prd.md)，公共语义以[独立成品方案](../../../docs/standalone/implementation-plan.md)及其引用的模块规范为准。

## 文件责任

- src/tsunagou/bootstrap/{container,runtime,settings}.py
- src/tsunagou/platform/db/、模块 infrastructure repository 和迁移
- src/tsunagou/cli/{app,client}.py、api lifespan、query ports 和恢复装配

路径带“待建”或包含规划目录时，按现有代码逐模块迁移；不得保留旧单文件和新包中的两套独立实现。

## 设计约束

1. sqlite3 ProjectDatabase/UnitOfWork 作为唯一事务连接；Alembic 负责迁移，不混用另一个 SQLAlchemy Session 开启所谓同事务。
2. 各模块拥有自己的关系表与 repository；Grant、UserDecision、CompletionProposal 归 projects，agents 负责会话和主身份。不能使用 all_state_json 替代领域数据模型。
3. server/container 统一装配八模块。CLI 只做传输、参数与展示，不 new 独立服务。读取通过 query port 与一个 ReadSnapshot。
4. M1 一个活动项目，仍支持多个 root/repository。daemon 未绑定已初始化项目时明确拒绝项目命令。项目初始化是显式流程。
5. 认证、epoch、幂等、revision 的顺序必须按总方案第 4 节执行。外部 I/O 交给 commit 后 Operation/Job，不长期占用写事务。

## 依赖与交接

开始前读取 R1 的验收记录，确认产物可从正常入口使用。依赖有缺陷则先回补，不能临时绕过。

后继任务复用公开端口、DTO、持久数据与运行结果。workflow 组合端口，领域事实归所属模块。成功响应和日志不得含控制秘密。

## 验证方法

1. 以真实 daemon 子进程测试 CLI→HTTP→SQLite 一致性；中途杀掉进程再启动，查询相同 IDs 和 revisions。
2. 为同键重试/异输入、事务中途异常、第二 writer、旧 epoch、JSON 导入失败增加集成断言。
3. 对照审计 F01/F02/F05/F11-F14 重现并关闭缺陷；旧审计器若因 R1 协议变化失效，迁移案例到正式入口测试，不能只删除失败项。

故障操作和停止条件见[调试执行单](../../../docs/standalone/debugging-runbook.md)。实际结果写入 implement.md，不能只以任务状态表示验证成功。
