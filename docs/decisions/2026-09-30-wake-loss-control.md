# D184：唤醒只承担“有人被卡住”的打扰，并且一定会收敛

日期：2026-09-30。来源：用户要求落地此前提出的“止损三条”——窄化触发、能力感知的终态、状态声明诚实；并把读取时机写进契约，补一个只读收件箱 peek 与“推送到人”的可见性。

## 决定

1. **触发面按种类收窄**：daemon 只为 `task.assigned`、`task.submitted`、`task.reviewed`、`contract.proposed`、`contract.revised`、`user_decision.resolved` 在消息创建的同一事务里写 `outbox(kind='host_wake')`。白名单只有一处（`modules/messaging.py::WAKE_WORTHY_KINDS`）。普通 `message`/`notice` 只进收件箱；`user_decision.pending` 不唤醒——它的收件人在构造上就是一个 running attempt（宿主本来就醒着），暂停由 `task.begin` 门禁保证。
2. **“待唤醒”行是持久意图，不是当前进程的能力判断**：即使本次启动没有启用唤醒也照写，以便以后启用时由投递工人补投；对应 delivery 已经被 ACK 时不会启动 turn（`messages_already_acked`）。
3. **有界重试 + 终态**：`host_binding_not_found`、`host_binding_not_ready`、`host_wake_dispatch_failed` 以 5 秒起倍增、封顶 300 秒，最多 12 次（总窗口约 35 分钟）；到顶后该行转 `failed`，不再每 5 秒空转。不采用“一次判定即终态”的字面实现，因为“没有绑定”虽然多数是确定性结论（能建绑定的只有 Codex 三个 provider），但绑定也可能几分钟后才出现。
4. **声明诚实**：`daemon.endpoint()` 在环境变量缺席时报 `disabled`；A2A Agent Card 报 `binding-dependent`（没有 dispatcher 时才是 `unsupported`），不再用“调度器存在”冒充“能唤醒”。
5. **门铃不装正文**：唤醒 prompt 只带条数与最久等待时长（`HostWakeRequest.waiting_hint`）；正文只在通过认证的 MCP 拉取里。等待超过 10 分钟的 delivery 会写一条按消息去重的 `message_waiting` 诊断，让“迟迟没人读”在流水里也可见。
6. **只读 peek**：`GET /api/v1/projects/{project_id}/inbox` 与 `MessageStore.waiting()` 与 `fetch()` 共用同一条候选规则，但不领租约、不计次；Agent 只能看自己的收件箱，`U` 可用 `agent_id` 查询指定 Agent。
7. **读取时机进契约**：MCP `instructions` 与生成的 `agent-context.md` 都要求“每轮开始 + 每个自然断点（子步骤完成、构建或测试跑完）再读一次”。

## 未做与边界

> 下列四条已由 [D185](2026-10-01-wake-switch-and-degradation.md) 在 2026-10-01 收口：项目级开关接进唤醒链路（读不到即关，关闭期间行保持 pending）、能力协商参与派发决策、Desktop 占用会话显式降级、`unknown` 兜底时限与两个日志文件的保留上限，并顺带消掉了 A2A 同步派发那条重复路径。

- ~~项目级策略 `auto_wake_multi_agent` 仍未接进唤醒链路~~（D185 已接）。
- ~~A2A 收消息时**同步**再唤一次的重复路径仍在~~（D185 已改为只登记、由后台派发）。
- Desktop `active writer` 未显式降级为 `degraded` + `wake_failed`；重启后 `unknown` 的兜底时限、诊断与尝试文件的保留上限仍未加。（D185 已加。）
- **不新增控制台界面**：只提供数据与接口，界面由使用者自行设计。（D185 维持，并把数据出口列为已齐。）

## 影响

- `docs/implementation/codex-host-wake.md` 新增“什么时候才打扰宿主”。
- `docs/overview/cli-http-manual.md` 新增 `/inbox` 只读路由。
- 根文档 `Tsunagou-消息共享与唤醒机制.md` §11 记录实施与残留项。
