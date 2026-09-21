# R6 设计与责任边界

细化 [PRD](prd.md)，公共语义以[独立成品方案](../../../docs/standalone/implementation-plan.md)及其引用的模块规范为准。

## 文件责任

- pyproject.toml、package.json 和 bridge 构建/发布配置（按实际需要）
- tools/dev/smoke_standalone.py、tools/dev/package_smoke.ps1、tests/integration/standalone/、tests/fault_injection/（待建）
- docs/standalone/debugging-runbook.md、用户 CLI/接入文档和实际运行报告

路径带“待建”或包含规划目录时，按现有代码逐模块迁移；不得保留旧单文件和新包中的两套独立实现。

## 设计约束

1. 测试主体是安装产物与真实公开入口。现有单元测试继续保留，但无法代替 daemon/CLI/stdio 进程集成。
2. smoke 使用临时 Git 项目和独立会话；用 MCP 客户端驱动可复現协作，不要求外部模型 API 才能验证程序正确性。人工 Agent 接入步骤另行照单执行。
3. M1 验收只要求确定的本机产品行为；宿主正式支持、能力报告、对照实验不进入本任务的通过条件。
4. 一条安装入口必须包含所需 wheel 与 bridge 产物位置/依赖说明；不能让用户在源码目录中才能找到资源。
5. 故障注入只针对自建临时项目和进程，清理前验证绝对路径；保护实际工作区和用户改动。

## 依赖与交接

开始前读取 R5 的验收记录，确认产物可从正常入口使用。依赖有缺陷则先回补，不能临时绕过。

后继任务复用公开端口、DTO、持久数据与运行结果。workflow 组合端口，领域事实归所属模块。成功响应和日志不得含控制秘密。

## 验证方法

1. 逐项执行总方案第 6 节全部 12 条完成断言；使用真实 HTTP、CLI 和 MCP，不调用领域私有方法。
2. 在全新 venv、源码树以外重复相同场景；分别注入 commit 前后进程退出、Job 中断、重复消息与旧 epoch。
3. 执行锁定依赖安装及相关全量回归；操作单按干净环境逐条运行并登记输出，不能沿用旧审计数字当新结果。

故障操作和停止条件见[调试执行单](../../../docs/standalone/debugging-runbook.md)。实际结果写入 implement.md，不能只以任务状态表示验证成功。
