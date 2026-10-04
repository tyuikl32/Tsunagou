# 实际验收收口：最小执行矩阵

2026-10-04，只读准备。依据 approved-v2、当前 bridge/reminders、wake_assistance、Codex host-wake 文档及已有验收记录。本文没有执行接入、发消息、唤醒或完工提案，不代表验收通过。

## 当前前置条件

- 主会话目前 not_enrolled，无可用的当前项目认证；用户尚待选择验收项目及真实宿主成员。不得用 fixture 身份或 Trellis 子 Agent 冒充真实成员。
- 所选项目使用包含本次修改的实际 daemon、bridge 和打包脚本；原会话 tools/list 能看到 coordination__peer_hosts、coordination__wake_status、coordination__wake。刷新常驻上下文后记录实际版本/构建摘要。
- 各成员在自己的原会话执行 context__project_read，核实 project_id、agent_id、main_agent_id、ready 与真实宿主。原始宿主会话 ID、route 文件、token 不进入报告。
- OpenCode CLI 与服务须均为 2.0.18，模型已有可用业务回应。上次默认模型 provider.auth/403 未解决；不能把更换模型或新会话测试说成旧原会话已经恢复。
- Codex 原生通道需要已有项目开关及当前有效 binding。关闭或绑定缺失是前置阻塞，不自动开开关、重绑或切换补位脚本。

## 成员拓扑与范围

核心三成员可覆盖三个方向和两条路径：Codex main M、Codex Worker C、OpenCode Worker O；均为用户选定、已认证且同机的真实原会话。

该拓扑可证明 M→O 的跨宿主补位、C→M 的原生任务提交通知、C→O 的 Worker 直接补位，外加 M→C 原生派发。它不能证明所有宿主排列。若本轮还要求 OpenCode→OpenCode 以及“补位直接唤醒 main”的实测，需要用户选定的 OpenCode main 与另一 OpenCode Worker（可在独立验收项目），不可擅自改现有项目主控身份。OpenCode→Codex 无覆盖时只验收真实降级；DSH 未验证形态同样允许明确 unsupported。

## 按顺序执行

| 步骤 | 原会话操作入口 | 必须保存的脱敏证据 / 通过条件 |
| --- | --- | --- |
| 1 身份与首次指南 | 各成员 context__project_read `{}`，coordination__peer_hosts `{}` | 认证角色正确；真实 host/version/machine/evidence，不把模型品牌当宿主。每个尚未见过当前 GUIDE_VERSION 的成员收到完整指南；仅 main 有完工提醒 |
| 2 去重与安静调用 | 同一成员重复 context__project_read；重载其 bridge 后再读；普通查询、ACK、义务关闭 | 首次指南同版本不重复，重启不重复；其他 Agent 独立计数。不删除去重记录来伪造首次结果。普通调用无唤醒长文，main 上下文的完工提醒是预期行为 |
| 3 M→C 原生 | main 用 coordination__plan 定向派发一个真实、限定范围的验收任务；读取返回 assignments[].message_id，再 wake_status | lane=native，只保留原生路径，不出现补位 wake 入口；原生证据 thread_resumed/turn_started；C 在原会话读取任务，不产生第二条启动路径 |
| 4 M→O 补位 | main 用 message__send 发需回应消息，显式 response_contract.required=true；按返回 message_id 执行 wake_status，允许后显式 wake | 附加短提示且 content[0] 保持业务 JSON；身份本机且原会话存在；实际 PowerShell→安装 CLI 链路驱动 O；O 读取消息并发送关联业务回复 |
| 5 C→O Worker 互唤 | C 自己 message__send，自己 wake_status/wake；main 不代调用 | 认证调用者为 C；O 原会话出现一次输入并读取、关联回复；没有扩大 worker scope。第二次同 message_id wake 不追加输入 |
| 6 C→M 结果审查通知 | C 在其拥有任务 task__begin/完成/task__submit；读取简短提示中的 message_id（业务提交 JSON 不新增字段） | submit 成功附加待 main 审查的短提示；main 原生接收该 task.submitted；提交者自己可查状态，不能读取 main 私有收件箱 |
| 7 验收与完工提示 | main 对真实结果 task__review_accept，或仅在策略许可且原 owner 正确时 task__self_accept | 成功后只有 main 有条件完工提醒；无唤醒长文。worker 审核场景不收到面向自己的完工提案指令 |
| 8 完工提案前端 | main 核对全部工作、合并、验收与实际 objective；无待确认提案后 project__completion_propose | 返回 proposal_id/status/revision；前端出现真实待用户确认事项；项目尚未 completed。记录前端截图/结构化 UI 状态。不要代用户确认，也不要为验证 UI 假报源代码项目全部完成 |

