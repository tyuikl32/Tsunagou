# FX3 宿主适配设计

## 实现位置

新增 src/tsunagou/hostwake/codex_desktop.py，放 NativeAppToolsClient 与 CodexDesktopProvider；复用 port.py、binding.py、dispatcher.py 和已有 provider registry。不要为 Desktop 再建一套 A2A、消息库或任务状态机。保留 managed app-server；替换当前 DesktopAttachProvider 中“独立 listener 读取后 resume”的默认路径。

客户端只支持本任务所需工具调用、读状态和关闭。管道格式按本机插件已读代码：4 字节小端长度 + JSON-RPC；请求和响应关联 ID；限制按宿主当前上限，断线结束 pending 请求。直接用系统管道/Unix socket 库，不安装一个新的消息中间件。平台差异留在此文件的传输实现。

## 接入和绑定

继续使用现有 /api/v1/host-wake/bindings 的 U 控制边界；正常用户体验由 FX4 connect 封装，不要求用户单独调用。ticket 创建时保存宿主接入请求，enrollment 消费该请求，自动绑定兑换出的 agent_id。不得给普通 bridge 一个可绑定任意 Agent 的 U 接口。

私有记录扩展 provider=codex_desktop_app、真实 target_thread_id、endpoint、host_generation、原接入 caller 信息、app/plugin 版本和连接更新时间。原始值只保存在既有 private binding store。公开项目上下文只显示 provider、是否连接、最近触发/失败时间和对应原因。caller thread 和目标 thread 不混用；每个绑定只能指向其已确认的原会话。

管道由宿主环境 CODEX_APP_TOOLS_PIPE_PATH 和当前会话上下文自动取得，禁止扫描所有进程/管道猜测。稳定会话身份按宿主明确 metadata 绑定，不能拿 profile 名当 conversation ID。同项目两个会话对应两个 Agent；同会话重连复用其身份。

宿主重启后的刷新并入现有 session.reconnect（D 权限）的私有 host_binding_refresh 字段：provider、endpoint、host_generation、app_version、plugin_version。只刷新已由 U 接入意图授权的当前 session/Agent，target_thread_id 从既有绑定取值，不能通过刷新改目标或创建任意绑定。此字段不进入公开事件/receipt；正常业务请求不每次重连。FX3 实现服务端及现有 bridge 启动/恢复处的最小刷新调用，FX4 负责安装与接入体验，避免两任务互相等待。

## 消息到回合

1. A2A 或 MCP 的 message.send 共用持久消息事务和 outbox，提交后才唤醒。
2. dispatcher 按 recipient+message 去重，将同一个空闲 recipient 尚未处理的消息合并为一次“读取项目收件箱”通知。
3. provider 经宿主 tools/call 调用 codex_app.send_message_to_thread。arguments 只包含绑定的 threadId/hostId 和最小拉取提示；提示可带一次 wake_attempt 的脱敏关联引用，供响应丢失时匹配原回合，不放 thread/session 原值。不传 model/thinking，不复制消息正文，不发代码任务替代收件箱。
4. 外层 callerSource/threadId/turnId/callId 遵守宿主插件实际调用契约。第一步实测确认会话空闲后合法的调用上下文；不借历史 turnId 冒充活跃模型回合。request ID 是此次适配器请求的关联，不宣称为模型 turn。
5. 宿主接收记 accepted，实际回合开始才记 running；实际 Agent inbox pull/present/ACK 分开记录。若发送返回没有 turn ID，用原会话的轻量状态/增量读取确认，不拉取全量 transcript。
6. active 时保留 pending 通知。利用已有宿主事件或有界 wait_threads/read 状态等待当前回合结束，再发一次通知；不启动定时 LLM 看守。普通进程状态轮询不等于模型轮询，不产生 prompt/token。
7. 一个线程的用户重大决定等待不使无关任务全停；通知只是让 Agent 读新增上下文，继续、挂起或升级由 main/worker 按任务关系判断。

W3 实测修正：排队期间 Agent 可能已在当前回合读完并 ACK 新消息。首次 outbox 派发以及从 queued 重试前，由 HostDeliveryWorker 向 dispatcher 提供项目内、匹配 recipient 的已提交 delivery ACK 查询；整个 coalesced 批次全部 ACK 才结束这次通知。沿既有 completed 终态写 completion_reason=messages_already_acked 和 wake_skipped 证据，不能据此制造 turn_completed 或证明某个模型回合的触发来源。部分 ACK 仍须通知；starting/running/unknown 可能已被宿主接受，继续核对原回合，不用 ACK 撤销。查询不持有 dispatcher 全局锁，宿主 RPC 不持有 SQLite writer lock；同 recipient 的合并、检查和状态提交串行。此前失败和消息事实都保留。

## 超时、重启与去重

消息提交成功不因唤醒失败回滚。确定拒绝写失败；请求可能已被宿主接受但响应丢失时为 unknown，先检查同一目标是否出现对应回合/消息处理再重试，不声称 exactly-once 或盲发第二条。保留已有 wake_attempt_id 的失败历史，新尝试关联前次 ID，不删除历史以覆盖失败。

daemon 重启先恢复 private binding 和未完成投递，再核对原会话；不创建替代身份。Desktop 管道变化时，新启动的 Tsunagou bridge 注册新 host_generation；旧连接的迟到响应不能写新代状态。重连不撤业务资源占用。

当前 watcher 的固定五分钟观察窗口不能把仍待处理的消息永久搁置。一次观察窗口结束只结束观察请求，持久 pending/unknown 由既有调度循环继续核对；不靠无上限忙循环或新 LLM 回合维持。Desktop 重启后的 running/unknown 先核对原会话，不能套用“受控进程已消失”的恢复结论。

连接不可用是投递失败，不改 Task 为业务 blocked。FX5 补充终态诊断；本任务先保证 provider 每条失败路径都给结构化结果。只通过实际请求观察，不引入阻挡正常任务的能力证书或逐条探测。

## 第一项工程验证及停止条件

必须实际验证 W1/W2 和宿主自身权限/确认流程，尤其是主 Agent 也已 idle 时的触发。若工具调用依赖仍活跃的宿主回合，或要求每次用户确认，当前实现还不满足目标；保留真实失败并继续修同一 provider，不能切换为“由主 Agent 持续代发”。这个工程验证在 FX3 中完成，不要求用户再决定要不要唤醒。
