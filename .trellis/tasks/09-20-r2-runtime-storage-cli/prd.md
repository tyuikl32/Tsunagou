# R2 常驻 daemon、统一 SQLite 和真实 CLI

状态：planning（第一轮 runtime/CLI 已落地，完整迁移与恢复门禁仍待验收）。负责人：tyuikl32；平台：Codex；优先级：P0。

上级：[M1](../09-20-tsunagou-m1/prd.md)。前置：R1。历史责任关联：T04, T05, T06, T07, T16（已归档，不作为启动依赖）。

范围来源：[独立运行实施方案](../../../docs/standalone/implementation-plan.md)、[当前缺口](../../../docs/standalone/status-and-gaps.md)、[路线图](../../../docs/implementation/roadmap.md)。多宿主正式认证和研究实验不作为本任务关闭条件。

## 交付内容

- 唯一 ProjectRuntime、daemon lifespan、进程寿命锁、单 writer 和模块 SQL repository
- 真实 CLI HTTP client、启停/状态/项目选择与必需查询入口
- 原子 command/event/outbox 写入、幂等重放、启动 epoch 恢复及显式旧 JSON 导入

## 验收条件

- [ ] CLI 签发的票据可被正在运行的同一 daemon 兑换；CLI 查询能读到 HTTP 写入的真实对象
- [ ] Task、Contract、Message 等 M1 事实写入协调项目 SQLite，杀进程再启动可查询；无 JSON/内存双重真相
- [ ] 一条变更失败后 Task/Grant/Lease/event/outbox 均无部分写入；同键同输入返回原结果，异输入 409
- [ ] 旧身份/epoch 的请求不能借幂等缓存获得有效授权；有效重试在 revision 检查前命中原结果
- [ ] 第二 writer 打开同项目失败；服务不可用 CLI 退出 5，未知对象明确 404，无固定成功占位输出
- [ ] 启动撤销旧执行 Grant/Lease，保留 Attempt owner 并进入恢复审查；旧 JSON 导入失败保留原文件、事务无半导入

## 实施边界

保持主 Agent 控制 Git、用户重大确认、逐会话身份和领域所有权。代码只维护结构、状态、范围和版本不变量，语义协调由主 Agent 完成。不得返回占位成功、绕开所有权检查或伪造宿主 supported 状态。

文件责任见 [design](design.md)，执行和交接见 [implement](implement.md)。公共变更同步实施方案、Schema/registry、fixtures 与用户文档。
