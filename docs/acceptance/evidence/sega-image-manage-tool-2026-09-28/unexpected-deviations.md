# 本次真实项目测试的异常与设计偏离

记录时间：2026-09-28（Asia/Shanghai）  
目标项目：`D:\ALL.Net\SegaImageManageTool`  
验收记录：[`../../sega-image-manage-tool-2026-09-28.json`](../../sega-image-manage-tool-2026-09-28.json)

本文件只记录本次实际运行中观察到的事实、影响、处置和后续动作。`ticket_issued`、创建了 Codex 会话或工具出现在工具列表中，都不被当作 Agent 已经 ready，也不被当作 A2A 已经成功。尚未验证的项目保留为 pending。

## 已解决或已缓解的异常

### 1. 安装器复用了错误的 Tsunagou checkout

- 时间：2026-09-28 部署阶段。
- 观察：安装器在目标项目执行时复用了 `C:\Users\Tyuikl\Tsunagou` 作为 installer destination/bootstrap source，而不是当前验收要求的 `D:\Tsunagou`。目标项目初次生成的上下文引用了旧提交 `e0ada9942...`。
- 影响：如果不纠正，业务项目中的项目上下文、技能说明和实际运行源码可能来自不同 checkout，造成协议语义漂移；这违反“daemon 管理多个项目但源码保持在指定中心位置”的验收前提。
- 处置：使用显式 source root 重新 bootstrap：

  ```powershell
  uv run python -m tsunagou project bootstrap `
    --coordination-root 'D:\ALL.Net\SegaImageManageTool' `
    --source-root 'D:\Tsunagou' `
    --source-ref working-tree `
    --host codex --refresh
  ```

- 结果：目标 `.tsunagou/agent-context.md` 和 `project-integration.json` 已改为引用 `D:\Tsunagou`、当前工作树提交 `616bd83e272f6be3c9aec0b6176c6d71a13a4aff`。目标项目未复制 Tsunagou 源码。
- 后续：安装器应在复用已有 checkout 时明确报告 source root，并允许验收命令强制指定 source root；在修复前，部署证据必须保存 bootstrap 前后的 source root 和 source digest。

### 2. PTY 启动的 daemon 没有保持存活

- 时间：2026-09-28 daemon 首次启动。
- 观察：通过 PTY 启动返回 `started`，日志出现 uvicorn startup/health，但进程随后退出；紧接着 `daemon status` 显示 stopped，health 连接被拒绝。
- 影响：CLI 返回成功并不等于 daemon 仍可用；如果把该返回直接作为验收证据，会产生假阳性。
- 处置：改用非 PTY 的持久进程启动，并重新执行 status/doctor。当前稳定实例为 PID `76936`，URL `http://127.0.0.1:56876`，`doctor` 返回 `Tsunagou doctor: ok`。
- 结果：本次部署已恢复，但尚未证明所有宿主终端/PTY 启动方式都具备相同生命周期语义。
- 后续：将 daemon 的“启动后存活探测”纳入安装器和验收脚本；CLI 应在进程刚退出时返回失败，而不是只返回启动瞬间的成功。

### 3. daemon 命令出现了 coordination root 解析偏差

- 时间：2026-09-28 daemon status/doctor 复核阶段。
- 观察：一次没有显式 `--coordination-root` 的调用解析到了 `D:\Tsunagou\.tsunagou\local`，结果为 `daemon_unreachable`，而目标 daemon 实际运行在 `D:\ALL.Net\SegaImageManageTool`。
- 影响：多项目场景下，用户可能误查另一个项目的本地状态，导致“daemon 已坏”或把错误项目的状态当作验收证据。
- 处置：所有本次验收命令均显式传入 `--coordination-root D:\ALL.Net\SegaImageManageTool`；显式参数下 status/doctor 正常。
- 结果：当前验收可继续，但默认 root 语义仍需进一步确认。
- 后续：安装后生成的操作命令应始终包含项目 root，或提供明确且可验证的项目选择；文档不能假定当前工作目录自动指向目标项目。

### 4. Python 虚拟环境路径出现警告

- 时间：2026-09-28 安装阶段。
- 观察：uv 输出 `VIRTUAL_ENV=D:\Tsunagou\.venv does not match project environment path .venv and will be ignored`。
- 影响：当前安装和构建仍成功，但用户可能误以为命令使用了已激活的环境；不同环境会造成依赖或版本证据不一致。
- 处置：保留 uv 选择的项目环境，不强行迁移用户环境；记录警告。
- 后续：安装器应在 JSON 结果中记录实际 Python/uv 环境路径，并给出一条无歧义的复现命令。

