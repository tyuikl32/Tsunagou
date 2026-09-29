# 原 Desktop 实测进展与偏差

本记录延续 FX3/FX4 的实测材料；时间全部 UTC，初始记录于 2026-09-28T14:27:00.000Z，后续结果按序追加。仍在验收，不能将此记录作为 A1–A8 全部通过。

## 已发生的事实

- 用户确认 Codex 设置可见 tsunagou，但没有刷新按钮。不得要求用户找不存在的入口。主会话随后实际 MCP context 返回原 agent_id、main、ready，两个原 Worker 的消息回复闭环已通过。早期失败及修复见 [原宿主记录](../../../../.trellis/tasks/09-28-fx4-onboarding/research/live-original-host-20260928.md)。
- 独立安装来源 D:\Tsunagou，commit 1fb86e08b9cfaab312a9210a3eb15d0108314c36，含未提交修复。首次安装 12:57:52.468Z–12:57:57.275Z，4.807 秒。保留 extras 的复装 13:53:53.933Z–13:53:56.462Z，单调时钟 2528ms。安装入口为 C:\Users\Tyuikl\.local\bin\tsunagou.cmd；业务目录不复制源码。
- daemon 消息于 13:56:08Z 派发，两个原 Worker 回合于 13:56:09Z 实际开始。业务工作位于 D:\ALL.NET\SegaImageManageTool-fx20260928；原业务目录未覆盖。任务及基线摘要见 [运行时任务](../../../../.trellis/tasks/09-28-fx7-btid-integrity/research/runtime-tasks.json) 和 [复制基线](../../../../.trellis/tasks/09-28-fx7-btid-integrity/research/baseline-copy.json)。
- parser 任务 74f34f37-f3df-44ef-a5f0-8991de6243b7 完成 Modules/Btid.cs 的完整读取、CRC/HMAC 拒绝、checked 尺寸及固定缓冲。首次 build 14:06:11.474Z–14:06:19.587Z；退出 0，73 个既有警告。main 于 14:21:50.715Z 审查接受；这不等于用户确认最终项目完成。
- 测试任务 b335f087-790b-421f-bb39-e65a961774d7 于 13:57:37.697Z begin，14:04:43.982Z 主动 block 等待构建，旧 Attempt 046b861e-ef93-4b6e-8842-7861209be5a7 释放占用。main 收到请求即回复并在构建就绪后通过 daemon 消息恢复；新 Attempt 为 bfbf7ee8-ab0b-45a1-a734-34e23dab401d。没有 TTL 过期，也不需重新选工作区。
- main 曾误说 blocked 后“不重复 begin”，查实际状态后明确更正：running 同 owner 重连恢复同 Attempt；主动 block 已停止执行，恢复需一次 begin 新 Attempt。不能把这两个场景混为一谈，也不能把本次有依赖暂停的任务统计成只有一次 begin。
- 真实 HTTP 于 14:17:32Z 验证 9/9 样例：正常 200；短头按既有 handler 为 400/file_too_small；其余 CRC/HMAC/截断/非法尺寸为 422/invalid_image，requestId 头体一致。请求 4.58–77.52ms，这是 HTTP 耗时，不是 Agent 工作时长。Node 6/6，既有 HTTP 回归通过。原始报告在业务 checkout 的 tests/Fixtures/Btid/http-result.json 和 validation-summary.json。

## 后续实测暴露的偏差

