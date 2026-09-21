# T16 HTTP、MCP、CLI、黑板与运行提示

> 2026-09-20：按用户要求关闭旧计划并归档。保留原分项完成记录，不表示独立成品已交付。 当前执行入口：[M1 路线图](../../../../../docs/implementation/roadmap.md)。

状态：已规划，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- FastAPI routers、共享MCP、Typer CLI
- 一致读Blackboard与版本化提示资产
- OpenAPI artifact、用户操作runbook

## 前置依赖

T15, T07。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 逐条暴露同一CommandPolicy/handler，落实REST headers/ETag/problem和MCP工具投影
- 实现user CLI控制入口与--json/退出码、config provenance/doctor
- 实现黑板single read snapshot、bounded sections、敏感过滤和详情入口
- 实现核心prompt fragments/version/digest与attach/resume/task边界最小注入

## 验收标准

- [x] REST/MCP相同命令hash、权限和错误，user-only不出现在Agent tools（`CommandDispatcher` 与 FastAPI/MCP projection）
- [x] CLI可以初始化、接入、任命、查看/解决决定、恢复与查询Operation
- [x] 黑板不引入业务表，截断不漏身份/权限/阻塞
- [x] 生成OpenAPI零diff，命令目录覆盖率100%（`tools/codegen/generate_openapi.py`）

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。

## 本轮补充验收

- [x] CLI契约逐项映射已有U handler，Agent-only保留动作不出现在用户可执行help中；秘密不进入模型或CLI参数。