### 5. Windows 保留端口导致 credential private lock 失败

- 时间：2026-09-28 Web UI worker 首次 connect 的两次尝试。
- 观察：Web UI profile 的 ticket 哈希选择了端口 `56618`；该端口落在 Windows excluded range `56570-56669`，绑定时得到 `WinError 10013`，桥接器报告 `credential_private_lock_busy:retry_pending_request`。
- 影响：同一 daemon、同一 profile 的接入在环境层面失败；重试前不能把 ticket 认为是可用 enrollment。失败还留下了 pending ticket/host identity 状态。
- 处置：修改 `src/tsunagou/platform/private_file_lock.py` 和 `packages/bridge-server/src/private-file-lock.ts`：遇到 Windows `EACCES/10013` 时按确定性序列跳过不可用端口，继续寻找可绑定端口；真正的 `EADDRINUSE/10048` 仍按等待/忙处理。增加 Python 回归测试。
- 结果：`uv run pytest -q tests/unit/test_private_file_lock.py`（2 passed）、ruff、mypy、bridge check/build 均通过；使用同一 `codex-webui` profile 重试后返回 `ticket_issued` 和 `registered:tsunagou-codex-webui-fa0987f0`，没有证据表明创建了第二个业务 Agent。
- 后续：connect 失败时应清晰报告“可重试/待清理状态”，并在验收历史中标记失败 attempt，避免用户误以为已经完成接入。

## 尚未解决或尚未证明的偏离

### 6. ticket issued 与当前 Codex 会话的 bridge 不一致

- 时间：2026-09-28 三 profile connect 后、创建新 Codex 会话前。
- 观察：当前主对话中已加载的动态 bridge 调用分别返回 `credential_transport_failed:retry_pending_request` 和 `not_enrolled:no_ticket_or_session_file`，尽管 daemon 已为 `codex-main`、`codex-webui`、`codex-http` 发行 ticket。
- 影响：当前对话的旧 MCP/bridge 实例不能证明新 ticket 已经被宿主加载；只依靠工具列表、ticket JSON 或 host registration 会把未 ready 状态误报为 ready。
- 处置：创建三个独立 Codex conversation，分别承担 main、Web UI worker、HTTP worker，并在各自会话中重新读取项目上下文。对应公共 thread ID：
  - main：`01a0e5fa-cb14-7162-b5d0-ce5216190c7d`
  - Web UI：`01a0e5fa-d186-7430-8fb1-0707ed8b3e49`
  - HTTP：`01a0e5fa-daa6-7891-8bb8-9cd58d8b23fb`
- 当前状态：待这些会话返回实际 `context__project_read` 结果；在此之前，三 Agent enrollment、A2A、任务执行和 WebUI/HTTP 交付均保持 pending。
- 后续：bridge 接入结果应区分“ticket 已发行、host 已登记、bridge 已加载、project context 可读、Agent 已 ready”五个阶段，并提供无需用户粘贴凭据的恢复路径。

### 7. `agent list` 命令不存在

- 时间：2026-09-28 接入复核阶段。
- 观察：`uv run python -m tsunagou agent list --help` 返回 `No such command 'list'`。
- 影响：不能使用预期的 `agent list` 作为三身份验收入口；旧说明或 Agent 的自行推断可能导致命令失败后继续编造身份状态。
- 处置：本次使用项目 history、profile-specific bridge/session 文件和各自的 project context 作为证据来源；不把 `agent list` 写入通过标准。
- 后续：要么补充只读身份查询命令，要么统一更新命令目录、fixtures、验收文档和 Agent skill，明确现有替代查询方式。

### 8. 三个 Codex thread 已创建，但尚无 ready/A2A/任务执行证据

- 时间：2026-09-28 03:07 UTC 左右创建。
- 观察：Codex app 已创建 main、Web UI worker、HTTP worker 三个独立 thread；创建 thread 本身只证明调度动作，不证明其已加载 bridge、领取任务或完成一轮 A2A。
- 影响：如果把 thread 创建或“等待中”消息写成协作完成，会违反“不能把 MCP-only 或 ticket-only 当作 A2A 证明”的硬失败条件。
- 当前状态：等待各 thread 的真实上下文、任务领取、A2A JSON-RPC、证据回写和持久化查询结果。
- 后续：至少需要保存每个 thread 的 `agent_id/session_id/conversation_id` 公共标识或脱敏 digest、`context__project_read`、一条可关联的 A2A send/receive/wake、任务 attempt 和最终证据。

### 9. 目标项目基线已有 67 个 nullable warnings