1. 忙时消息已在当前回合 ACK，队列仍可能在回合结束后触发空收件箱检查。隔离 SQLite/outbox 回归已实际复现。修复仅跳过尚未发送且整批已 ACK 的 queued 通知；不取消 unknown/已接受的发送，不把跳过冒充真实 turn_completed。代码已过回归，当前 daemon 尚未加载。
2. 普通通知的 token_usage/tokenUsage=unavailable 被敏感键子串匹配误当凭据，inbox.fetch 多出私有交付包装。观察消息 84427dc2-4268-4c65-9f05-27a09c57521d（14:11:40.975Z）和 a0cb9a0c-d835-4dcb-b97b-86b8b3929bf9（14:22:47.421Z）。修复允许计量字段，仍递归检查其内部真实敏感键；不在此保存 receipt 或私信正文。
3. 消息目录/schema 与 MCP 实际参数不一致：send 被 escaped pipe 截断，respond/fetch 保留旧字段。正在以当前实际语义统一目录、schema、MCP 和 fixtures；同版本整体加载前不宣称生效。
4. 浏览器实际打开本轮服务 http://127.0.0.1:56416/ 后，页面显示 Service unavailable，连接设置仍为 5137。后端可服务页面和 health；根因是前端固定默认端口。这是 HTTP 脚本与 API mock 测试未覆盖的真实 UI 缺陷。窄范围任务 a4bf07a7-acf8-4253-94c8-f69a193ba276 已由 Worker 修复：保留有效的显式用户配置；没有有效保存值时，同源 loopback 页面默认使用当前 origin；非本机页面仍退回安全固定值，不扫描端口。Node API 测试 8/8 通过，JS 语法检查通过。
5. 真实 CLI task history 中 parser 的 `task.begin`、`task.review.accept` 可见，`task.submit` 看似缺失。只读核对 SQLite 证明 submit 已持久化（event_seq 79，发生时间 `2026-09-28T14:10:33.066Z`）；用户 CLI 的单事件查询返回 `audit_event_access_denied`。根因是这个 submit 事件的显式 `evidence_refs` 包含一条仅 Worker 与 main 可见的私信引用。当前约定要求显式证据整体授权，user_control 不继承消息收件人权限，所以 history 与单事件查询都正确隐藏整个事件。没有改权限投影或从 review 推导时间；用户 CLI 的 submit 时间仍应显示为未知。修正应由后续提交避免把仅作通知的私信引用当成共享 task.submit 证据；如需让 U 在保留私信隔离的同时看到含此类引用的 submit 行，需先明确调整证据投影规则，不属于本轮擅自改变。
6. 修复前，在页面手工设为 `http://127.0.0.1:56416` 后 health 显示 Service online · v1.0.0.0。14:34Z 上传 `valid.app` 实际 HTTP 返回成功并显示 `FX7T/BTID`、2 sectors、16384 bytes、正确文件名和 request ID `3d03f98c-c4e7-4d1d-a231-af5268e07d5a`。随后上传 `crc-corrupt.app`，页面展示 `invalid_image` 和校验错误信息，不显示 API unreachable。这证明旧 UI 能处理后端结果，但手工设置掩盖了首次默认地址问题。
7. 14:51:17Z 为同一隔离业务 checkout 在新端口启动第二个实例 `http://127.0.0.1:57065/`，health 返回 200。通过 Codex 内置浏览器创建该端口的新 origin；连接设置此前无保存值，页面初始状态即显示 `Service online · v1.0.0.0`，展开设置后 `Local API origin` 为 `http://127.0.0.1:57065`。这验证了真实页面按当前 loopback origin 选路及 health 请求成功，不依赖 56416 手工配置。FX7 的 HTTP 9/9 与修复前同页成功/损坏样本证据仍分别有效；本次只在新 origin 验证自动地址和 health，没有再次上传文件。新实例地址及启动时刻见 `business-origin-test.json`；浏览器保留该页供人工复查。
8. 15:07Z 用最新隔离 checkout 重跑真实 HTTP 完整性脚本，9/9 通过；合法样本返回 FX7T/BTID、2 sectors、16384 bytes、header CRC valid，CRC/HMAC/截断/非法 offset/size 均按预期返回 400/422，头体 requestId 一致，最慢 67.26ms。报告为 `btid-http-final.json`。同一轮 `dotnet build --no-restore` 成功，0 warning/0 error；既有 HTTP 回归通过，WebUI Node 测试 8/8，两个 JS 文件语法检查通过，业务 checkout `git diff --check` 通过。
9. 15:09:18Z 通过 FX6 工具创建新鲜验收快照 [live-repair-20260928T150917Z](../live-repair-20260928T150917Z/summary.md)，实际安装 CLI 查询及 OTLP 导出均成功。快照包含 1 main、2 个不同 Worker、6 个 Attempt 和 168 条匹配 span；A1–A8 保持 `not_run`，项目确认 `unverified`。它记录 parser 的 user-control history submit 时间为 null，不作推算；HTTP/页面证据与 Agent 任务事实分开保存。
10. 15:15Z 检查用户原 URL `http://127.0.0.1:5080/` 时没有监听进程，请求超时；验证端口 `57065` 的真实页面和 `/health` 正常。尝试将已验收隔离 build 启动在原端口，以恢复原 URL，但本机命令策略在进程启动前拒绝，命令未执行且未改走其他启动方式。现有可复查页面保持在 `http://127.0.0.1:57065/`；原 5080 的恢复仍待用户本机操作或策略状态改变。

