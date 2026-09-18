# 工程消歧与规范优先级

本文件把已确认原则推导为唯一实现约定。E 编号是本次文档整理的工程结论；不是新增用户回答。若宿主实测推翻某项可行性，记录证据并调整实现，不默默降低共同基线。

| ID | 分散文档中的歧义 | 当前唯一约定 |
|---|---|---|
| E01 | runtime epoch 有时整数、有时 UUID | `runtime_epoch` 是 UUIDv7；authority_epoch、connection_epoch、execution_epoch 是非负安全整数。wire 旧文档把 runtime 列入整数处作废。 |
| E02 | “不可变 Attempt”与状态更新 | Attempt 的 ID、owner、创建输入及历史结果不可改；其 status/revision 是可更新投影，每次更新有事件。关闭的 Attempt 不复活，blocked 原 Attempt 可 resume。 |
| E03 | Lease 在 running 前需要却又在非 running 释放 | preflight 预留 active execution Lease 于 claimed；start 必须校验仍有效。离开 running/取消 claimed/失联时释放。冻结 grant 不赋予执行权。 |
| E04 | blocked 无 execution grant 却允许报告 | agent_base 附带协调命令 capability，handler 必须校验其为该 Attempt 历史/当前 owner、参与者或收件人；只能报告/协商/恢复请求，不能文件写入、start 或续 execution Lease。 |
| E05 | 同 session SSE 与 REST 多个请求算多 Connection | Connection 是 bridge 逻辑连接代次，不是 TCP socket；每个 REST、MCP session 和 SSE 均绑定同 HostSession 当前 connection_epoch。 |
| E06 | daemon 建 Worktree 与主 Agent控制 Git冲突 | D83 优先：所有 Git mutation（包括 worktree add/remove）由 current main 执行；workspaces 产生请求并只读核验。无 main 就等待，daemon 不调用写 Git兜底。 |
| E07 | checkpoint 成功/逻辑状态提交混用 | 数据库状态提交先成立，响应包含 materialization 状态；D162 完成立即可见，必需 checkpoint 待收敛。归档/切换另有完成屏障；不把文件 I/O 放进数据库事务。 |
| E08 | 固定 user-only 和 main重大性分类 | 固定命令按 principal 强制；业务重大性由 main申报。核心禁止从文字/diff 猜测重要程度。 |
| E09 | outcome_unknown 是终态又可 mark 成功 | 原 Operation 保持 outcome_unknown；新 OperationResolution 保存 conclusion、evidence、actor、reason；`effective_outcome` 为派生结论。风险接受不产生成功结论。 |
| E10 | idempotency_key 与 command_id 双重身份 | 公开 mutation 唯一幂等键 `command_id`；数据库唯一 `(project_id, principal_id, command_kind, command_id)`；旧 `idempotency_key` 文案作为实现内名，不增加 wire 字段。 |
| E11 | 用户无响应与 Lease/Job/评估超时 | UserDecision/挂起无默认截止。Lease、Job、票据属基础设施时间；D66 风险评估 120s 仍为明确已确认例外，只尝试确定性 fallback，不判断用户拒绝/任务失败。普通 request deadline 可省略。 |
| E12 | 同 lineage分叉与 sealed lineage混合 | 同 lineage自动合并仅不相交实体；同实体由 main明确方案，身份/用户 ceiling冲突 user。sealed lineage不合并；fork延后。 |
| E13 | 契约参与者不允许代理的旧规则 | D150–151优先，policy明确允许时 main可 proxy，记录真实 actor；全体 required slots仍须被 direct/proxy evidence覆盖，不能伪造直接接受。 |
| E14 | 父任务结束级联取消的历史选项 | D97优先，子孙独立继续；不自动取消、不隐式门禁父验收。 |
| E15 | shared artifact 可能泄露私信 | 默认本机；只有领域权限为 project_shared 且经过当前 main/user显式 PromoteArtifact 的内容进入共享 checkpoint。recipient-only材料不能自动提升。hash只寻址不授权。 |
| E16 | schema 路径和命令命名漂移 | OpenAPI 固定 `protocol/openapi/v1/openapi.json`；领域 command `snake_case.dot`，DTO PascalCase，wire field/event type snake_case；REST action统一 `/{resource_id}:verb`。以 command catalog为源，禁止同义端点。 |
| E17 | 主 Agent提议完成时自身 Attempt尚运行 | 提案可先建；确认前逻辑关闭所有 current Attempt。停止未知用残余风险证据，不能仅因模型下线就算已停止。 |
| E18 | shared 快照携带运行身份 | 保存历史作者/authority事件，但不导入可用 credentials/grants/Lease/job claims。重置、新 clone 一律重建 runtime；归档/reactivate 的差别依 lifecycle规范。 |
| E19 | shared MCP与宿主 stdio兼容 | daemon共享 project scoped Streamable HTTP MCP endpoint；stdio-only宿主用逐会话薄 stdio转发器接入，仍共享服务与工具定义。转发器不持有全项目身份。 |
| E20 | 文件物化永久失败与用户完成结论 | 项目事实不回滚；completion checkpoint失败只阻塞完成归档/发布/迁移等需要证据的动作。outbox高水位达到硬阈值才挡新增领域写，读取/修复/撤权始终可用。 |
| E21 | capability零散新增 | 以当前 command catalog 的唯一 capability列为准；五 grant kinds保留；user-only无可下发的 admin capability。 |
| E22 | 恢复旧任务自动复活权限 | 目标 checkpoint中终态保留；非终态恢复为 blocked/recovery_review，无current Attempt和运行权限。main显式选择转 open；已completed只可follow-up。 |
| E23 | 无execution Grant时如何start/resume | claimed/blocked的owner使用agent_base+task.coordinate_self协调；resume只blocked→claimed，start完整核验后才running并发执行Grant。旧task.start必须先持task_attempt的循环依赖不采用。 |
| E24 | 凭据首次交付丢失与普通幂等结果 | 服务端只持久secret hash；幂等重放返回非秘密receipt。bridge未保存token须专用rebind，不为此新增加密token缓存或密钥生命周期。 |
| E25 | 共享MCP服务部署位置 | Python官方SDK在daemon承载项目MCP；TS官方SDK只承担必要bridge/stdio传输。具体SDK API与版本由T02验证，不能从语言选型猜已兼容。 |
| E26 | 用户直接管理与Agent管理入口 | 需要user直接操作的普通管理动作注册独立user command，无Grant；不能让user token伪装main，也不创建通配admin动作。明确目录见command-catalog。 |
| E27 | 尚未逐题决定的限额与私有结构 | 当前规范中的表名前缀、Job实现端口、64MiB附件默认、JSON/批次/路径限额、outbox高水位和黑板截断值是有标注的工程默认；不是伪造用户选项。Schema/配置一致可调整，不改变产品权限和认知边界。 |

## 阅读优先级

当前用户明确指令 > D161–D181与更晚已确认决定 > 本文件消歧 > 当前实施规范 > 专题历史记录 > 初始研究建议。若 E 推导与已确认决策产生实质冲突，以已确认决策为准并修订规范。

当前实现规范是整理后的实施基线，不要求开发者同时逐字拼接 45 份历史草案。详细实体、命令、失败语义不得由某个 adapter自行再定义。
