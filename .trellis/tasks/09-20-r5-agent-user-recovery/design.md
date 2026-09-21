# R5 设计与责任边界

细化 [PRD](prd.md)，公共语义以[独立成品方案](../../../docs/standalone/implementation-plan.md)及其引用的模块规范为准。

## 文件责任

- packages/bridge-server/src/、packages/bridge-sdk/src/、接入 CLI 配置生成器
- src/tsunagou/modules/projects*、agents*、durability/evaluation 公开端口与 repository
- checkpoint Job、观测投影、会话恢复及 stdio/HTTP 集成测试

路径带“待建”或包含规划目录时，按现有代码逐模块迁移；不得保留旧单文件和新包中的两套独立实现。

## 设计约束

1. 独立 bridge 使用随机绑定会话 ID；cwd 不作为身份，宿主临时 subagent 不自动成为成员。resume 必须持有原私有记录并通过 nonce/epoch 校验。
2. admission_profile=local_session 是阶段性交付设置，需显式注册、校验和记录；不能把旧能力检查改为永远成功或伪造 supported。
3. 票据经本机私有交付进入 bridge，宿主配置只引用非秘密启动描述；bridge token 和 user control token 分离。
4. UserDecision/CompletionProposal/Grant 归 projects；durability 处理 checkpoint/Job；evaluation 只消费事件，不持有业务写权限。
5. 不承诺宿主主动唤醒或动态 IDE 门禁；正常交互通过 stdio MCP tools 完成。等待期间状态持久化，下一轮由读取黑板恢复上下文。

## 依赖与交接

开始前读取 R4 的验收记录，确认产物可从正常入口使用。依赖有缺陷则先回补，不能临时绕过。

后继任务复用公开端口、DTO、持久数据与运行结果。workflow 组合端口，领域事实归所属模块。成功响应和日志不得含控制秘密。

## 验证方法

1. 运行两个真实 stdio bridge 子进程，通过 MCP 初始化、tools/list、tools/call 连接同一 daemon，检查身份隔离。
2. 中断网络重试同动作、再次发送同正文新动作，校验 command_id 与 inbox 呈现/ACK 顺序。
3. 通过 U CLI 提交决定/完成确认，注入 checkpoint 物化失败；断言用户结论保留、状态可查、旧 epoch 不延续执行权。

故障操作和停止条件见[调试执行单](../../../docs/standalone/debugging-runbook.md)。实际结果写入 implement.md，不能只以任务状态表示验证成功。