- 时间：2026-09-28 部署前 baseline。
- 观察：`dotnet build ...SegaImageManageTool.sln` 成功，但已有 67 个 nullable warnings。
- 影响：不能把本次验收中的零 warning 作为现实标准；新增 WebUI/HTTP 改动必须与 baseline 对比，不能掩盖新增编译问题。
- 处置：保存 baseline 成功结果和 warning 数，验收要求报告新增 warning 数；不在本次 Tsunagou 协作验收中顺手清理既有业务警告。

### 10. OpenTelemetry/blame 仍没有实际证据

- 时间：截至本记录生成时。
- 观察：验收单要求 local opt-in OTel、HTTP/A2A/CLI/UoW/task/resource/cognition/workspace/checkpoint/wake span 及持久化 trace refs，但当前真实项目测试尚未产出这些 span/exporter/blame 证据。
- 影响：不能用已有 actor/evidence/history 字段宣称已经完成 OTel 因果追责；这是设计目标与当前可证明能力之间的明确缺口。
- 处置：将 `otel_blame` gate 保持 pending，并把所需的 trace、causation、subject、redacted blame view 作为独立验收证据。
- 后续：若本次工期不足，必须在最终报告中明确标记未完成，而不是降低验收标准或用日志存在替代 trace evidence。

### 11. 目标项目目录不能直接运行 Tsunagou CLI

- 时间：2026-09-28 主 Agent 读取历史阶段。
- 观察：主 Agent 在 `D:\ALL.Net\SegaImageManageTool` 执行 `uv run python -m tsunagou project history ...`，Python 返回 `No module named tsunagou`。
- 影响：项目级安装入口包含文档和 bridge，但用户从业务项目目录直接复制验收查询命令不能工作；这与“项目可独立运行的 CLI 查询”预期不一致。
- 处置：主 Agent 未修改项目或猜测环境，改在 `D:\Tsunagou` 执行；该路径又进入下一条控制凭据偏差。
- 后续：提供不依赖当前工作目录的官方 CLI 入口（例如可定位 source root 的 wrapper/安装环境），并让验收命令显式记录 source root。

### 12. 源码目录的 CLI 查询缺少 control credential

- 时间：2026-09-28 主 Agent 读取历史阶段。
- 观察：在 `D:\Tsunagou` 重试同一 `project history` 命令时，返回 `{"status":"control_credential_missing"}`；主 Agent 没有索取或猜测凭据。
- 影响：普通 CLI 与 bridge 的权限边界没有被用户友好地解释：bridge 可以完成项目上下文/任务编排，而独立 CLI 不能直接查询同一项目；这阻塞了验收要求的人工持久化查询。
- 处置：将 CLI 查询保持为 pending，使用 bridge 事件作为当前运行证据；不把该错误当成历史为空。
- 后续：提供安全的本机控制凭据发现/初始化流程或只读诊断命令，使用户无需复制秘密即可执行历史、diagnostics、audit 查询。

### 13. 原子计划默认要求项目级自动唤醒 opt-in

- 时间：2026-09-28 主 Agent 首次调用 `coordination__plan`。
- 观察：即使计划明确声明 `auto_wake=true`，daemon 首次返回 `auto_wake_project_opt_in_required`；当前 daemon 初始状态报告 `host_wake=disabled`。
- 影响：任务发布本身被隐藏的项目政策门槛阻塞；用户若只看到 assignment 创建命令，无法知道为何没有子 Agent 被唤醒。
- 处置：主 Agent 通过 `project__configure` 设置 `auto_wake_multi_agent=true`，注明 durable inbox pull 仍为 fallback，然后重试同一计划成功。
- 后续：安装/初始化时明确询问或显示 wake policy；`coordination__plan` 的错误应给出可执行的用户级配置命令，不应让 Agent自行猜测策略变化。

### 14. A2A message accepted，但尚无 worker delivery/presentation/turn

- 时间：2026-09-28 03:10 UTC 左右。
- 观察：任务计划成功后，main bridge 的两次 `message__send` 均返回 `completed`；assignment 状态为 `waking`。截至当前，Web UI 与 HTTP worker thread 均保持 `idle`，最后一轮仍是 `conversation_identity_required_for_session_file`，没有新的 worker turn、delivery、presentation 或 wake 回调证据。
- 影响：`message/send` 的 accepted/completed 不能证明消息已到达宿主或唤醒了 Agent；当前 A2A 只能证明 daemon 接收了发送请求，不能证明端到端协作。
- 处置：验收 gate 保持 `message_accepted_delivery_and_wake_pending`；不使用 Codex app 的普通 thread 消息替代 A2A 证据。
- 后续：检查 bridge profile 到 Codex conversation 的绑定、host registration 和 wake adapter；若宿主 wake 不可用，必须让 worker 能通过新鲜 bridge 的 durable inbox pull 接着执行，并持久化 `accepted/delivered/presented/pull` 阶段。

