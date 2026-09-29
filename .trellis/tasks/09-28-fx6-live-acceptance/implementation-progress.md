# FX6 implementation progress

状态：验收工具与首次实测操作单已完成，FX6 现场验收仍在进行；不得据此把 FX6 或总修复计划标为完成。

## 工具实现

- `tools/dev/live_repair_acceptance.py` 提供 `prepare`、`check`、`export`。`prepare` 为新 UTC run 初始化 A1–A8 未执行表和证据索引；重复覆盖已有 run 会失败。
- `check` 调用安装 CLI 的 `installation-info`、`doctor`、`agent list`、`project diagnostics`、`project timings`、逐页 `project history`，输出每次查询的 UTC 观测/结束时间、耗时/结果类别、安装登记、daemon 注册事实及 agent/task/Attempt 摘要。它不写协调域状态。
- Attempt 时间复用实际 `project timings` 输出：begin/review 使用可见事件，submit 可使用独立公开 Result.created_at 并明确来源；没有可靠来源才为 null，不从 review 状态倒推。原 audit rows 不补造，隐藏 submit 仍保留可见事件数 0；替代 Attempt、重复 event、矛盾来源和不一致时钟均不伪装成功。
- 输出限定为显式字段。token、凭据、原始 thread/session/pipe、消息正文、诊断 details、私有会话值及任意 CLI 错误正文不会写入证据。`export` 只读取真实本地 collector NDJSON 的五种边界 span，要求结构有效且 project id 匹配；不改 collector 原始文件。
- `review.json` 接受 A1–A8 的人工 `status`、UTC `observed_at`、本地相对 `evidence_refs`。pass 必须有有效观测时间和存在于 run 内的证据文件；人工来源会在导出中标明。人员数量、ACK、diagnostic、OTel span 和健康查询均不会自动通过 LLM/原宿主实测。
- [首次实测操作单](../../../docs/acceptance/live-repair-first-run.md) 给出安装与项目定位、prepare/check/export、每个原 Desktop 会话自己的接入、实际任务、真实 BTID HTTP 检查和结论门槛。它说明当前 Codex 没有刷新按钮：现有原会话先直接查 context；只有首次实际 MCP 工具确实缺失时才完全退出并重开一次。

## 验证证据

2026-09-28 的实现检查：

- `uv run --no-sync ruff check tools/dev/live_repair_acceptance.py tests/unit/test_live_repair_acceptance.py` 通过。
- `uv run --no-sync mypy tools/dev/live_repair_acceptance.py` 通过。
- `uv run --no-sync pytest tests/unit/test_live_repair_acceptance.py -q` 通过，15 tests。
- `python tools/docs/validate_docs.py` 通过，48 个历史来源未改，369 个 Markdown 文件、953 个本地链接通过。
- 从 `C:\Users\Tyuikl\.local\bin\tsunagou.cmd` 的 `installation-info` 取得安装 Python，执行 `install.py --help`、接入/bootstrap/start CLI help 核实及完整 prepare→check→export 只读采集。目标 project doctor 显示 daemon reachable 且包含该项目；安装记录为版本 `0.1.0`、来源 commit `1fb86e08b9cfaab312a9210a3eb15d0108314c36`、source dirty。2026-09-28T14:53Z 快照保留一 main、两 worker；history 分页完整；导出读取到 164 条该项目真实 span。验收 A1–A8 均仍 `not_run`，项目重大确认仍 `unverified`。
- 对比导出前后持续写入的 `docs/acceptance/evidence/live-repair-20260928T125752Z/spans.ndjson` 长度和最后修改时间相同。实际 CLI 采集只写入 `%TEMP%` 的隔离目录；没有运行 installer、安装依赖、重启 daemon 或读取/代用 Worker 私有身份。

## A5 独立回合补充 — 2026-09-28T17:44Z

main 利用当前已运行 daemon 向两个原始 Desktop Worker 发布两个独立的无文件接口核对任务，分别核对 UserDecision 的提案摘要和 resolve payload。两个不同 agent/session 均由 daemon 唤醒，完成各自 begin、cognition report、submit；main 对两个 Result 独立审查并 ACK。双方结论一致：propose 的 `proposal_digest` 可省略并由 daemon 计算，resolve 需要 `decision_id`、版本和 digest。没有真实理解分歧，因此没有创建 discrepancy/contract，也没有把这次一致性回合计为 A5 分歧验收通过。证据见 [A5 独立核对](../../../docs/acceptance/evidence/live-repair-20260928T150917Z/evidence/a5-independent-interface-check.json)。

