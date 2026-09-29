# W3 审查：已经 ACK 的排队通知不得再制造空读回合

日期：2026-09-28。57 项组合回归的完成结果于 `2026-09-28T14:26:18.000Z` 观察到；该值为观察时刻，不是推测出的测试起止时间。此项由协调者授权按 Trellis check 核实并自修，接口方向先报告失败复现后得到确认。

## 问题来源与复现

协调者的原 Worker 实测报告：活跃回合已经读取并回复 `d669...` 消息，回合结束后疑似又被排队 wake 触发一个只查空收件箱的回合。主 Agent 在活跃回合自行读取并 ACK 全部消息也有同样风险。这是本次审查的线索；本子任务没有读取、发送或唤醒真实对话，也未操作真实 daemon，不能把孤立测试当成该原回合的再次取证。

代码证实路径缺口：`HostDeliveryWorker` 按 outbox 通知 dispatcher，忙时 provider 返回 queued；watcher 以后只问宿主状态，不再查询消息的已提交 delivery ACK。宿主变 idle 时，无论该批次是否已被消费都会发送一次拉取提示。

新增真实 SQLite/command/outbox 测试 `test_busy_notification_does_not_wake_after_current_turn_acked_message`，仅宿主 RPC 用隔离 fixture：

1. 宿主 busy，正常 message.send 提交消息及 outbox。
2. drain 后 wake 为 queued。
3. 收件人通过正式 inbox.claim、inbox.presented、inbox.ack 命令在当前回合完成消费。
4. 将宿主置为 idle，等待真实 watcher 检查。

**修改前实际失败：** `host.turns` 出现 turn-0，`ACKed queued notification started an unnecessary model turn` 断言失败。该行为会多启动一次模型回合，并非单纯诊断显示错误。

**修改后同一测试通过：** 无宿主发送、无模型 turn；通知收口且保留明确原因。

## 最小修复

`HostDeliveryWorker` 给 `WakeDispatcher` 绑定一个只读回调，从本项目 SQLite 已提交 messages snapshot 的 deliveries 查询 ACK 状态。只返回布尔结果，要求每个 message_id 存在、recipient 完全一致、status=acked；未知、缺失、查询失败、仅 leased 或 presented 均不能证明完成。

首次 outbox 派发前，以及 never-sent queued 批次每次重试前检查。合并批次必须包含主记录及全部 coalesced 消息，全部 ACK 才收口；主消息 ACK、其他消息未 ACK 时照常发送一次通知。

沿既有 `completed` 终态保存：

```json
{
  "state": "completed",
  "completion_reason": "messages_already_acked",
  "turn_id_digest": null,
  "evidence": [{"kind": "wake_skipped"}]
}
```

这里只完成**通知的生命周期**，不宣布 LLM 回合完成。`wake_completed` 诊断带相同 completion_reason；不生成 host_accepted、turn_started、turn_completed 或虚构 turn digest。已有 presentation、旧失败诊断及 previous_attempts 都保留，coalesced 记录同步终态和原因。没有新增公开状态枚举、Schema、DTO、业务调度器、LLM 决策或用户审批。

`starting/running/unknown` 可能已经由宿主接受，始终继续观察原回合；ACK 不撤销它们，也不能把未知结果改成成功。重启后恢复的 queued 按同一规则检查持久 ACK。

## 锁与边界

SQLite 查询在 dispatcher 全局锁外；宿主 RPC 不持有数据库 writer lock。同 recipient 的新通知合并、ACK 批次检查、provider poll 及结果保存由现有 recipient lock 串行，避免 poll 已发送而另一个线程仍按旧 queued 状态合并新消息。其他 recipient 不等待该宿主调用。

这不是 ACK 与宿主 RPC 的分布式原子事务。最后检查之后并发提交的 ACK 不能撤回已经发出的外部请求；本修复针对检查时已经消费完的通知，不承诺 exactly-once，也不靠跨网络持锁实现。

## 校验结果

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_codex_desktop.py tests/unit/test_hostwake.py tests/integration/test_desktop_wake.py -q
.venv\Scripts\python.exe -m ruff check src/tsunagou/hostwake/dispatcher.py src/tsunagou/platform/host_delivery.py tests/integration/test_desktop_wake.py
.venv\Scripts\python.exe -m mypy src/tsunagou/hostwake/dispatcher.py src/tsunagou/platform/host_delivery.py
.venv\Scripts\python.exe tools/dev/check_architecture.py
```

57 passed、exit 0；Ruff/mypy/architecture 通过。随后单独重跑最初复现，增加并通过“回调不持 dispatcher 全局锁”和“跳过不新增领域事件”断言。测试中仅出现既有 FastAPI on_event 弃用警告。

新增回归覆盖：全部 ACK、部分 ACK、仅呈现、outbox 未派发就 ACK、错误 recipient、缺失消息、已接受与结果未知不可撤销、queued 重启恢复、旧宿主失败历史保留、合并记录原因传播、没有虚构模型完成证据。

规范同步：[FX3 design](../design.md)、[日志与证据边界](../../../spec/backend/logging-guidelines.md)。实际运行 daemon 尚未在本子任务中加载该修复；原宿主的下一次忙时收件测试由协调者实施，W3 实测记录应把“消息已消费、通知跳过”与“宿主实际回合完成”分别统计。