### 15. Main 能读取 worker bridge context，但 worker 自身 bridge 仍旧

- 时间：2026-09-28 主 Agent发布计划阶段。
- 观察：main thread 的工具调用记录显示它能调用 `tsunagou-codex-webui-fa0987f0` 与 `tsunagou-codex-http-fa0987f0` 的 `context__project_read` 并取得不同 worker 身份；相应 worker thread 自己调用的却是旧 `tsunagou-sega-worker-live-fa0987f0`/wake bridge，并返回 `conversation_identity_required_for_session_file` 或 `credential_transport_failed`。
- 影响：同一 Codex host 中不同 conversation 的 MCP 工具缓存/路由不一致，可能导致主 Agent看到 worker 已 enrollment，而 worker本身无法行动；这直接违背“每个 conversation/subagent 都是独立 worker”的可操作接入预期。
- 处置：将 main 的跨 bridge 读取仅作为身份与任务绑定的观察，不将其当作 worker ready；worker gate 继续 pending。
- 后续：bridge 安装/刷新必须按 conversation 隔离工具命名空间和会话身份；需要提供无需重启整个 Codex 的可验证 reload，或明确新 thread 的初始化方式。

### 16. 主会话的 inbox fetch 出现失败

- 时间：2026-09-28 03:14 UTC 左右。
- 观察：主会话在发布任务、提出协作契约后调用 `inbox__fetch` 获取消息 ID `ef93b629-e1b0-4231-9d30-027f2ad14a29` 和 `8fcb7a8a-5d99-4811-a1d6-746d03840132`，工具调用状态为 `failed`；返回体未在 Codex thread 摘要中暴露，故不推断具体原因。
- 影响：即使 daemon 已持久化消息，主 Agent 也可能无法按消息 ID读取完整 payload；这会阻塞响应义务和 A2A delivery/presentation 追踪。
- 处置：只记录调用状态和公共 message ID，不重试生成新消息、不猜测内容；A2A gate 仍保持 pending。
- 后续：为 inbox claim/fetch 返回结构化错误、消息是否已 ACK/过期/不属于当前 session 的原因和可重试建议；验收需要保存完整安全错误摘要。

### 17. 自动唤醒超时并重试，worker 没有进入 pull

- 时间：2026-09-28 03:15 UTC 左右。
- 观察：主会话记录两次首次 wake 产生 `wake.expired` 和 `wake.retry`；新的 `wake_attempt` 仍为 `waking`。两个 worker context 没有 claim 任务，Codex worker thread 没有新 turn。
- 影响：项目级 auto-wake opt-in 已通过，但实际 host wake 仍未把任务送入 worker 对话；`message__send` 的 accepted 不能升级为 delivered/presented/turn。
- 处置：保留 wake 事件链，等待 durable inbox pull；不手动替 worker ACK、claim 或执行任务。
- 后续：明确 wake adapter 的超时、重试次数、最终降级到 pull 的时机；在 worker bridge 可刷新之前，验收不得进入代码实现阶段。

### 18. Main 读取 worker inbox 被拒绝（边界行为正确但阻塞观测）

- 时间：2026-09-28 03:15 UTC 左右。
- 观察：主会话尝试读取对方 inbox，得到 `inbox_access_denied`；没有冒充 worker读取 `presented` 状态。
- 影响：主 Agent 无法直接替 worker确认消息是否已 presented，只能依赖 worker 自己的 bridge 或 daemon 的安全 delivery 摘要；当前缺少后者的可见查询路径。
- 处置：将该拒绝记录为“权限边界正确”，不把它计为越权缺陷；同时保持 delivery/presentation gate pending。
- 后续：提供脱敏的主方 delivery/attempt 状态视图，允许 main 追踪结果但不能读取 worker 私有 payload 或代 ACK。

### 19. Wake 重试耗尽后 assignment 被阻塞

- 时间：2026-09-28 03:16 UTC 左右。
- 观察：两轮 retry 均未唤醒 worker；两个 assignment 最终进入 `blocked`，事件原因是 `wake.failed: wake deadline expired after retry limit`。
- 影响：即使项目已 opt-in auto-wake，首轮任务也不能自动进入 worker；整个 Web UI/HTTP 实现尚未开始，无法进入代码、冲突和端到端验收。
- 处置：保留 `wake.expired`、`wake.retry`、`wake.failed`、assignment 状态变化和 A2A durable message 记录；不替 worker claim/preflight/start，不创建伪造 workspace 证据。
- 可恢复路径：需要刷新或重新创建与 `codex-webui`/`codex-http` 对应的独立 bridge，使 worker 能够执行 durable inbox pull；随后由 main 或用户按规则重新发布/恢复 assignment。恢复前不得把 blocked 当作完成或失败交付。
- 后续：实现明确的 host wake 不可用降级：assignment 在 wake 失败后应转为 `open`/可领取，而不是永久 blocked；worker 任意稍后加入都应能领取任务，且 lease 只约束执行 Attempt。

