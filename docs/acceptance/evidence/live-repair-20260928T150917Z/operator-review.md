# 本轮现场验收复核

首次复核时间：2026-09-28T15:33:02.000Z；最近更新：2026-09-29T04:45:48.644Z。人工角色为当前实施主 Agent；这是对实际材料的复核，不是采集脚本自动认证。用户尚未确认整个项目完成。

| 项目 | 结论 | 实际依据与边界 |
| --- | --- | --- |
| A1 独立安装与身份 | pass | 安装 CLI 在独立协调目录运行；一 main、两名用户原先手动创建的 Desktop Worker，各有不同 agent_id。安装与原会话 context 证据见 evidence/original-host.md、manifest.json。 |
| A2 原会话自动唤醒 | pass | 两名原 Worker 于 13:41:33Z 经 daemon 请求进入新回合，用自己的 MCP fetch/present/ACK 并回信；业务回合也由 daemon 触发。见 evidence/message-loop.json。开发者第一次人工 setup 保留为 developer_followup，不算自动唤醒。最后一批队列修复的运行时回归尚待重启。 |
| A3 实际协作交付 | pass | 两 Worker 分别修改 parser 和测试，范围分离；另一个窄范围任务修复页面 origin。三项均实际 submit 并经 main review，见 evidence/runtime-tasks.json、timeline.json、evidence/btid-http-final.json。测试 Worker 因等待构建主动 block 后用一次 begin 创建替代 Attempt；没有 TTL 过期，不把它写成全任务仅一次 begin。 |
| A4 重启与回收 | pass | 同一 SQLite 重启后原 owner 和 running Attempt 保留；原 Desktop Worker 重新 `task.begin` 复用同一 Attempt。main 显式 `task.recover(reopen)` 后，该 Worker 在后续自动唤醒回合亲自调用一次旧 Attempt 的 `task.submit`，被 `capability_denied` 拒绝，无 Result。拒绝发生在权限层，未证明更深层 Attempt 专属错误码。见 [重启恢复](evidence/a4-restart-recovery-20260928T1951Z.json)及[旧提交探针](evidence/a4-stale-submit-20260929.json)。 |
| A5 真实分歧与契约 | pass | 先前两个 Worker 的 UserDecision 核对意见一致，不计入分歧。随后 main 与一名 Worker 对 `task.cancel` 的活跃执行者语义形成真实 hard discrepancy；两个现场探针显示无执行者立即取消、有执行者先 `cancel_requested` 再取消。最终契约由 main 与另一名独立复核的 Worker 接受，分歧已解决；最初报告分歧的 Worker 未接受最终契约。见[分歧与契约](evidence/a5-discrepancy-contract-20260929.json)。 |
| A6 用户重大决定等待 | pass | 真实决定待答期间，相关 Worker 以 `user_decision_pending` 挂起并结束回合，main 提交无关任务。用户通过 CLI 批准同一决定后，主会话收到并 ACK 持久通知，main 自行回收相关旧 Attempt 并通知原 Desktop Worker；该 Worker 在新回合验证决定、用新 Attempt 提交，main 审查完成。主通知因消息已在活跃会话中 ACK 而跳过额外唤醒，不能宣称它另启主会话回合。见[待答证据](evidence/a6-user-decision-pending-20260928T235043Z.json)及[恢复证据](evidence/a6-decision-resume-20260929.json)。 |
| A7 可查询时间与因果 | pass | 安装、三项业务任务执行/提交/审查、失败/自动来源及真实 trace 可查，token 明确 unavailable。新增 project timings 从独立公开 Result.created_at 取得 parser 提交记录时间 14:10:33.066Z，来源标签 result_created_at，可见 submit_events 仍为 0；原私信审计事件继续隐藏。见 snapshots/20260928T164747-c06e35eb/timeline.json、facts.json。 |
| A8 HTTP 与页面 | pass | 真实 HTTP 9/9；新 origin 不手工设 API 地址，正常、CRC 损坏和截断扇区文件在页面分别显示成功/invalid_image/invalid_image。见 evidence/browser-check.json 和三张截图。仍未宣称用户确认最终交付。 |

八项 pass 只表示各项列出的实测事实。A4 的拒绝层级和 A6 主会话通知的回合边界已如实限定；它们不等于用户确认整个项目完成，也不自动关闭 FX6。

## A7 首次失败和修复复测

15:35Z 首次复核为 fail：当时采集仅从用户可见审计事件提取时间，parser submit 引用了私信，因此提交时间是 null。后续查明 Result 自身已有公开持久创建时间，无需改变私信权限或删除旧事件。新增 CLI 复用这一公开事实，并保留明确来源与可见事件数；时间表示 daemon 记录的实体创建边界，不是磁盘 fsync/COMMIT 完成瞬间。16:47Z 使用安装 CLI 重新采集通过：parser 工作经过 740729ms、审查等待 677649ms。此前失败保留在原始记录和早期快照中。

独立源码检查新增 69 项相关回归通过，涵盖真实 HTTP/SQLite、同库重建、幂等、返工 Attempt 区分和错误内容脱敏。原 Worker 也通过 daemon 唤醒完成只读复核并提交 Result `24e9cb06-cdb7-461c-a333-e41bfc1478d4`，main 已审查接受；双方意见一致，不算 A5 真实分歧验收。

## 测试和版本