## 2026-09-28T17:48Z 回归复核

公共 UserDecision schema/registry 修复后，全量 Python 回归通过（513 collected，510 passed，3 platform skips，0 failures/errors）；Ruff、mypy 74 source files、七工作区 bridge build、OpenAPI/protocol codegen、文档链接校验均通过。安装 CLI 的只读 `project timings` 重新采集并导出，最新快照 `snapshots/20260928T174746-eea3dff3`，trace 导出 275 spans；A1/A2/A3/A7/A8 仍以人工证据为 pass，A4/A5/A6 保持未完成，project confirmation 仍 unverified。当前现场 daemon 仍为 PID 102616/runtime `a233923d-af53-48c4-aaf2-286a004cc54e`，因此上述新版源码尚未加载到 live restart 场景。

## 后续现场验收

双 Worker 真实 begin/work/submit 与 main 审查、daemon 原 Desktop 空闲自动唤醒、同 owner 重启恢复及显式回收、认知/用户决定回合，以及 FX7 正常/损坏/截断样本的 HTTP/页面结果，仍需在各所属真实会话与隔离业务服务中留下证据并复核 `review.json`。trace 和 history 只证明记录到的边界/投影，不证明缺失的 Agent 回合。用户重大交付确认仍是独立门槛。

## 现场复核更新 — 2026-09-28T15:35:25.700Z

本节更新上述尚待状态，保留此前观测。主会话已复核原 Worker 对话调用、daemon 消息回信、真实代码提交与 main review、新 origin 的三种 BTID 文件上传及 HTTP 9/9。A1/A2/A3/A8 记 pass；A4/A5/A6 尚未完成；A7 因 parser submit 显式证据含私信导致用户 CLI 看不到提交时间，记 fail。用户未确认完成。具体边界、材料及后续动作见 [逐项复核](../../../docs/acceptance/evidence/live-repair-20260928T150917Z/operator-review.md)。

最新全量 Python 为 510 passed、3 skipped，0 failures/0 errors，158.557 秒；Ruff、mypy 73 文件、架构检查、七工作区 TypeScript check、Node 34 tests 通过。bridge 已重新 build。daemon stop 被本机命令策略拒绝，因此不能用源码测试通过代替加载新版后同库恢复的现场结果。FX6 与父任务仍 in_progress。

## 2026-09-28T18:02Z 回归复核

在不改变现场 daemon 的前提下，重新运行当前源码的相关回归：`tests/integration/test_daemon_lifecycle.py`、`tests/integration/test_desktop_wake.py`、`tests/integration/test_user_decisions.py`、`tests/protocol/test_user_decision_contract.py` 和 `tests/unit/test_live_repair_acceptance.py`，共 37 项通过，0 失败。该结果只证明当前源码回归，不替代旧 daemon 重启后的 A4/A6 现场验收。

## 2026-09-28T18:25Z daemon 重启结果与 MCP 加载断点

用户已重启 daemon，PID/runtime 变为 `103048` / `432243a5-9041-4979-89f9-83c20ddc9cf0`。CLI 确认 main 和两个 worker 身份均保留，运行中 Attempt `6c6b53f3-64b7-4f63-beb8-504276e8c8f4` 仍属原 owner `e5a866e0-3c1c-4ab5-8d11-5becd613cc48`。这是 A4“同库重启保留 owner”的现场证据；owner 重连恢复和 main 显式回收 fence 尚未验证。

新 daemon health digest 与当前 source bridge registry digest 相同；主会话 MCP 的 `context__project_read` / `inbox__claim` 返回 `schema_bundle_digest_mismatch`。当前运行的 bridge 子进程最晚创建于 00:56+08:00，而新 bridge build 文件时间为 01:51+08:00，故宿主持有较旧的内存中 bridge。完全退出并重启 Codex 后，先重试两个只读 MCP 工具；不得重新 enrollment。A6 等 MCP 正常后继续。详见 FX6 evidence `daemon-restart-bridge-digest-20260928T182511Z.json`。

## 2026-09-28T18:47Z bridge 重查