### 20. 相同 command_id 的 message/send 幂等性不一致

- 时间：2026-09-28 03:17 UTC 左右。
- 观察：主会话用原 Web UI assignment command 重试 `message__send`，工具返回 `completed`；用原 HTTP assignment command 重试时返回 `failed`。当前 thread 摘要没有暴露 HTTP 失败的安全错误体，不能推断是重复冲突、状态阻塞还是传输故障。
- 影响：验收要求重复 `messageId`/request ID 得到同一安全结果且不增加业务消息；当前两个接收者的表现不同，无法宣称消息幂等性已经成立。
- 处置：不生成第三个 command、不手动修改消息状态；保存两次调用状态和相同 command ID，幂等 gate 保持 pending。
- 后续：统一重复命令的结果协议（同一 message/result digest 或明确的 already-accepted），并返回可审计的失败原因。

### 21. Wake fallback 消息 accepted，但 durable pull 仍未发生

- 时间：2026-09-28 03:17 UTC 左右。
- 观察：main 发送 `main-webui-pull-fallback-20260928-01` 和 `main-http-pull-fallback-20260928-01`，两次工具调用均 completed，payload 明确要求 worker pull inbox 后再 claim/preflight/start；两个 worker thread 仍没有新 turn。
- 影响：系统已经给出设计上正确的 pull fallback，但当前 worker bridge 未加载/未执行 pull，因此任务仍被 blocked；用户需要知道“fallback 已记录”不等于“worker 已恢复”。
- 处置：保留 fallback message 作为可恢复证据，不通过 Codex app 普通消息代替 worker pull。
- 后续：新鲜 worker bridge 接入后应首先读取这两条 fallback 消息，验证消息去重、claim 和 assignment 从 blocked/open 的恢复语义。

### 22. 用户侧看不到 worker 新对话或消息

- 时间：2026-09-28 本次验收进行中，用户现场观察。
- 观察：用户在 Codex 界面确认 Web UI 和 HTTP 两个 worker 没有任何新对话或消息；线程状态仍为 idle。
- 影响：系统内部的 `message__send completed`、`waking` 和 fallback accepted 没有转化为用户可见的 Agent turn；用户无法知道 worker 是否被唤醒，也无法从界面继续工作。
- 处置：将用户观察与 daemon 的 `wake.expired`/`wake.failed` 和 worker 的 `conversation_identity_required_for_session_file` 关联保存；不把“没有新消息”解释为 worker 已完成或无任务。
- 后续：恢复流程必须在 Codex 界面产生可见的新 turn，或明确提供用户可以手动触发的 bridge reload/pull 命令，并在恢复前显示 assignment、身份和待处理消息摘要。

### 23. 首个实现任务的前置链过长，明显削弱效率（用户要求事后复盘）

- 时间：2026-09-28 本轮任务执行阶段，用户现场判断。
- 观察：从用户发起任务到代码开始之间依次遇到 source checkout 校正、daemon 生命周期确认、bridge reload、auto-wake opt-in、wake retry、worker.ready、pull fallback、任务 claim、主 Agent workspace select、resource intent/acquire、workspace prepare、preflight 和 start 等多个门禁；其中多项是相互独立或可由主 Agent默认决定的准备动作。
- 影响：首个 WebUI/HTTP 交付尚未开始时，墙上时间已经显著增加；用户需要理解并等待大量机械状态，违背“代码部分少做复杂决策、主 Agent自动处理普通细节、用户只在重大决策时介入”的初始效率原则。
- 当前处置：不在本轮验收中临时改动协议或删除证据；继续按当前实现完成任务，所有门禁和耗时保持可追溯。
- 复盘方向：将默认安全路径压缩为主 Agent可自动完成的最小编排，把 workspace/resource/cognition 等细节合并为一次可审计准备事务；只有风险、冲突或用户权限变化时才暴露额外决策。此项不代表当前代码已经修改。

### 24. 计划中的路径 glob 与资源协议的结构化 scope 不兼容

