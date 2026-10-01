# D185：唤醒听项目开关，醒不了就收尾，一次只走一条路

日期：2026-10-01。来源：落实 D184“未做与边界”里剩下的四条（项目级开关、能力协商、Desktop 降级、`unknown` 兜底与保留上限），并消掉 A2A 与后台工人重复派发唤醒的那条路径。

## 决定

1. **项目级开关真的控制唤醒**：投递工人在每轮派发前读项目策略 `auto_wake_multi_agent`，读到“关”就不派发。**开关读不到 = 关**，与界面/上下文快照展示的值一致；`project.configure` 在运行中改动能立刻生效，不需要重启。关闭期间**“待唤醒”行保持 `pending`**：那行是唤醒意图而不是一次性的提醒，所以重新打开会把攒下的补投出去，而不是丢掉。
2. **能力协商参与决策**：派发前先看绑定的能力。宿主在方法目录（method catalogue）里明确没有唤醒需要的方法时，记为 `unsupported` 而不是 `unknown`——**有目录却说没有**是确定答案，没有目录才是不知道。命中 `unsupported` 的绑定直接判 `host_wake_capability_unsupported` 并转终态，不排进重试。探针只有在**证明**唤醒路径可用（`supported`）时才把绑定恢复为 `ready`。
3. **失效绑定不再被当成临时故障**：绑定状态不是 `ready` 时分两种结局——`degraded` 是已经判定过“这条唤醒路径不通”，报 `host_binding_degraded` 并直接收尾；`stale`/`detached` 还可能靠重连恢复，保留重试。
4. **Desktop 占用会话显式降级**：`desktop_thread_unavailable`（真实场景是 Codex 自己握着那个 thread 的写入权）、`desktop_thread_required`、`desktop_thread_identity_mismatch`、`desktop_attach_transport_unsupported`、`desktop_attach_endpoint_invalid` 归为确定性失败：尝试以失败收尾并写 `wake_failed` 诊断，同时把绑定标为 `degraded` 并把原因留在绑定记录里。反过来，一次成功的探针会把它恢复成 `ready`。
5. **一次消息只走一条唤醒路径**：A2A `message/send` 不再在请求里同步派发唤醒。它只登记“回调到了”这个事实（`callback_received` 诊断），并在响应里如实说明通知是**已排队**（`staged`）而不是已送达；真正的派发只发生在后台投递工人消费 durable outbox 行的那一处。重试判定因此只剩一份。
6. **`unknown` 有终点**：daemon 重启会把在飞的尝试标成 `unknown` 并记下起始时间；超过宽限期（默认 10 分钟）仍无人观测到，就转 `failed`（`host_wake_unknown_expired`）并留下记录。“不知道成没成”不再是永久状态。
7. **两个日志文件有保留上限**：唤醒尝试流水最多保留 500 条、诊断流水最多保留 2000 条，**只裁已经收尾的历史，在飞的记录一律保留**，合并别名不会因为裁剪而指向不存在的尝试。两份文件本来就是每次变更整份重写，无限增长是体积与性能隐患。

## 未做与边界

- **不新增控制台界面**（沿用 D184 的边界）：数据与查询接口已齐（`wake_attempts`、`diagnostics`），界面由使用者自行设计。
- 唤醒记录仍在 JSON 文件里而不是数据库：本轮只加了保留上限，没有迁移存储。
- bridge/适配器自报的 `wake.push unsupported` 仍未进入 daemon 的绑定能力记录；daemon 现在读的是**宿主侧方法目录**得出的能力。

## 影响

- `docs/implementation/codex-host-wake.md` 的“什么时候才打扰宿主”补上开关与收尾规则。
- 根文档 `Tsunagou-消息共享与唤醒机制.md` 的 §5/§6/§7 收敛为“已修完”，实现记录并入 §11。