MCP 两个只读入口仍返回 `schema_bundle_digest_mismatch`，bridge 子进程时间戳未更新。尝试启动一份当前版本的隔离 MCP bridge 执行只读 context 查询，被本机策略在进程启动前拦截；无进程启动、无路由/credential 读取、无持久状态变更。保留失败并改由 Codex 宿主正常重启 bridge；A4 owner 恢复/回收及 A6 均继续待验。证据：`docs/acceptance/evidence/live-repair-20260928T150917Z/evidence/codex-bridge-recheck-20260928T184725Z.json`。


## 2026-09-28T19:51Z daemon 重启后的原 Owner 恢复与回收

用户提供并经只读快照复核的 daemon 为 PID `103048`、runtime `432243a5-9041-4979-89f9-83c20ddc9cf0`，启动于 `2026-09-28T18:11:09.514Z`。Codex 重开后，main `context__project_read` 与 Worker 原会话 MCP 均可用，host binding 为 ready、connection epoch 3。main 向原 owner 发送 A4 恢复消息后，Codex Desktop 原对话被 daemon 唤醒；Worker `task.begin(expected_task_revision=5)` 成功，前后保持 Task `357de2e9-8990-4c1e-b99f-365057d29732`、Attempt `6c6b53f3-64b7-4f63-beb8-504276e8c8f4`、revision 5 与原 owner，没有创建新 Attempt。该回合用时 110.486 秒。

随后 main 以准确的 `expected_attempt_id` 执行 `task.recover(disposition=reopen)`，事件 seq 242 于 `19:16:44.430Z` 提交；旧 Attempt 从 running 变成 orphaned，Task 变为 open/revision 6。main 两次通过持久消息要求原 owner 用旧 Attempt 做无副作用 `task.submit` 探针；Worker 读取并 ACK，但依据它保留的更早“退出 Tsunagou”要求拒绝继续。原对话此前退出旧 bridge，之后又按用户要求重新接入当前 FX live 项目；因此这次拒绝反映 Worker 未把后续 enrollment 视为更新的授权。未伪造 submit Result，也未借用 Worker 身份；旧 Attempt 的提交拒绝仍未验证，A4 保持 `not_run`。

截至 `19:51:51.667Z` 只读快照，Task 仍 open/revision 6、无 owner，两个 worker 会话均 ready 且无 owned task。CLI `agent --help` 不提供 retire；当前 main MCP 没有 `agent.retire` 工具，尽管协议 command catalog 注册了该命令。原 Worker 已停止此轮执行，但项目中的 Agent 状态仍为 ready。完整脱敏证据见 `docs/acceptance/evidence/live-repair-20260928T150917Z/evidence/a4-restart-recovery-20260928T1951Z.json` 与快照 `20260928T195149-d28cfb69`。

## 2026-09-28T23:43Z A6 真实用户决定待答路径

main 提出真实 `agent_lifecycle_policy` 决定 `f1396c86-ae11-4ce9-b499-281367fb5202`：同一 Codex 会话重新 enrollment 到当前项目后，是否覆盖仅针对旧项目/旧 bridge 的退出意图。CLI `decision list` 证实该项处于 `pending`、revision 1，proposal digest 为 `sha256:df307e0ef656c9559855a9ec7b323673659a29c5cb6140eee5d9dbdb0790d669`。这来自 A4 的真实生命周期冲突，不是为验收虚构的问题。

main 通过持久消息分派相关 Worker `cb2f1ff6-87de-4625-9afe-00b44ef5c182`。原 Codex 对话被 daemon 唤醒，回合从 `23:44:51Z` 至 `23:50:24Z`；Worker 于 `23:47:36.028Z` begin Task `097876bd-0473-40c2-9bed-d52fe5baa2f5`，向 main 发送进度消息并于 `23:49:59.025Z` 以 `user_decision_pending` block，随后结束回合。main 已展示并 ACK 该持久报告。决定待答期间，main 正常完成无关 Task `948d446d-bdb5-4905-a9f1-6b873abb8ca6`（begin `23:45:21.971Z`，submit `23:48:39.572Z`），无全局冻结、无自动恢复。

A6 仍为 `not_run`：尚缺用户以当前 revision/digest CLI resolve、原 main 收到 `user_decision.resolved` 的持久投递/宿主唤醒，以及 main 自行决定是否通知/恢复相关 Worker。脱敏现场材料见 `docs/acceptance/evidence/live-repair-20260928T150917Z/evidence/a6-user-decision-pending-20260928T235043Z.json`。

## 2026-09-29T00:02:49.213Z 待答期间只读复核