若成员已经看过当前版本指南，步骤 1 的“初次全文”使用既有真实记录或用户批准的新接入成员，不通过篡改持久记录制造条件。桥重启只作用于选定验收桥，不无差别停止共享 daemon。

## 可执行消息闭环

发送者在自己原会话调用：

```json
message__send {"recipient_agent_id":"<已核实目标>","summary":"验收请求：读取本消息后返回约定结果并关联原消息；不接入新成员、不修改项目权限。","response_contract":{"required":true}}
coordination__wake_status {"message_id":"<实际返回值>"}
coordination__wake {"message_id":"<同一实际返回值>"}
```

只有 status 的 entry.tool 为 coordination__wake 且实际状态允许才执行第三步。接收者由自己的 inbox__claim/fetch 读取，使用 inbox__presented 记录呈现，按真实返回字段 ACK。随后 message__send 到原发送者，设置 in_reply_to 为原消息、response_contract.required=false，避免验收回应递归制造义务；再 message__respond `{obligation_id,response_message_id}` 关闭原义务。发送者再次 wake_status 检查业务回应证据。

每个消息记录四项独立结果：durably_received、host_turn_started、presented、business_response，以及证据时间和引用。OpenCode 通用查询仍可能 host_turn_started=false（未证明）；仅在原会话自身存在实际关联执行记录时另列实机证据，不能改写为通用接口已证明。ACK、queued、exit code 0 均不替代其他阶段。

## 边界与失败验收

- Codex 普通 message 即使 required=true 也不是现有 WAKE_WORTHY_KINDS；不能用它要求原生自动启动。本轮原生实测用 task.assigned/task.submitted。当前原生还有 task.reviewed/contract.proposed/contract.revised/user_decision.resolved 触发，与提醒是否追加无关。
- 明确闲置与忙碌只看宿主证据；忙碌排队另记 can_queue。未知、超时先查状态，已有尝试不抹记录重试。不在真实项目刻意破坏凭据/宿主版本来复制已过的异常模拟测试。
- 若原生开关关闭、原会话锁定、OpenCode 403、DSH unsupported，保留实际阻塞。先核对目标宿主/版本/机器/会话；worker 升级 main 一次，不要求用户手动唤醒。
- 越项目、无关联消息、过期身份、并发、异常版本等沿用既有自动回归证据；若本轮声称“真实验证”必须额外标明真实入口与结果，不能沿用 mock 标签冒充。
- 真实完工提醒验收与用户确认完工分开。若还有失败项，只可对独立验收项目已达成且用户确认过的目标提出完工；源代码项目保持实际未完成状态。

## 本次准备的审查结果

没有修改产品代码。Lint/TypeCheck/Tests 本次未重跑，按父任务要求复用此前通过结果；此文件是可执行准备，不是新的质量门通过报告。

待父会话解决的实际阻塞：选择并核实真实项目成员、让原会话加载本次运行版本、解决可用模型业务回应、核实已有 Codex 原生通道可用；然后逐行填入真实证据。现有三成员核心矩阵通过后仍须明确同宿主补位是否已覆盖，不能笼统声明全部排列通过。