- 时间：2026-09-28 03:52–04:04 UTC。
- 观察：pull-first 计划把 `paths`/`forbidden_paths` 字符串写进 `execution_scope`；两个 worker 的 `resource__intent` 均返回 `invalid_task_execution_scope`。worker 必须分别提交 typed `task__scope_request`，再由 main 批准 `kind/root_id/segments/mode` 结构。
- 影响：任务已经由 main 划分清楚，却不能直接进入资源和 workspace 阶段；同一边界被人类 glob、消息 payload 和 typed scope 表达了三次。
- 处置：保留原 plan 与失败事件，通过正式 scope request/resolve 转换为结构化范围，不重建任务。
- 后续：`coordination__plan` 应校验并规范化 scope，或只公开一种 scope 表达；任务创建成功即应保证后续 `resource__intent` 可消费。

### 25. Bootstrap 未注册 workspace root，`project` scope 无法准备

- 时间：2026-09-28 03:56–04:04 UTC。
- 观察：目标 `.tsunagou/project.json` 的 `roots` 与 `repositories` 均为空。HTTP worker 已成功 intent/acquire，但 `workspace__prepare` 返回 `workspace_root_unbound`；用户控制的 `root.register` 尝试又因当前 daemon 不接受本地 control token 而返回 `authentication_failed`。
- 影响：项目已 bootstrap、daemon doctor 正常、Agent 也已领取任务，仍无法建立可扫描 workspace；这是安装阶段漏掉的机械前置条件。
- 处置：本轮使用实现已有的 `coordination` 根回退，并将两个任务重新批准为该 root 下的非重叠结构化路径。
- 后续：bootstrap 应原子注册并绑定协调项目根，doctor 应在 worker 领取任务前报告 root readiness；不得等到 `workspace__prepare` 才发现。

### 26. HTTP 的宽 `tests` Lease 与 WebUI 的 `tests/WebUI` 冲突

- 时间：2026-09-28 03:58 UTC。
- 观察：HTTP scope 申请 `tests`，WebUI scope 申请 `tests/WebUI`；WebUI acquire 返回 `resource_conflict:path:project:tests`。
- 影响：原计划声称两个任务范围不重叠，但机器资源语义实际重叠，阻止并行工作。
- 处置：释放旧 Lease，把 HTTP 测试范围收窄为 `tests/Http`，WebUI 保留 `tests/WebUI`。
- 后续：计划创建时应对所有 assignment 做规范化路径重叠检查，并在发布前返回冲突，而不是等 worker acquire。

### 27. 120 秒 Lease 在多轮准备和实现中反复过期

- 时间：WebUI 首次 Lease 于 `2026-09-28T04:07:42.611Z` 过期；HTTP fresh attempt Lease 于 `2026-09-28T04:16:40.940Z` 过期。
- 观察：WebUI start 后先提交 cognition/contract、读说明并实现，未在 120 秒内调用 `task__progress`，execution grant 被撤销；worker 后续才发现 `capability_denied`。HTTP 在 acquire 后等待 attempt-bound workspace decision，decision 完成前 Lease 已过期。
- 影响：WebUI 在机械授权失效后仍通过宿主 Full Access 写入文件；HTTP 多次 claim/recover/reselect 才能进入实现。系统留下了围栏事件，却没有及时让宿主对话停止或提醒续租。
- 处置：WebUI 立即停止并保留未提交文件，main reopen 后由 fresh attempt 重新核对；HTTP 改为先由 main select，再 acquire，并在 start 后立即 `task__progress`。所有过期 attempt 保留为历史证据。
- 后续：准备阶段不应消耗执行 Lease；running worker 应获得自动续租提醒或 bridge heartbeat，过期应主动通知/唤醒当前 conversation。默认 TTL 也应覆盖常见 Agent 回合时长。

### 28. Workspace decision 与 attempt 强绑定，恢复需 main 重做相同决定

- 时间：2026-09-28 04:14–04:22 UTC。
- 观察：HTTP task recover 后 fresh claim 得到新 attempt；旧 `workspace__select` decision 返回 `workspace_decision_attempt_mismatch`。main 为第二个 attempt 重新 select 时 Lease 又过期，第三个 attempt 还需要第三次同样的 shared decision。
- 影响：并未改变 task scope、风险或隔离选择，却重复消耗 main Agent turn、A2A 消息和墙上时间。
- 处置：严格保留 attempt fence，每个 fresh attempt 由 main 重建 decision；worker 在 decision ready 前不再 acquire。
- 后续：允许 main 为 durable task 记录可继承的 isolation policy，fresh attempt 只校验 scope/revision 后派生 decision；无需重复 LLM 决策。

### 29. Contract participant slot 编码错误，proxy 可把 withdrawn 提案恢复为 accepted

