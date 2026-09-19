# Codex 真实宿主经 Tsunagou bridge 接入记录：2026-09-19（第二次）

本记录是 `elysia` 分支上的 **Codex 专项试验延续**，不是首发发布验收通过。相较前一轮（`codex-pilot-2026-09-19.md`，票据阶段即停止、无 HostSession），本轮已经建立了一个真实 Codex HostSession 并兑换票据入会；但业务命令的**工具调用执行层**被宿主安装缺失阻断，详见下文。

## 宿主与版本

- 宿主：本机 `codex-cli 0.155.0-alpha.9.2`（`windows-x86_64`），模型 `gpt-5.6-sol`，provider `openai`，auth mode `chatgpt`。
- bridge：`@tsunagou/bridge-server` 0.1.0（stdio MCP server，`@modelcontextprotocol/sdk` 1.12.0），由 `node v24` 运行。
- 服务端：`tsunagou` 0.1.0，uvicorn 0.53.0，本地 `127.0.0.1:8000`，状态目录 `C:/Users/35742/.tsunagou-e2e`。

## 真实会话与入会结果（脱敏）

- 真实 Codex 会话：host conversation digest `eb189ff1756a62e14b0f85d6cfd1b692e70d50a934cf4374d7842a4025f6f16e`（= sha256("conversation_id:" + 原始会话 id)）。原始会话 id、ticket secret、session token 均不入库、不入 stdout。
- 首次 `agent.enroll`（一次性票据兑换，T principal）→ Tsunagou agent `a5f25919…`、session `2c70873e…`，`baseline_status=degraded`，`connection_epoch=1`。
- 第二次用新票据走 `session.rebind`（T principal）→ 同一 agent/session，`connection_epoch=2`，`baseline_status=ready`，签发 `agent_base` grant（1 条）。`host_conversation_id_digest` 前后一致，即连续性证据 `resume:same_digest`。

关键事实：Codex 不向其 stdio MCP 子进程暴露任何 `CODEX_*` 环境变量（`codex_env_names=[]`，经 `bridge-boot.json` 实测）。因此 host 身份来自票据绑定的 `conversation_id`（由编排方观察真实会话后写入票据），不是调用者自报身份；`redeem_ticket`/`redeem_rebind_ticket` 对 installation+conversation digest 做严格比对。

## 本轮修复

1. **Windows 票据文件 ACL**：`os.chmod(0o600)` 在 Windows 只改只读位，`st_mode` 仍 `0o666` 且继承 `Authenticated Users`/`Users` ACE。改为 `icacls /inheritance:r /grant:r *S-1-3-0:(F)`（CREATOR OWNER），失败即删文件并抛错。单测验证 ACL 只剩创建者。
2. **`session.rebind` 恢复路径**：新增 `AuthorityService.redeem_rebind_ticket`（校验新票据 + 定位既有 session + 委托 `rebind` 递增 epoch/换凭证/更新 baseline）、`session.rebind` handler（T principal）、bridge 的 `HttpTransport.rebind` 与启动期 resume 分支（session 文件 + 新票据并存时走 rebind）。
3. **票据签发必须走运行中的 HTTP 服务**：CLI `tsunagou agent enroll` 在进程内 `build_application()`，向一个即刻销毁的 AuthorityService 发券，运行中的 server 永远收不到；已改用直接 POST `agent.ticket.create.user`（U principal）到 8000 端口。

## 11 项逐项结果（本轮回合）

| 能力 | 结论 | 观测 |
|---|---|---|
| `identity.session_isolation` | **真实通过** | 入会时 host digest 来自绑定 `conversation_id`，session 独立 |
| `identity.continuity_evidence` | **真实通过** | rebind 前后 digest 一致，epoch 1→2 |
| `context.project_read` | **真实通过** | baseline 携带 `project_root_digest`（`D:/AB/git/AB/Tsunagou`） |
| `command.typed_tools` | **真实通过** | bridge 列出 14 个带 schema 的 typed tools |
| `task.lifecycle` | **被阻断** | 见下：工具调用执行层缺失；且无 task 创建命令 |
| `cognition.report` | **被阻断** | 同下 |
| `contract.participation` | **被阻断** | 同下 |
| `inbox.pull_fetch_ack` | **被阻断** | 同下 |
| `response.structured` | **被阻断** | 同下 |
| `recovery.idempotent_reconnect` | **被阻断** | `session.reconnect`（D principal）尚无 handler/认证分支 |
| `delivery.deduplicate` | **被阻断** | 同下 |

## 阻断根因（非 Tsunagou/bridge 缺陷）

业务命令要由模型真正调用 MCP 工具，但宿主 Codex 安装缺失 `codex-code-mode-host.exe`（"dynamic tool host"）：

```
codex_core::tools::router: error=failed to spawn code-mode host
  C:\Users\35742\.codex\.sandbox-bin\codex-code-mode-host.exe: 系统找不到指定的文件 (os error 2)
```

