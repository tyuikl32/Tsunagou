# 主 Agent 风险评估与隔离决策协议

> 核对日期：2026-09-17。
> 状态：候选协议；标为“已确认”后才构成实现约束。

## 依据与边界

- MCP tools 可以声明 `outputSchema`，服务端必须返回符合 schema 的 structured result，客户端仍应验证。不同宿主支持深度不同，核心不能假定宿主已经完成验证。
- JSON Schema 2020-12 提供 required、enum、长度/数量和对象属性约束，可拒绝额外字段及无界载荷。
- OWASP 对 Agent/LLM 的建议包括验证工具调用的权限与会话上下文、限制工具参数，并按最小权限处理模型输出。
- 本系统后端不调用模型 provider。风险评估请求作为持久消息交给当前主 Agent，主 Agent 通过类型化工具提交建议。

来源：

- [MCP latest specification: Tools](https://modelcontextprotocol.io/specification/latest/server/tools)
- [JSON Schema 2020-12 validation](https://json-schema.org/draft/2020-12/json-schema-validation)
- [OWASP LLM Prompt Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)

## 候选请求：RiskAssessmentRequest

请求是不可变快照，最小字段如下：

| 字段 | 含义 |
|---|---|
| `assessment_id`, `schema_version` | 请求身份与协议版本 |
| `project_id`, `task_id`, `attempt_id` | 所属项目、任务和当前 attempt |
| `execution_epoch`, `task_revision`, `authority_epoch` | 防止旧 owner、旧任务或旧主 Agent 响应生效 |
| `input_digest` | 下列决策输入经 JCS 规范化后的 SHA-256 |
| `trigger`, `requested_at`, `deadline_at` | 首次评估或重评原因及时间边界 |
| `task_snapshot` | 目标、验收策略、状态及受长度限制的任务描述 |
| `resource_intents` | roots、fs URI、读写/执行/consistent-read 意图 |
| `repository_facts` | 仓库数、Git 状态、基线 commit、跨仓库关系 |
| `required_capabilities`, `minimum_strength` | 任务硬要求和最低执行强度 |
| `available_drivers` | shared/worktree/external 的能力向量和当前可用性 |
| `contracts_and_discrepancies` | 相关契约 hash、未解决 hard discrepancy 和依赖摘要 |
| `policy_constraints` | 用户/项目策略、禁止项、允许的降级范围 |
| `previous_decision`, `changed_fields` | 重评时的旧决定与触发差异 |

`input_digest` 覆盖除时间和 assessment identity 外的全部决策输入。任何影响驱动选择的字段变化都会产生新 assessment，而不是修改旧请求。

## 候选响应：RiskAssessmentSubmission

| 字段 | 规则 |
|---|---|
| 请求身份字段 | 必须原样回传 `assessment_id/task_id/attempt_id/execution_epoch/task_revision/authority_epoch/input_digest` |
| `risk_level` | `low`、`medium`、`high`、`critical` |
| `recommended_driver` | 只能是请求中的可用 driver |
| `risk_factors[]` | 每项包含受控 `code`、severity、evidence refs 和简短 rationale |
| `required_controls[]` | 只能引用内核识别的控制项，例如 clean base、exclusive lease、secret denial、review gate |
| `assumptions[]` | 明示模型依赖但未验证的事实，每项有稳定 key 和文本 |
| `confidence` | `low`、`medium`、`high`，不使用伪精确概率 |
| `reasoning_summary` | 面向审计的短理由，不要求也不保存隐藏思维链 |
| `submitted_by`, `submitted_at` | 由鉴权上下文和服务器时间写入，客户端不能伪造 |

Schema 使用 `additionalProperties: false`，对字符串、数组、嵌套深度和 evidence refs 数量设上限。适配器可以把 schema 传给宿主，但后端始终再次验证。

## 确定性裁决

- 后端先验证身份、权限、current main agent、authority epoch、任务 revision、execution epoch、input digest 和 schema。任何不匹配返回 `409 stale_assessment` 或 `422 invalid_assessment`，不部分采纳。
- 内核独立计算 hard-constraint result：可用 drivers、minimum strength、权限上限、资源/仓库限制和未解决 hard discrepancy。
- 主 Agent recommendation 只有通过硬约束才可成为最终选择；不满足时内核选择满足约束的候选或保持 preflight blocked，并记录 rejection reasons。
- 最终结果是独立不可变的 `IsolationDecision`，引用 request、submission、policy version、选中 driver、required controls 和裁决理由。它不能由模型直接写入。
- 用户覆盖和策略允许的主 Agent降级继续使用已确认的审计规则；覆盖生成新 IsolationDecision，不改写原 submission。

## 陈旧与重评

- 资源意图、roots、仓库数、契约/hard discrepancy、权限、执行强度、driver capabilities 或 task revision 变化时，旧 input digest 立即失效并产生新请求。
- 任务还在 claimed 时，旧决定失效并重新 preflight；任务已 running 时标记 `migration_required`，停止签发新的受影响资源租约，但不自动搬迁或终止现场。
- 重复提交相同 assessment 和相同内容按幂等成功返回；同一 assessment identity 的不同内容作为冲突拒绝并审计。

## 候选不可用与超时策略

### Deadline 和提醒

- 存在 current main Agent 活动会话时，响应 deadline 为请求提交后 120 秒；对同一持久 inbox request 在 0、30、90 秒尝试唤醒或提醒，不创建三个逻辑请求。
- pull-only 适配器仍使用相同 deadline，消息在 inbox 中持续可见。ACK 只表示已读，不等于完成评估。
- 创建请求时没有活动主 Agent 会话，或会话已被判定失联时，不空等 120 秒，立即运行确定性 fallback 评估。
- schema/权限/digest 校验失败会返回字段级 machine-readable issues，并通过同一 request 允许修正；无效提交不延长 deadline。前三次无效提交可触发主动 correction reminder，之后停止自动提醒但仍接受合法修正。

### 确定性 fallback 矩阵

fallback 先运行全部 hard constraints；任何自动选择都必须满足权限、minimum strength、driver availability 和项目策略。

| 条件 | 自动结果 |
|---|---|
| 用户已固定一个 driver 或已绑定 external 环境 | 满足硬约束则采用，并标记 user-preset fallback；否则拒绝 |
| 只读、无进程/网络/密钥隔离要求 | shared 满足全部约束时采用 |
| 单一 Git 仓库写入且 worktree 能力覆盖全部要求 | worktree |
| 过滤后只有一个合法 driver | 项目策略允许自动 fallback 时采用 |
| 多仓库写入、未知写范围、存在不可比较的多个候选 | 保持 preflight 等待，不猜测 |
| 需要进程/网络/密钥等机械隔离，但没有能力匹配的 external driver | 保持 preflight 等待并报告缺失能力 |

- capability vector 不建立“external 永远强于 worktree”之类的全序。规则无法得到唯一、安全结果时必须等待主 Agent 或用户。
- fallback 生成的 IsolationDecision 使用 `source=deterministic_fallback` 和 `assessment_outcome=timed_out|main_agent_unavailable|invalid_exhausted`；不伪造 risk level、confidence 或模型理由。

### 任务状态和迟到响应

- fallback 成功后关闭该 assessment request，继续其余 preflight。迟到 submission 返回 `409 assessment_closed`；尚未 running 时可显式请求 re-evaluate，生成新 request/digest。
- fallback 无法选择时，Task 保持 `claimed`，Attempt 的 preflight 状态为 `waiting_for_risk_assessment`，不转入会释放 owner 的 Task `blocked` 状态。
- 等待期间合法的迟到 submission 仍可完成 assessment；current main Agent 或 authority epoch 变化时，旧请求立即 stale，并为新主 Agent 生成新请求和 deadline。
- 用户可随时通过已有 override 流程选择 driver；内核仍验证 hard constraints，并记录为何自动 fallback 未能决策。

## 后续验证

- 模拟 wake-capable、pull-only、离线、主 Agent 换届、连续 malformed submission 和 deadline 边界竞争。
- 对 fallback 矩阵做表驱动测试，确保多仓库写、未知 scope 和缺失机械隔离能力不会静默退化为 shared。