- 时间：2026-09-28 04:42–04:43 UTC。
- 观察：两个 task-linked contract 把裸 Agent ID 字符串作为 participant。handler 将它转换为只有 `slot`、没有 `agent_id` 的 participant，普通 `contract__accept` 因此返回 `participant_slot_denied` 并阻塞 strict preflight。HTTP worker 随后 withdraw 旧提案并用 `{slot, agent_id}` 提出正确契约；main 又通过 `contract__accept_proxy` 接受旧提案的两个必选槽，旧提案状态从 `withdrawn` 变成 `accepted`。
- 影响：调用方很容易产生无法普通接受的契约；proxy 路径允许非法状态跃迁，削弱审计语义。
- 处置：本轮用 main 的显式 proxy 接受完成验收，并保存正确 participant 形式的成功证据 `8b4d7185...`。
- 后续：`contract.propose` 对 required participant 强制要求 `{slot, agent_id}`；`accept_proxy` 必须与普通 accept 一样只接受 `proposed` 状态。

### 30. Lease 从 acquire 开始计时，但 worker 在 start 前不能续租

- 时间：2026-09-28 04:47–05:17 UTC。
- 观察：`task__progress` 在 running 且 Lease 有效时确实会自动续租；但 workspace prepare、preflight 和 Agent 推理已经消耗 TTL，worker 在 start 前没有 `task.execute`，`resource__renew` 会被拒绝。WebUI attempt `cc57128f...` 于 05:03:03.915 UTC acquire，05:04:49.048 UTC 才 start，05:05:04.020 UTC 即过期；renew/progress 到达时已经被 fence。
- 影响：即使实现和测试已完成，单纯提交证据也可能因正常 Agent 回合耗时反复 orphan；恢复链远长于实际工作。
- 处置：最终 WebUI attempt 不再执行读取、命令或复验，连续完成 intent/acquire/prepare/preflight/start/progress/result/submit，running 窗口 24.785 秒；HTTP 最终 running 窗口 92.616 秒。
- 后续：TTL 从 `task.start` 起算，或提供只延长准备 Lease 的窄能力；宿主应显示剩余 TTL，准备阶段不应占用执行 Lease。

### 31. 缺少可再分发的有效 BTID 成功样本

- 时间：2026-09-28 05:24 UTC。
- 观察：独立复验的 `dotnet build`、5 个 WebUI Node 测试和 HTTP acceptance 均 exit 0；真实浏览器连接实际后端并上传仓库 fixture 后，收到带 request ID 的 `file_too_small`。仓库内只有 33 B 的 `tests/WebUI/sample.app`，没有可用于成功解析的有效 BTID fixture。
- 影响：已证明服务在线、浏览器到后端的 multipart 链路和结构化错误；尚未用可复现仓库样本证明 BTID 成功解析页面。
- 处置：不伪造成功数据；实际后端继续运行在 `http://127.0.0.1:5137/`，浏览器保留错误路径证据。
- 后续：增加可合法再分发的有效 BTID fixture，或由用户选择真实样本再跑一次成功路径。

后续更新：`2026-09-28T05:58:58.994Z` 前已通过 [生成器](make-synthetic-btid.ps1) 构造无游戏数据的 32 KiB 合成有效 BTID，并在实际 HTTP 服务和真实浏览器中完成成功解析。`TEST / 1.2.3 / headerCrcValid=true`、请求 ID 和截图见 [成功记录](btid-success-record.json)。本项的样本缺口已解决，商业真实镜像的覆盖范围另计。

### 32. Codex-only 目标仓库出现无关的 `opencode.json`

- 时间：文件时间为 2026-09-28 04:53:15 UTC，最终清点于 05:24 UTC。
- 观察：目标仓库根出现未跟踪的 `opencode.json`，指向 `opencode-current` bridge；此前状态快照没有该文件，且它不在 WebUI 或 HTTP worker scope 中。
- 影响：业务交付混入未选择宿主的配置，也无法从当前 task scope 解释其作者与原因。
- 处置：删除根目录中的非秘密 OpenCode 配置；daemon 持久状态保留，便于事后追踪生成来源。
- 后续：host registration 只写用户明确选择的宿主配置，并为生成的项目根文件记录 actor/task/event。

## 后续证据修正（2026-09-28 05:58 UTC）