## 恢复场景安排

新建非文件任务 357de2e9-8990-4c1e-b99f-365057d29732，由 parser Worker begin、保存实际只读证据后结束回合，按明确测试指令故意保留 running。随后尝试按任务设计用已安装 CLI 对同一个测试 daemon 执行 `daemon stop`，但本机命令执行策略在启动 shell 前拒绝了该进程控制命令；命令没有执行。再次读取只读状态确认 daemon 仍为 PID 102616、runtime `a233923d-af53-48c4-aaf2-286a004cc54e`、原启动时间 `2026-09-28T13:54:51.611Z`，健康端点仍可访问。因此本轮没有发生 daemon 重启，也没有验证 post-restart 原 owner 恢复、显式回收或拒绝旧 Attempt；不得标 A4 通过。未尝试用其他进程终止方式绕过该限制。

token 用量均 unavailable。未提交 Git，未操作原业务数据库，未将用户尚未确认的交付写成 completed。

## 2026-09-28T17:44Z A5 独立核对补充

为避免把一致性演示误记成认知分歧，main 通过现有 daemon 给两个原始 Desktop Worker 发布了两个独立的无文件核对任务。两个 Worker 分别 begin、读取各自实际 MCP/CLI/协议证据、提交 cognition report 和 Result；main 逐项 present/ACK 并审查接受。报告都认为 `user_decision.propose` 的 `proposal_digest` 可省略且由 daemon 计算，`resolve` 必须含 `decision_id`、版本和 digest。两者没有真实理解差异，未创建 discrepancy 或 contract，A5 仍为 not_run。任务/result 引用和结论见 [A5 evidence](../live-repair-20260928T150917Z/evidence/a5-independent-interface-check.json)。

## 最终页面与逐项复核补充 — 2026-09-28T15:35:25.700Z

在新 origin 57065 无手工配置下，已实际上传 valid.app、crc-corrupt.app、truncated-sector.app，页面分别显示成功、invalid_image、invalid_image。browser-check.json 记录 request ID 与三张截图；它补齐前述第 7 项当时只检查 health 的局限。

Python 全量 510 passed、3 skipped，0 failure/0 error（513 collected，158.557 秒）；Node 34 tests、七个工作区 TypeScript check、Ruff/mypy/架构检查通过。逐项验收见 [复核记录](../live-repair-20260928T150917Z/operator-review.md)：A1/A2/A3/A8 通过，A4/A5/A6 尚未完成，A7 的私信证据导致用户 CLI 时间不可见未满足。整体任务仍未完成。

另记录一次真实 Worker 调用偏差：14:28–14:41Z 回合首次 contract.accept 缺 participant_slot 且 digest 不完整，被拒绝；随后用实际 digest/slot 成功。未绕过校验，不能把失败调用计为接受成功。认知报告与双方契约已发生，但不是已证明的分歧协商完整场景。
