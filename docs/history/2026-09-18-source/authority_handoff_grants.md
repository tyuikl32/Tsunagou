# 主 Agent 交接时的 Grant 连续性

> 核对日期：2026-09-17。
> 状态：第 166 题已确认选项 A；作为 D89 的主 Agent交接授权基线。

## 问题

主 Agent签发的 grants 是其管理权的派生物。交接后让它们全部存活，会让旧策略继续支配新 epoch；立即撤销又可能让正在写文件或调用工具的 Agent在没有安全停止窗口时失去协调通道。

[RFC 7009](https://www.rfc-editor.org/rfc/rfc7009)的 token revocation 语义允许撤销一个 token 及同一 authorization grant 派生的相关 tokens；[RFC 6749](https://www.rfc-editor.org/rfc/rfc6749)也强调 token scope 不应超过资源所有者授权，并可签发更小权限。Tsunagou 不直接套用 OAuth grant，但采用相同的“派生授权不可脱离签发 authority 永久存活”和“接管只能等权或收窄”原则。

## 选项

| 选项 | authority epoch 变化后的行为 | 优点 | 代价 |
|---|---|---|---|
| A（推荐） | 旧管理权与闲置 grants 立即失效；running attempt grants 进入最多 120 秒 `pending_adoption`，只允许安全收敛；新主 Agent按精确摘要 adopt 后换发新 epoch grant | 新主 Agent获得真实控制权，同时给运行任务安全暂停/报告机会；与 lease TTL 对齐 | 增加过渡状态、adopt 操作和超时收敛；Full Access 进程仍可能绕过逻辑冻结 |
| B | epoch 变化时所有旧 grants/token/leases 立即撤销，running attempts 一律 cancel/orphan | 最简单、最严格 | 正在执行的文件/Git/外部动作可能被截断，产生更多 outcome-unknown 和恢复工作 |
| C | 所有已签发 grants 保持到原 expiry，新主 Agent需要逐项主动撤销 | 连续性最好、交接最平滑 | 旧主 Agent可以通过长 TTL 把权限带入新 epoch；新管理者无法确定当前有效范围 |

## 选项 A：授权分类

epoch 改变时按 grant 来源和使用状态分类：

| 类别 | 默认处理 |
|---|---|
| 系统硬约束、用户直接签发且未绑定旧主 Agent的 grant | 保持，但重新计算当前 project/policy ceiling；不满足即收窄/撤销 |
| 旧主 Agent的未使用 ticket、session-wide grant、root/Git intent approval | 立即 revoked；旧 token family 与管理 command 全部失效 |
| ready/open/claimed 但未 running attempt 的执行 grant | 立即 revoked，任务回到可重新 preflight 的安全状态 |
| running attempt 的执行 grant | 进入 `pending_adoption`，设置 deadline，不允许开始新业务阶段 |
| 已启动 Git/外部副作用 action | intent/approval 不可转移；Operation 标记 outcome-unknown/reconcile，不能自动重试 |

grant 必须保存 `issued_by_principal_id`、`issuer_authority_epoch`、来源 ceiling/policy revisions、scope digest、issued/expires time 和 continuity class，才能确定派生关系。

## 原子交接

用户任免，或策略允许的主 Agent交接，通过一个 `AuthorityTransition` command/UoW 完成：

1. 校验 project revision、expected old main/epoch、successor identity/capability 和用户 ceilings。
2. 创建 transition ID，将 project 暂时标记 `authority_transitioning`，阻止新的 main-agent管理命令、claim 和 Git/root intent。
3. 原子写入新 main agent（可 absent）并递增 `authority_epoch`；撤销旧主 Agent的 control/token families、未开始 intents/approvals 与非运行 grants。
4. 为每个 running attempt 创建 immutable `GrantAdoptionCandidate`，固定旧 grant scope/digest、任务/attempt、lease、workspace、风险和 120 秒 deadline。
5. 路由高优先级 handoff/pause 消息给旧主 Agent、successor 和受影响 workers；SSE/主动唤醒只作提示，权威状态在 REST/inbox。
6. transition 进入 `awaiting_adoption`；不存在 running candidates 时可立即 completed。

交接事务不等待 Agent响应，也不声称终止外部进程。

## `pending_adoption` 能做什么

过渡窗不是继续正常开发的宽限期。受控 API/tool 只允许：

- 读取当前任务、grant transition、inbox、契约和已有 workspace 状态；
- ACK/respond handoff/cancel 请求、报告当前进度/未保存工作/外部副作用；
- 完成已经开始且无法安全中断的单个工具调用的结果上报；
- 请求暂停、提交只读状态/patch/artifact evidence、释放 lease、确认停止；
- 心跳仅用于证明 session/attempt 仍在线，不延长旧业务 grant 超过 transition deadline。

禁止新 claim、创建子任务、获取新资源、扩大写集、开始新 Git/网络副作用、修改 root/contract/policy 或进入下一个执行阶段。已在运行的 Full Access shell 可能无法机械拦截，系统发送自然语言/bridge pause，并把实际 enforcement 记录为 observed/advisory。

## Adopt

当前新主 Agent或用户可对单个/批量 candidate 提交 `AdoptGrant`：

- command 绑定 transition ID、新 authority epoch、candidate ID、旧 scope digest、current attempt/workspace/lease revisions；
- adopt 只能保持或收窄 capability/path/expiry，不能在同一动作中扩大；扩大走正常授权流程和必要的用户 ceiling 审批；
- 核心重新运行任务 preflight、权限交集、root identity、契约、风险/隔离和资源冲突检查；
- 通过后撤销旧 grant，签发新 epoch grant/token family，递增 attempt authorization revision 并记录 adopter/reason；
- attempt 只有在 worker 确认收到新 grant 且必要 lease 恢复后才能继续 running。

批量 adopt 仍逐 candidate 给出结果；不能因一个失败而假装其他已换发 grants 回滚。

## 未 Adopt 的收敛

- worker 在 deadline 前确认安全停止：旧 attempt 转为 `blocked(reason=authority_transition)` 或按请求取消，释放 leases；任务由新主 Agent决定 resume/交接。
- deadline 到达且没有停止证据：attempt 进入 `orphaned`，使旧 execution epoch/grant/token 失效，记录残余进程/写入风险；相关物理资源保持 quarantine，直到 reconcile。
- 用户可在极端情况下为特定 candidate 批准一次有界延长；新主 Agent不能自行无限延长旧 epoch。
- 没有 successor 时仍执行同样冻结/收敛；用户之后任命新主 Agent，再从 blocked/orphaned 状态恢复，不让旧 grants 无限等待。

120 秒与执行 lease TTL 对齐是首版默认值；项目可收紧到 0（等同立即撤销），不能仅由主 Agent延长超过用户/项目上限。

## Git、消息与租约

- 已开始 GitAction 在交接时进入 outcome-unknown；新主 Agent先按 D83/D84 reconcile before/after refs，再创建新 intent。旧 L2 用户批准也绑定旧 intent/epoch而失效。
- pending-adoption worker 的现有资源 lease 不再普通 renew；transition coordinator 仅将其保留到较早的原 TTL/deadline，用于安全收敛。新 grant 通过后重新取得/换发 lease。
- inbox 历史不转移作者身份。旧主 Agent未处理的 required management obligations 路由给 successor 生成新的 recipient obligation，旧 obligation 标记 superseded_by_transition。
- worker 对原任务的业务消息保持可读；任何要求旧主 Agent批准的 request 不能由新主 Agent冒充响应，而应以 successor 身份给出新 response/evidence。

## 崩溃恢复与幂等

- AuthorityTransition、candidate、revocation、adoption 与消息/outbox 在 SQLite 持久化；daemon 重启从 deadline 与状态继续。
- 相同 transition command/request hash 幂等返回原 transition；不同 successor/scope 冲突。
- adoption command 相同 digest 幂等成功；candidate 已 adopted/revoked/expired 时返回其终态，不重复签发 token。
- daemon 停机时间越过 deadline 时，启动后先执行过期收敛，再开放项目写入。

## 后续待细化

- AuthorityTransition/GrantAdoptionCandidate/AdoptGrant 的完整字段与 REST/MCP schema。
- 哪些 progress/artifact 操作属于安全收敛 allowlist，以及各适配器能否机械限制。
- 新主 Agent批量审查 UI/CLI 输出与默认收窄建议。
- 用户直接 grant 与旧主 Agent policy 共同派生时的 provenance DAG 表达。