- Tsunagou：Python 510 passed、3 skipped（513 collected），0 failure/0 error，158.557 秒；证据 [JUnit](../../../../.trellis/tasks/09-28-real-test-repair/research/final-tests.xml)。Ruff、mypy 73 源文件、架构检查、TypeScript 七个工作区 check、Node 34 tests 通过。
- 业务隔离副本：dotnet build 成功；真实 BTID HTTP 9/9、既有 HTTP 回归及 WebUI Node 8/8 通过。
- 本机安装记录：版本 0.1.0，源码 commit 1fb86e08b9cfaab312a9210a3eb15d0108314c36，加未提交修改。测试通过不能将 dirty 代码说成已发布版本。
- 当前 daemon 启动于 13:54:51.611Z，尚未加载后来完成的队列 ACK 去重、计量字段敏感键修复等改动。

## 当时的下一步（历史记录）

1. 已通过正常安装 CLI 对既有协调目录重启 daemon，确认新 runtime 使用同库且身份保留；主会话也已加载并验证当前 MCP bridge。
2. 原 Worker 自己恢复了保留的 Attempt，main 也完成显式回收；旧 Attempt 的提交拒绝尚未由该 owner 实测。不得由 main 借用 Worker 凭据或把 wrong-owner 拒绝冒充 stale-owner 证据。
3. 完成尚缺的认知/用户决定场景；用户决定列表内容/字段与答复通知已修源码，仍需现场加载和验证。A7 查询用独立公开 Result 事实解决，不修改私信审计规则。
4. 重新采集 check/export，复核未通过项，再由用户确认最终交付。原 5080 地址尚未恢复；当前可复查业务页为 http://127.0.0.1:57065/。

## 2026-09-28T18:00Z 现场状态复核

通过安装 CLI 再次读取 daemon 状态，仍为 PID `102616`、runtime `a233923d-af53-48c4-aaf2-286a004cc54e`，启动时间为 `2026-09-28T13:54:51.611Z`。主会话的 MCP 上下文仍返回 `ready`，因此没有刷新 MCP 或重新 enrollment 的必要；新版源码尚未进入 live daemon，A4/A6 继续保持 `not_run`。原始输出见 [live-daemon-status-20260928T180018Z.json](evidence/live-daemon-status-20260928T180018Z.json)。

## 2026-09-28T18:25Z 重启后现场复核

用户已按要求重启 daemon。新进程 PID `103048`、runtime `432243a5-9041-4979-89f9-83c20ddc9cf0`，health 显示当前协议 digest `sha256:f574e1308cb05d16e9833a2570f1476ca718844cbf4daa5e3bd172260142d2b4`。CLI `agent list` 与 `task history` 证实同一 SQLite 中 main、两个 worker 的身份保留，Attempt `6c6b53f3-64b7-4f63-beb8-504276e8c8f4` 仍由原 owner `e5a866e0-3c1c-4ab5-8d11-5becd613cc48` 持有，故 A4 的持久 owner 子项通过。

主会话 MCP 的 `context__project_read` 和 `inbox__claim` 均返回 `schema_bundle_digest_mismatch`。已核对当前 daemon/bridge registry digest 一致，但 Codex 当前 bridge 子进程创建于 2026-09-29 00:56+08:00，当前 bridge 文件构建于 01:51+08:00；旧进程仍在内存中运行旧摘要。A4 的原 owner MCP 恢复和主 Agent 显式回收旧 Attempt fence、A6 用户决定闭环继续未验证。需完全退出并重启 Codex 一次以重载 bridge；无需重新 enrollment。详见 [daemon restart and bridge digest evidence](evidence/daemon-restart-bridge-digest-20260928T182511Z.json)。

## 2026-09-28T18:47Z bridge 重查

主会话再次调用 MCP，`context__project_read` 与 `inbox__claim` 仍返回 `schema_bundle_digest_mismatch`；最新 Codex bridge 子进程创建时间未变化。尝试通过当前 bridge SDK 创建一份隔离只读 context probe，进程启动在策略检查阶段被拒绝，未创建进程、读取路由凭据或修改状态。故仍须正常退出并重开 Codex，让宿主监督器重启 bridge。证据见 [Codex bridge recheck](evidence/codex-bridge-recheck-20260928T184725Z.json)。

## 2026-09-29T04:45Z A4–A6 后续现场收口

原 Desktop Worker `e5a866e0-3c1c-4ab5-8d11-5becd613cc48` 在用户批准后由 daemon 再次唤醒，并在自己会话内对已 `orphaned` 的 Attempt `6c6b53f3-64b7-4f63-beb8-504276e8c8f4` 调用一次 `task.submit`。daemon 于 02:38:32.406Z 记录 `command_rejected/capability_denied`，没有 Result，Task 保持 open/revision 6。这个结果证明旧 Attempt 在外部不可提交；这次权限层提前拒绝，不能声称验证了更深层的 Attempt 状态错误码。

另一组真实认知报告对活跃任务取消语义产生 hard discrepancy `f7bf105d-ebe5-4512-b828-bd480fa04c3a`。main 用两个真实任务分别验证无执行者即时取消、有执行者先请求取消；最终契约 `b3e8f48c-e1c7-4c55-9ced-2c1dc1421c25` 于 03:40:10.703Z 由 main 和第二名 Worker 接受，分歧于 03:41:28.999Z 解决。首位报告分歧的 Worker 因早先退出意图未接受最终契约，故接受者身份必须保留在证据中。

用户决定 `f1396c86-ae11-4ce9-b499-281367fb5202` 于 01:58:52.747Z 经 CLI 批准。主会话的持久通知已 ACK；诊断显示其额外 wake 为 `messages_already_acked`，不算一个新的主会话回合。main 显式回收被阻塞的旧 Attempt，原 Desktop Worker 在新回合领取通知、验证决定、新建 Attempt `eb5a1efa-d499-4039-a6bd-d8e2e0bbc35f`，02:13:14.340Z 提交，02:58:09.115Z 经审查完成。此前无关任务在决定待答期间照常提交。以上均为现场已发生的状态，不推导用户对整项目的最终确认。