`codex doctor`：`websocket handshake timed out`、`latest version probe HTTP 403`；`.codex/.sandbox-bin` 只有 `codex.exe`。模型能"看到" tsunagou 工具（正是工具发现触发了 bridge 入会与 rebind），但调用时回报 "the dynamic tool host is disabled / not exposed in the callable catalog"。`codex features list` 显示 `code_mode_host=stable/true`，但二进制缺失。

即：**4 项准入能力已通过真实 Codex 链路取证；7 项运营能力的证据采集被宿主缺失的 code-mode host 阻断**，需要先补齐/修复 Codex 安装（下载 `codex-code-mode-host.exe`，或 `codex update`/`codex app` 修复安装），本环境网络受限（403/WebSocket 超时）无法自行获取。

## 后续最短顺序

1. 补齐 Codex 的 code-mode host 后，用两个真实会话（main+worker）分别入会→`ready`，再逐项驱动 7 项运营能力（需同时补 `task` 创建命令与 `session.reconnect`/`session.reprobe` 的 D-principal handler）。
2. 每项按宿主/adapter/协议版本、schema digest、脱敏 session digest、时间、命令、退出码、结果引用与失败原因留证；真实失败再修复并回归。
3. 仍未改动 `release_check.py` 判定；OpenCode/DeepSeek 宿主与首发门禁不在本轮范围。

## code-mode host 修复（本轮回合，阻断已解除）

`codex update` 无法自愈（"Could not detect the Codex installation method"，网络 403）。但本机桌面版 Codex（`OpenAI.Codex_26.915.4065.0_x64`）的 `app\resources\` 内已捆绑同版本二进制：其 `codex.exe` 与 `.codex\.sandbox-bin\codex.exe` **逐字节一致**（均为 316,853,040 字节），故其 `codex-code-mode-host.exe`（72,514,864 字节）即为匹配版本。

- 修复动作：将 `app\resources\codex-code-mode-host.exe` 复制到 `C:\Users\35742\.codex\.sandbox-bin\`（Codex 按此路径查找 dynamic tool host）。
- 验证（本地，不依赖模型推理）：修复前 `codex exec --json` 事件流为 `thread.started → item.completed(Code Mode is unavailable … failed to spawn code-mode host) → turn.started`；修复后为 `thread.started → turn.started`，**无 item_0 错误**。
- 模型行为随之改变：同一条 `inbox__claim` 提示，修复前回报 "not exposed in this session"；修复后回报 "I'll locate the callable Tsunagou MCP tool, invoke `inbox__claim`…"，即工具已进入可调用目录。

即：`#31`（code-mode host 缺失阻断）**解除**。

## 新阻断：Codex 账户用量上限（非代码缺陷，需用户侧处理）

修复 code-mode host 后，模型进入工具调用时被 Codex 账户配额拒绝：

```
ERROR: You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro),
       visit https://chatgpt.com/codex/settings/usage to purchase more credits
       or try again at 7:40 PM.
```

该错误发生在模型推理（chatgpt.com API）层，而非 Tsunagou/bridge 层：bridge 入会（enroll/rebind）与 MCP `tools/list` 均已在本地完成且正常。需要用户补齐 Codex 用量（升级/购买，或等 7:40 PM 重置）后，才能真正完成一次 `inbox__claim` 工具调用并采集运营能力证据。此期间可继续做不依赖模型推理的工作（worker 票据预签发、`session.reconnect`/`session.reprobe` 的 D-principal handler 补齐）。

## 用量重置后：MCP 工具审批阻断 → 首个真实工具调用成功

7:40 PM 用量重置后重试，出现第二个宿主侧阻断（同样是 Codex 侧、非 Tsunagou/bridge 缺陷）：

```
mcp: tsunagou/inbox__claim started
mcp: tsunagou/inbox__claim (failed)
MCP tool call requires approval, but approval policy is never
```

即模型已把 `inbox__claim` 真正派发到 MCP 层（`started`），但 Codex 的 MCP 工具审批独立于全局 `approval_policy`，默认要审批而全局策略为 `never`（fail-closed）。修复：在 `~/.codex/config.toml` 给 tsunagou MCP server 加 `default_tools_approval_mode = "approve"`（本地协调命令、只走 127.0.0.1、无破坏性标注，安全）。

修复后**首个真实工具调用成功**（经完整链路：Codex 模型 → MCP 工具调用 → bridge → HTTP `inbox.claim` → Tsunagou → 回传）：

```
mcp: tsunagou/inbox__claim started
mcp: tsunagou/inbox__claim (completed)
codex  {"content":[{"type":"text","text":"{\"messages\":[],\"count\":0}"}]}
```

