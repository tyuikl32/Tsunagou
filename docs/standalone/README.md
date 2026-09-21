# 从当前代码到独立运行的最小成品

日期：2026-09-21。检查工作树：当前未提交改动。本文以真实命令、测试和临时项目结果为准；不把宿主能力检测、证据收集或研究实验作为本轮最小成品的前置条件。

**M1 的十二条最小产品验收标准已通过，成品可独立启动和运行；原始八模块的完整设计仍有后续范围。** 任务/认知/消息、shared 文件观察、review、真实 daemon 提交窗口、过期 Job lease 机械恢复、checkpoint 失败查询与 retry、用户确认和重启恢复均有入口证据。主动 Job runner、完整 lifecycle、worktree/external、真实宿主正式基线等列在后续 R1-R6 范围，不冒充 M1 已支持行为。逐条结果见 [M1 验收记录](m1-acceptance-2026-09-21.json)。

## 阅读与执行顺序

1. [现状与八模块缺口](status-and-gaps.md)：已有代码能做什么、缺什么、与原设计的距离。
2. [独立成品实施方案](implementation-plan.md)：交付范围、六个实施包、文件责任、事务、接口、错误和完成标准。
3. [启动与调试执行单](debugging-runbook.md)：当前即可执行的审计和启动；修复后的操作流程与逐项调试办法。
4. [本次真实 HTTP 审计结果](audit-2026-09-21.json)：当前 16/16 通过；它只覆盖已装配后端的回归，不代表 M1 全部完成。
5. [双 bridge MCP 协作烟测](bridge-two-session-smoke-2026-09-21.json)：两个独立认证 bridge 的首轮协作通过。
6. [M1 公开入口烟测](m1-public-smoke-2026-09-21.json)：从空项目启动、用户确认、checkpoint 到 daemon 重启恢复通过。
7. [独立安装包烟测](package-smoke-2026-09-21.json)：Python wheel 与 Node bridge 在源码树外安装启动通过。
8. [checkpoint 失败语义测试](checkpoint-failure-2026-09-21.json)：真实 daemon 中用户完成结论在物化失败时保留，失败 Operation 可查询并可通过用户 CLI retry 物化。
9. [多根项目边界烟测](project-roots-smoke-2026-09-21.json)：主 Agent 登记/绑定额外目录、登记仓库并通过 HTTP 脱敏查询。
10. [认知与契约动作烟测](cognition-contract-actions-2026-09-21.json)：分歧推进/解决、契约拒绝/撤回的公开入口和主体边界。
11. [Lease 后台维护证据](lease-maintenance-2026-09-21.json)：过期 Lease 的 orphan、撤权和 SQLite 事件回收。
12. [提交窗口故障证据](commit-window-2026-09-21.json)：确定性注入覆盖提交后响应丢失的幂等重放。
13. [真实 daemon 提交窗口证据](commit-window-process-2026-09-21.json)：真实子进程在提交前/提交后退出，重启后按 command_id 重放。
14. [M1 / R1–R6 Trellis 路线图](../implementation/roadmap.md)：当前唯一活动任务组；R1/R2/R3/R4/R5/R6 均已有部分代码证据，尚以全量 M1 门禁为关闭条件。

审计可重复执行：

```powershell
Set-Location D:\Tsunagou
.\.venv\Scripts\python.exe tools/dev/audit_standalone.py
```

当前预期退出 0。退出 1 表示发现产品断言失败；退出 2 表示审计没完成。脚本在临时 Git 项目启动真实 uvicorn，调用 HTTP，终止/重启进程，完成后清理临时文件。不会连接用户 IDE、调用模型或修改实际用户项目。测试身份仅用于后端请求，不声明任何宿主兼容性。

## 本轮最小成品 M1

一个本机 daemon，由 CLI 启停；项目状态保存到协调 Git 仓库内；用户接入一个主 Agent 和一个独立 worker；二者通过自己的 stdio MCP bridge 查询项目、收发消息、报告理解和接受契约。worker 领取任务，在明确选择的共享工作区写入真实文件、运行测试、提交结果，由指定审查者验收。用户能够处理重大决定和确认项目完成。daemon 重启后事实仍在，旧执行授权不会直接恢复。

模型由已有 Agent 宿主提供，后端不内置 LLM，也不要求额外模型密钥。八模块都必须具有这条流程实际用到的功能。多宿主同时认证、20 次对照实验、Web 工作台、跨机器恢复和复杂隔离驱动不阻塞 M1。

上述是阶段性交付范围，不删除[完整原设计](../implementation/README.md)。原设计中的主 Agent 控制 Git、用户保留决定、独立会话身份、SQLite 原子性、自然语言业务判断继续有效。不得用硬编码 `supported` 或取消所有权检查换取运行成功。

## 与旧任务的关系

用户于 2026-09-20 要求关闭全部旧 Trellis 任务。历史目录中的 27 项均已归档：20 项保留 completed，7 项 cancelled（放弃），其中包含此前单独归档的 bootstrap 与文档任务。[迁移清单](trellis-transition-2026-09-20.json)记录原状态与归档位置。

旧代码可复用，但旧 completed 不证明功能已接入产品。当前按新建的 [M1 总任务](../../.trellis/tasks/09-20-tsunagou-m1/prd.md)与 R1–R6 推进，T 编号仅用于追溯。R1/R2 的协议资源、统一 SQLite、回滚、真实 CLI 和 daemon lifecycle 已有实现证据；R3 当前 in_progress，R4-R6 仍为 planning，不能把当前 16 项审计当作 M1 完成。