使用安装产物的 `live_repair_acceptance.py check` 生成快照 `snapshots/20260929T000247-5225f92c`。所有只读查询成功且 history 分页完整：daemon 仍为 PID `103048` / runtime `432243a5-9041-4979-89f9-83c20ddc9cf0`，同一项目中恰有一名 main 与两名不同的 ready Worker。相关 A6 Attempt `35427c2f-cfe8-498c-8f64-cd2b8a8a1097` 仍为 `blocked`，无关 Attempt `29cec294-4683-466d-8095-8af8bf342ca9` 仍为 `submitted`；没有自动同意、自动恢复或无关任务冻结。该采集没有读取私信、发送消息、领取任务或改变待答决定。

## 2026-09-29T00:30:07Z 当前源码与接入迁移复核

本节是当前源码的回归记录，不将未完成的现场回合改写为已完成。完整 Python 回归 `uv run --no-sync pytest -q` 无失败或错误，输出中保留三个已知平台跳过项；`corepack pnpm run check` 通过全部七个工作区 TypeScript 检查；`corepack pnpm exec vitest run` 通过 6 个文件、34 项测试；`uv run --extra dev python tools/codegen/validate_protocol.py` 验证 99 个命令策略与 115 个 schema；架构检查和文档校验均通过。直接以未带开发额外依赖的 Python 执行协议校验会缺少 `jsonschema`，这是错误的操作环境；以 `uv run --extra dev` 重试通过，不记为产品故障。

FX4 接入修复已加入当前源码：`agent connect` 在相同项目中发现旧式、固定 session 的 Codex MCP 注册时会迁移到共享路由 bridge，并只移除该项目且使用同一 bridge 可执行文件的旧注册，不触及其他项目。共享 MCP 已存在时也会执行这项清理。对应的 onboarding 单元及集成回归共 9 项通过，Ruff 和 mypy 通过，相关用户文档已说明无需 GUI 刷新按钮、旧已启动 bridge 不会热切换，以及首次 MCP 查询的恢复路径。此修复尚未替代 A4 的旧 Attempt submit 拒绝、A5 的真实分歧/契约或 A6 的用户决定闭环；三项继续为 `not_run`，项目重大完成确认继续为 `unverified`。

同一时刻以安装 CLI 做只读现场采集，生成 `snapshots/20260929T003151-9a149986`。daemon PID `103048` / runtime `432243a5-9041-4979-89f9-83c20ddc9cf0` 可达且登记当前 project；恰有一名 main、两名 Worker、三个 ready Agent 且身份独立，history 分页完整。A6 相关 Attempt `35427c2f-cfe8-498c-8f64-cd2b8a8a1097` 继续为 `blocked`，没有自动恢复；无关已提交任务仍独立存在。采集仅调用公开安装、doctor、agent、diagnostics、timings 与 history 查询，不读取私信、发送消息或改变 pending UserDecision。

## 2026-09-29T04:45:48.644Z A4–A6 现场收口

在上述历史状态之后，原 Desktop Worker 实际调用了回收后的旧 Attempt `task.submit`，daemon 于 `02:38:32.406Z` 以 `capability_denied` 拒绝，未生成 Result；A4 的外部行为通过。拒绝发生于权限层，未覆盖 Attempt 专属错误码。此前同库重启、原 owner 恢复同一 Attempt 和显式回收证据仍有效。新证据为 `docs/acceptance/evidence/live-repair-20260928T150917Z/evidence/a4-stale-submit-20260929.json`。

A5 出现真实 hard discrepancy，main 用无执行者/活跃执行者两个任务验证 `task.cancel` 行为，并与第二名 Worker 接受最终契约后解决分歧。首位分歧报告 Worker 没有接受最终契约，此身份差异如实留档。A6 用户通过 CLI 批准原 pending 决定；主通知被 ACK，main 自行恢复被阻塞任务，原 Desktop Worker 在新回合以新 Attempt 提交，main 审查完成。额外主会话 wake 因消息已 ACK 而跳过，不能作为新回合证据。对应证据为同一 run 的 `a5-discrepancy-contract-20260929.json`、`a6-decision-resume-20260929.json`。

人工 `review.json` 的 A1–A8 现均为 pass，具体限定见 `operator-review.md`。这些通过项不代替用户对整项目的重大完成确认；FX6 和父任务状态继续 in_progress，待最终交付边界复核。