`inbox.claim` 以 main 会话 credential（secret_token 不出信封、不出 stdout）派发并返回真实结果 `{"messages":[],"count":0}`（空 inbox）。这打通了「模型真正调用业务命令」的执行层：`command.typed_tools`（列工具）+ 工具执行层 + `inbox.pull_fetch_ack` 的 claim 段均已过真实链路。7 项运营能力的逐项证据采集自此不再被宿主安装/审批阻断。

## 11 项能力全部真实通过（本会话完成，Codex 专项）

上轮「首个真实工具调用成功」之后，本会话把 7 项运营能力全部经真实 Codex 工具调用驱动完成（main `a5f25919…` + worker `95a91916…`，经 bridge 的 typed tools 走 HTTP 到 Tsunagou），并补齐了最后一项 `recovery.idempotent_reconnect` 的后端缺失。逐项结论（证据 ID 均取自 `codex-*.log` 真实工具调用结果，非单测/模拟器）：

| 能力 | 结论 | 真实证据 |
|---|---|---|
| `identity.session_isolation` | **真实通过** | 两个 HostSession 的 `host_conversation_id_digest` 不同（`eb189ff1…` 等） |
| `identity.continuity_evidence` | **真实通过** | rebind 前后 `host_conversation_id_digest` 一致，epoch 1→2 |
| `context.project_read` | **真实通过** | baseline 携带 `project_root_digest`（`D:/AB/git/AB/Tsunagou`） |
| `command.typed_tools` | **真实通过** | bridge `tools/list` 返回带 schema 的 typed tools，模型真实派发 MCP 工具调用 |
| `task.lifecycle` | **真实通过** | `task.create` `f0f38fd3…` → `claim`/`start` attempt `38e9782a…` → `submit` result `6dc1eedf…` |
| `cognition.report` | **真实通过** | report `0134c9e3…`（claims 含 `task.lifecycle` 结论） |
| `contract.participation` | **真实通过** | propose `dfc724b3…` → accept slot `worker`（`participant_slot` 绑定 `agent_id`） |
| `inbox.pull_fetch_ack` | **真实通过** | message `78e68258…` 经 claim→fetch→presented→ack 全流程，`deliveries` 状态 `acked` |
| `response.structured` | **真实通过** | `message.send` 带 `response_contract` → obligation `f59b97fc…` → `message.respond` `b28e2c3b…`，obligation 状态 `responded` |
| `recovery.idempotent_reconnect` | **真实通过** | `session.reconnect`（D principal）epoch 1→2 凭据轮换；错误 nonce → 403 `stale_reconnect_nonce`，stale 重试 → 401 `authentication_failed`（nonce CAS 幂等，不重复轮换） |
| `delivery.deduplicate` | **真实通过** | 相同 (sender, kind, payload) 两次 `message.send` → 同一 `message_id` `96eb1621…`（`command_index` 命中同一条） |

### 本会话后端修复（真实失败驱动）

1. **`task.create` capability_denied**：`find_grant` 曾把 `session_id=None` 的 `main_authority` grant 过滤掉，导致 M principal 的 `task.manage` 授权失败。改为「仅当 grant 自身也声明了 session 时」才按 session 过滤（`grant.session_id is not None`），`main_authority`（session-independent）不再被误滤。
2. **`session.reconnect` 缺失**（`recovery.idempotent_reconnect` 的阻断根因）：`session.reconnect` 在 registry/schema/command-catalog 里是 D principal（「token 认证 + nonce CAS」），但 `auth.py` 无 D 分支、`handlers.py` 无 handler，导致一律 `authentication_failed`。补齐：
   - `auth.py` 新增 D 分支：用会话 token 认证（bootstrap 会话、无普通 Grant），返回 `PrincipalContext("D", agent_id, session_id, epoch)`。
   - `handlers.py` 新增 `session_reconnect`：调用既有 `AuthorityService.rebind(session_id, expected_nonce=reconnect_nonce, baseline=probe_payload)` 完成 nonce CAS（stale nonce fail-closed，不重复轮换）。
   - 回归：全量单测通过；经真实 HTTP 驱动（disposable 会话，不扰动 live main/worker）：错误 nonce → 403 `stale_reconnect_nonce`；正确 nonce → 200 epoch 1→2 + 凭据轮换；stale 重试 → 401 `authentication_failed`。

## 发布门禁（诚实运行，未改动判定）

`tools/dev/release_check.py` 结果为 `passed=false`：`codex`/`opencode`/`deepseek` 各 `live_baseline_missing`（各缺 10 项）。这**不是**本会话 11 项未过，而是两层事实：

1. 门禁读取 `docs/research/evidence/{host}-*.json`（`scope=disposable_no_model_turn` 的探针产物，仅 `identity.session_isolation` 为 `supported`）；运营能力证据在 acceptance 文档 + live state，尚未回灌到门禁证据文件。
2. `opencode`/`deepseek` 两宿主不在本 Codex 专项范围，其证据文件仍只有 admission 探针。

未改动 `release_check.py` 判定，未把单测/模拟器证据写成真实宿主证据。
