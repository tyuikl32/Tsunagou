# 项目初始化与首任主 Agent

> 核对日期：2026-09-17。
> 状态：第 168 题已确认选项 A；作为 D91 的首任主 Agent bootstrap 基线。

## 问题

D80 允许 project init 完成后立即 active，D19/D90 又允许 authority 暂时 unassigned。必须明确首任主 Agent如何产生。若“第一个接入的 Agent”自动成为主 Agent，普通 join ticket、重连竞态或错误宿主就可能取得项目管理权；若初始化强制等待 Agent在线，则 CLI/恢复/自动化 bootstrap 被不必要地绑定到某一宿主。

## 选项

| 选项 | 首任主 Agent 规则 | 优点 | 代价 |
|---|---|---|---|
| A（推荐） | init 不隐式任命，项目可为 `active + unassigned`；用户显式任命已接入 Agent，或签发绑定候选的一次性“接入并任命”票据 | 无竞态提权；支持先配置后接 Agent；恢复/测试简单；仍可一条用户流程完成接入任命 | 多一个明确授权步骤；unassigned 时部分工作被 blocker 限制 |
| B | 第一个使用任何有效 join ticket 接入的 Agent自动成为主 Agent | 上手步骤最少 | 普通 worker 可能抢占主 Agent；并发接入依赖时序；难以表达用户选择 |
| C | project init 必须由一个在线 Agent调用，并把调用者自动设为主 Agent；没有 Agent不能初始化 | 心智模型直观，项目始终有主 Agent | bootstrap 与特定宿主/会话耦合；Agent身份尚未建立时存在循环依赖；不利于恢复和无人值守配置 |

## 选项 A：初始化后的能力

`project init` 的调用主体是本机 user/control principal，不是尚未注册的 Agent。初始化事务产生：

- active lifecycle、active writer replica、`authority.status=unassigned`、`authority_epoch=0`；
- user ceilings、shared project/root declarations、本机 bindings、genesis checkpoint 和 D80 的 Git durability 状态；
- `main_agent_required` blocker，仅作用于明确要求主 Agent的 actions/capabilities，不把整个项目伪装成不可用。

在 unassigned 状态：

- 用户仍可查看/配置项目、管理 ceilings/bindings、签发 enrollment ticket、任命主 Agent、运行 doctor/reconcile、归档或注销；
- 用户可创建/维护 draft task 和其他由用户直接授权的对象；具体 publish/claim/start 是否可用仍按任务风险、D66 fallback 和 action blocker matrix判断；
- 已获用户 ticket 的 Agent可 attach、上报 capability 和等待 inbox，但普通 attach 不改变 authority；
- 需要 main-agent Git、root delegation、风险评估、grant issuance、任务协调或 contract management 的动作返回 `main_agent_required`。

项目可以长期 unassigned；系统不因超时选主，也不从 agent role/name、宿主种类、Full Access 或连接先后推断管理权。

## 路径一：任命已接入 Agent

用户调用类型化 `AppointMainAgent` command：

- 输入 agent ID、当前 session/host evidence、main-agent ceiling/grant template、expected project revision 与 expected authority epoch 0；
- 核心验证 Agent属于当前 project/lineage、未 retired、session 连续、adapter/host capability 满足主 Agent最低要求，且授权不超过用户 ceilings；
- 同一 UoW 将 authority 从 unassigned 变为 stable、epoch 从 0 增为 1，签发新的 main-agent token family/grant，创建任命事件、inbox obligation 和 outbox；
- 若并发任命已成功，后到命令因 revision/epoch 不匹配失败，不覆盖现任主 Agent；
- 任命事务提交即生效；职责/范围通过持久 inbox obligation 通知，ACK 只作可观测性，不阻止管理命令。

用户任命是幂等 command：相同 command/request hash 返回原结果；同 key 不同候选冲突。

## 路径二：一次性接入并任命票据

为了减少交互，用户可签发专用 `main_agent_enrollment_ticket`：

- 固定 project/lineage、host kind、候选 session/host binding 条件、main-agent ceiling、初始 capabilities、expected authority epoch、10 分钟 expiry 和 one-time nonce；
- 明确字段 `appoint_on_success=true`，票据类型与普通 `agent_enrollment_ticket` 不可互换；
- attach 验证和 authority appointment 在同一 UoW 完成；任一步失败都不产生半任命或可复用的 access token；
- 并发票据只有第一个满足 expected epoch 的事务成功，其余返回 `authority_epoch_mismatch` 并消费/撤销到安全终态；
- ticket 不含 bearer 之外的长期凭据，不进 Git/prompt/log；bridge 仍按 D50 代持。

该路径仍是用户显式选择候选，只是把 attach + appoint 合并，不是“first join wins”。

## 不允许的隐式信号

以下均不能自动任命主 Agent：

- 第一个连接、最近活跃、最高模型版本或 Full Access；
- Agent自报 role=`main`、自然语言声称代表用户；
- 使用 Codex/OpenCode 等特定 adapter；
- 能读取 coordination repo、创建 Git commit 或拥有操作系统管理员权限；
- 从旧 clone/旧 runtime 拷贝的 main-agent token/配置；
- 旧 lineage/authority epoch 中曾任主 Agent。

## 恢复与撤销

- 任命事务提交但通知失败：authority 已生效，持久 inbox/outbox 重投；不能因为 bridge 未收到而自动回退并另选人。
- Agent在任命后失联：authority 保持 stable，用户可撤销或交接；epoch 再次递增，旧票据/token/grants 失效。系统不自动降回 epoch 0 或选主。
- 首任主 Agent失联后使用正常 D89 撤销/交接流程，不重新套用 bootstrap first-agent 规则。
- 从 checkpoint clone 时共享历史可显示曾任主 Agent，但新 runtime 的 token/session 不恢复；当前 authority state 按恢复协议重建并要求有效本机接入证据。

## API/CLI

- `POST /api/v1/projects/{project_id}/actions/appoint-main-agent`
- `POST .../enrollment-tickets`，ticket kind=`main_agent` 或 `worker`
- `GET .../authority` 返回 current main、epoch、status、active transition refs 和 blockers
- CLI：`tsunagou project authority appoint --agent <id>` 与 `tsunagou agent ticket create --role main-agent`；JSON 不输出 secret ticket，秘密通过安全输出/凭据交付通道处理

普通 Agent的 MCP 工具不暴露 self-appoint。用户/control API 与当前主 Agent在 policy 允许下的后续 handoff 使用不同 command kinds，防止 authorization handler 混用。

## 后续待细化

- main-agent minimum capability profile 与四 adapter 的验证字段。
- enrollment ticket secret 的 CLI 安全展示、credential store 与 bridge 领取协议。
- 从共享 checkpoint 恢复 current authority metadata 时，unassigned/stable 的本机重建规则。