- `mcp_transport_not_a2a_protocol_proof`：此前 bridge 的 `message.send` 实际通过 `/api/v1/commands`，不能独自证明 A2A HTTP。新增 [A2A HTTP 实测](a2a-http-record.json)：六次发送只新增两条消息，tasks/get 成功，三个异 Worker 操作被拒绝。两个 Worker 自己读取和 ACK，回复也由 main 自己 ACK；见 [回执](a2a-receipt-record.json)。harness 发起与 Codex follow-up 均明确标注，原生唤醒仍未通过。
- CLI 查询修正：指定目标 `TSUNAGOU_PROJECT_ROOT`、`TSUNAGOU_STATE_DIR` 后，history、两个 task history、diagnostics、audit 和 checkpoint verify 全部 exit 0。查询前后 seq 375 不变；daemon 重启后七项复验也成功、seq 386 不变。原来的错误观察保留，但“CLI 仍不可查询”的旧结论已被后续证据替代。daemon status 的 root 默认值差异仍存在。
- `otel_instrumentation_absent`：源码和依赖中没有 Tsunagou OTel instrumentation/exporter，公开 audit 没有 trace/span 关联；已有 actor、command、时间戳不能代替这一项。按用户要求留待交付后处理。
- `diagnostic_empty_despite_transport_and_denials`：diagnostics 为空，A2A 拒绝操作没有产生业务事件；不能声称可通过公共查询完整追责所有失败。安全 HTTP 响应已另存，后续只补必要诊断，避免把拒绝写成成功业务事实。
- `legacy_btid_integrity_results_discarded`：源码检查发现既有 `Btid.Create` 忽略 sector CRC/HMAC 的返回值；截断扇区读取也需补终止条件。本轮未修改既有库，合成样本校验值正确。已知有效样本成功不等于所有损坏样本验证通过。

用户提出的效率问题继续保持 `deferred_postmortem`。新增 [宿主回合计时](host-turn-timing.json) 与原 running 窗口分开呈现；Lease 有效时间不能被当作实际全部工作时间。业务交付与平台验收分列于 [交付报告](delivery-report.md)。

## 原生唤醒补测（2026-09-28 06:17 UTC）

- `native_wake_disabled_and_unbound_in_initial_run`：原 daemon 未启用 host wake，也没有宿主绑定。初始 coordination retry 失败不等于实际 provider 调用失败，已修正结论。
- `codex_listener_private_directory_required`：公开 listener 首次因目录不私有退出；新建专用当前用户目录后恢复，未修改既有目录权限。
- `desktop_thread_active_writer_blocks_external_resume`：绑定和只读 thread/read 成功，实际 A2A wake 的 thread/resume 被当前 Desktop writer 拒绝；没有删锁或强行接管，消息通过原 HTTP Worker 的 explicit follow-up 完成 ACK。
- `provider_failure_missing_terminal_diagnostic`：wake-status 为 failed，但 diagnostic 列表没有这个 provider 错误的 wake_failed，后来的 agent_presented 来自 fallback。不得只凭 presentation 宣称原生唤醒。

完整调用、安全摘要和当前运行配置见 [原生唤醒补测](native-wake-followup.md)；JSON 现在包含 41 项历史与后续偏差。

## 共同记录规则

06:26 UTC 增补 `superseded_open_tasks_and_ownerless_cancel`：两个替代任务完成后，旧任务仍 open。主 Agent 取消请求已把它们改为不可领取的 cancel_requested；无 owner 却无法按约定直接 cancelled 的缺陷保留，未伪造 ACK 或直接改库。见 [收尾审计](completion-audit.md)。JSON 累计 42 项。

1. 所有时间使用 UTC ISO-8601，展示时可以附本地时区，但不删除原始时间。
2. 只记录公共 project/agent/session/thread ID、路径、错误码和摘要；ticket、session secret、私有 prompt、credential 文件内容不进入证据。
3. 每个异常必须有 `status`、`impact`、`evidence`、`resolution` 或 `follow_up`，并在 JSON 数据中保持同一 `id`。
4. 本文件不能把“可启动”“已发行 ticket”“工具可见”“thread 已创建”升级为“Agent ready”“A2A 成功”或“交付完成”。

## 计时记录

本轮测试用户给出的起点是 `2026-09-28 10:50`（Asia/Shanghai）。精确阶段计时见 [`timing-record.json`](timing-record.json)。部署的精确 installer 起止没有计时，因此只报告从测试起点到 project genesis 的 514.450 秒、到稳定 daemon 的 575 秒这两个可复核上界。WebUI 从首次 start 到最终 submit 的墙上时间为 4272.197 秒，持久化 running 窗口合计 260.901 秒，submit 到 main accept 为 154.430 秒；HTTP 分别为 2410.918 秒、682.825 秒和 1000.338 秒。墙上时间包含重复恢复与等待，running 合计只统计 SQLite 中有明确 `started_at`/`ended_at` 的 Attempt。
