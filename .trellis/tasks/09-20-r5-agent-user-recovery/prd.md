# R5 Agent 接入、用户决定与恢复

状态：planning（实施计划就绪，产品修改未开始）。负责人：tyuikl32；平台：Codex；优先级：P0。

上级：[M1](../09-20-tsunagou-m1/prd.md)。前置：R4。历史责任关联：T14, T15, T16, T17（已归档，不作为启动依赖）。

范围来源：[独立运行实施方案](../../../docs/standalone/implementation-plan.md)、[当前缺口](../../../docs/standalone/status-and-gaps.md)、[路线图](../../../docs/implementation/roadmap.md)。多宿主正式认证和研究实验不作为本任务关闭条件。

## 交付内容

- bridge-server 复用 bridge-sdk 的生成工具、逐动作幂等 ID、精确错误和自动读取同步
- 逐会话私有接入配置、local_session profile、U 任命与可靠 resume
- 真实用户决定/项目完成确认、Operation/Job checkpoint 和提交后审计查询

## 验收条件

- [ ] 用户通过 CLI 生成两份独立 bridge 启动配置即可接入；秘密不进入提示词/日志；新会话不共用凭据文件
- [ ] local_session 不以宿主测评为任务执行前置条件；ticket/协议/身份/epoch 和 main/worker/user 边界仍有效
- [ ] 每次新动作生成新 command_id；同次重试复用 ID；两个相同正文消息作为两次动作各有记录
- [ ] tools/list 和实际 M1 handler 对齐；attach/resume/任务边界先读取黑板和增量收件箱，呈现后 ACK
- [ ] U resolve 精确 revision/digest；pending 无超时，解决不自动 start；worker 不能任命 main、代用户确认
- [ ] 用户确认项目 completed 与 checkpoint Operation 同事务；物化失败保留用户结论和可查错误/重试
- [ ] 停掉 bridge 并恢复可读原任务和消息；审计仅消费已提交事件、可重建且不含 token/私信正文

## 实施边界

保持主 Agent 控制 Git、用户重大确认、逐会话身份和领域所有权。代码只维护结构、状态、范围和版本不变量，语义协调由主 Agent 完成。不得返回占位成功、绕开所有权检查或伪造宿主 supported 状态。

文件责任见 [design](design.md)，执行和交接见 [implement](implement.md)。公共变更同步实施方案、Schema/registry、fixtures 与用户文档。
