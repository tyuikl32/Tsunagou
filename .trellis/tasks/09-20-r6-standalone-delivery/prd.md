# R6 封装、回归与独立交付

状态：planning（实施计划就绪，产品修改未开始）。负责人：tyuikl32；平台：Codex；优先级：P0。

上级：[M1](../09-20-tsunagou-m1/prd.md)。前置：R5。历史责任关联：T01, T16, T23（已归档，不作为启动依赖）。

范围来源：[独立运行实施方案](../../../docs/standalone/implementation-plan.md)、[当前缺口](../../../docs/standalone/status-and-gaps.md)、[路线图](../../../docs/implementation/roadmap.md)。多宿主正式认证和研究实验不作为本任务关闭条件。

## 交付内容

- 可交付 Python wheel/Node bridge 产物、任意 cwd daemon 发现和真实 doctor
- tools/dev/smoke_standalone.py、tools/dev/package_smoke.ps1 与真实入口端到端/故障回归
- 逐条已执行的 Windows 操作单、版本/命令/退出码/预期事实及交付总结

## 验收条件

- [ ] 干净临时 venv 安装 wheel 并从源码树外启动；无 PYTHONPATH/editable 回退；bridge 产物可启动
- [ ] 公开 CLI/HTTP/MCP 完成 M1 的 12 条最终标准，无直接 new 领域 Service 或改库补正常流程
- [ ] commit 前 kill 无半写，commit 后响应前 kill 重试无重复，Job 中断状态可解释，第二 writer 被拒
- [ ] 旧连接/epoch、worker 操纵主任务、未批准用户决定等拒绝案例通过，等待不会自行失败
- [ ] endpoint manifest 不含控制秘密；凭据私有存储；日志能按 command/attempt/event 定位而不泄密
- [ ] doctor 反映实际 DB/锁/恢复状态，未实现动作明确失败；用户操作单每条命令实际执行且可重复
- [ ] 全部相关 Python/TS/Schema/文档检查通过，M1 完成与后续完整设计范围分开报告

## 实施边界

保持主 Agent 控制 Git、用户重大确认、逐会话身份和领域所有权。代码只维护结构、状态、范围和版本不变量，语义协调由主 Agent 完成。不得返回占位成功、绕开所有权检查或伪造宿主 supported 状态。

文件责任见 [design](design.md)，执行和交接见 [implement](implement.md)。公共变更同步实施方案、Schema/registry、fixtures 与用户文档。
