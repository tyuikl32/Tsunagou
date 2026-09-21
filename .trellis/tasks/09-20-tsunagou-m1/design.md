# M1 设计基线

阶段方案：[独立成品实施方案](../../../docs/standalone/implementation-plan.md)。问题事实：[八模块审计](../../../docs/standalone/status-and-gaps.md)。保留完整目标：[实施基线](../../../docs/implementation/README.md)。

## 八模块责任

| 模块 | M1 核心补齐 | 主要任务 |
|---|---|---|
| projects | 项目/root/ceiling、Grant、用户决定/完成确认 | R2、R3、R5 |
| agents | 独立会话、主身份、消息/收件箱、bridge 接入 | R2、R5 |
| tasks | 状态、Attempt、owner、preflight、执行与审查 | R2、R3 |
| cognition | 报告/分歧/契约及版本接受 | R2、R4 |
| resources | 整组 scope/冲突/Lease/过期 | R2、R4 |
| workspaces | shared 的真实文件基线与结果 | R2、R4 |
| durability | SQLite/UoW、幂等/事件/Jobs、附件/checkpoint | R2、R4、R5 |
| evaluation | 提交后审计投影和查询 | R2、R5 |

R1 提供公共协议和包资源，R6 负责安装产物及全流程验证，不新增业务模块。

## 不变量

- 一个 ProjectRuntime，一个写命令一个 SQLite UoW；内存限请求生命周期。
- 跨模块使用公开端口；workflows/blackboard 无自有领域真相。
- HTTP、CLI、MCP 共用身份、scope、owner、revision、epoch 与错误语义。
- 内核处理机械不变量，主 Agent 判断业务语义；不能绕过固定用户权限。
- 阻塞持久保存，用户不回答不等于失败；无关任务可继续。
- 外部 I/O 在事务外执行，Job 用版本核验回写，未知结果不盲重。
- M1 用本机产品行为验收，不把原宿主能力门禁移入新计划。

数据、事务、公开命令和错误矩阵使用实施方案第 4/5 节，子任务不能重命名同一概念。
