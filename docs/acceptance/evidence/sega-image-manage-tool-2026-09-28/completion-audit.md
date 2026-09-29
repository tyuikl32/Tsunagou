# 交付收尾审计

时间：2026-09-28 06:26 UTC 后。本轮目标保持为：真实项目部署、独立 main 和两个 Worker 交付 WebUI + HTTP，检验 A2A、效率、租约/冲突/协商持久化和 OTel 责任链。

本文件不把失败项改成通过。用户已要求先完成业务任务、记录问题、事后复盘；用户完成确认问题已经发出，尚未收到答复。

| 要求 | 当前证据 | 判断 |
|---|---|---|
| 真实部署与启动 | deployment-record、restart-record、delivery-file-manifest；health/UI HTTP 200 | 可运行，安装存在手工修正 |
| 独立 main、两个 Worker | coordination-record、host-turn-timing、worker result 与 review 事件 | 已证明；业务实现由两个 Worker 完成 |
| WebUI + HTTP 功能 | 构建和 API/Node 测试、真实错误路径、有效合成 BTID 响应与截图、16 文件 SHA256 清单 | 基本业务路径通过；不宣称覆盖所有真实镜像或修复既有 parser 缺陷 |
| A2A HTTP | a2a-http-record、a2a-receipt-record | 发送、查询、去重、越权拒绝及实际收件闭环通过 |
| Desktop 原生唤醒 | native-wake-binding-record、native-wake-http-record、native-wake-diagnosis | 未通过；配置补齐后，现有宿主 writer 拒绝外部 resume |
| 效率 | timing-record、host-turn-timing | 已分别统计墙上时间、授权窗口、宿主回合；installer 精确起止和 token 费用不能补造 |
| 租约与冲突 | task history、resource 事件、scope 变更与恢复记录 | 有过期、重领、冲突与解决证据；准备阶段 TTL、重复恢复决策仍是缺陷 |
| 协商和关键操作 | cognition/contract/task review audit | 有记录；slot 编码及 withdrawn→proxy accepted 状态跃迁未修复 |
| 查询、时间和重启 | public-query-record、public-query-after-restart | 查询不新增业务事件，时间与 actor 可追溯；仅验证 genesis checkpoint |
| 失败诊断 | native-wake-diagnosis | 缺该 provider 错误的终态诊断；fallback presentation 不能证明 native wake |
| OTel blame | 当前源码、依赖和 audit schema | 未实现 instrumentation/exporter/event↔trace-span，不得标为通过 |
| 重复旧任务 | closeout-state | main 已将两项早期任务改为 cancel_requested，不再可领取；ownerless terminal cancellation 未实现 |
| 用户确认总任务完成 | 尚无用户答复 | 父任务仍 open，不伪造 completed 或最终 checkpoint |

## 收尾动作

两个替代 Worker task 已 completed。早期任务 `93ffd4c0-c4ad-4401-bccb-0f3fcacb0b31` 和 `f98e9640-a150-4a22-a37a-6e58fb4ae11e` 曾仍为 open，主 Agent 于 06:26:14 UTC 连续执行取消请求，在原因中引用对应已完成的替代任务。状态均为 cancel_requested、revision 4；没有历史删除、虚构 owner ACK 或直接数据库修补。

源码 claim 只接受 open/blocked/orphaned，因此取消请求已阻止这两项重复领取。但命令目录约定无 owner 时应直接 cancelled，当前实现没有完成这一步，作为缺陷保存。

收尾快照没有非终态 Attempt、有效执行 Lease 或有效 attempt Grant；三个 Codex 会话均已结束最近一轮并待命。公共 ID、UTC 时间、actor 和因果 command 见 [closeout-state.json](closeout-state.json)。业务文件清单与当前 HTTP 存活证据见 [delivery-file-manifest.json](delivery-file-manifest.json)。

本轮不得自动跨过用户最终完成确认，也不能通过删除 live writer 锁或替换 Worker 身份让唤醒通过。平台修复和效率重构保留到交付后的复盘，不在收尾时静默改变原协议。完整证据入口见 [交付报告](delivery-report.md)。
