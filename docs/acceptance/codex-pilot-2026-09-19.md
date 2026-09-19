# Codex 单宿主首轮协作试验：2026-09-19

本记录是 `elysia` 分支上的 **Codex 专项试验**，不是首发发布验收通过。首发规范仍要求 Codex、OpenCode、DeepSeek Harness 三宿主各自的 11 项真实证据；只完成 Codex 不能把 `release_check.py` 改成 PASS。T18/T23 保持 `in_progress`，任务负责人未改。

## 范围与可复核输入

- 操作者：协同者 `elysia080928`。测试时仓库 HEAD 为 `b8d8431`，另有尚未提交的 bridge/身份安全改动；本试验不把这些改动当作已发布能力。
- 宿主：本机 `codex-cli 0.155.0-alpha.9.2`。探针使用独立临时 `CODEX_HOME`、新建空 thread、不发送模型轮次，也不读取用户原有对话。
- 原始探针于本机 2026-09-19 17:01（UTC+08:00）写出；审查后保存为 [脱敏 JSON](../research/evidence/codex-2026-09-19T170100.json)。仓库副本与原始 JSON 的解析内容相等。它只有两个不可逆会话 digest，没有原始会话 ID、token、cookie、转录或私人绝对路径。

本轮使用的命令与结果如下；`--work-root` 和 `--output` 指向可写的本地验收目录，不要求固定私人路径：

```powershell
$codexExe = (Get-Command codex).Source
$acceptRoot = Join-Path (Get-Location) '.trellis/workspace/elysia080928'
uv run --offline --no-sync python tools/conformance/probes/codex/probe.py --executable $codexExe --work-root $acceptRoot --output (Join-Path $acceptRoot 'codex-native-probe.json')
uv run --offline --no-sync tsunagou agent enroll --adapter codex --mode attach
uv run --offline --no-sync python tools/dev/release_check.py
```

| 命令 | 实际退出码 | 实际结果 |
|---|---:|---|
| `codex --version` | 0 | `codex-cli 0.155.0-alpha.9.2` |
| Codex 无模型 app-server 探针 | 0 | 初始化成功；同目录两个新 thread 的身份 digest 不同；空 thread 的 resume/fork 返回 `-32600`；`ready: false` |
| `tsunagou agent enroll --adapter codex --mode attach` | 0 | JSON 为 `status: ticket_required`；**退出 0 不是接入成功** |
| Codex adapter + bridge 定向 Vitest | 0 | 17/17 通过；只证明本地测试夹具和 bridge 逻辑，不是宿主经 Tsunagou 完成协作 |
| Python 全量 pytest、Ruff、mypy、协议校验、六 workspace TypeScript 检查 | 0 | 工程门禁通过；pytest 有 1 项跳过，协议为 106 policies / 111 schemas |
| `release_check.py` | 1 | Codex 仍缺下表 10 项；OpenCode/DeepSeek 也各缺 10 项 |

## 其余十项逐项结果

正式通过要求按 [首轮验收步骤](first-live-acceptance.md) 第 8 节，使用 **两个经独立 ticket 兑换且已绑定 HostSession 的真实 Codex 会话**（main 与 worker）。本轮 CLI 在票据阶段停止，没有建立任何 HostSession；因此下表的“阻断”是前置链路缺失，**不是能力实测失败**。

| 能力 | 本轮实际观测 | 下次接通链路后的最小复测 |
|---|---|---|
| `identity.continuity_evidence` | unknown；空 thread 的 resume/fork 返回 `-32600`，不能证明有内容会话的连续性 | 在真实已接入会话中依次核对 resume/compact 与 new/fork 的身份变化，并验证 bridge 绑定 |
| `context.project_read` | unknown；无 HostSession、项目查询入口未进入 | worker 查询项目 ID、任务与自己的 scope，确认不串项目 |
| `command.typed_tools` | unknown；没有安装到真实 Codex 会话的项目工具 | 列举已注册工具，拒绝未知字段和伪造 actor |
| `task.lifecycle` | unknown；没有就绪 worker | 真实执行 claim、preflight、start、progress、submit，逐步核对 owner/状态 |
| `cognition.report` | unknown；没有就绪 worker/main | worker 提交显式理解、假设、不确定性及证据，main 读取版本 |
| `contract.participation` | unknown；没有两个项目成员 | 两个身份分别对同一精确 proposal digest 表态；ACK 不算接受 |
| `inbox.pull_fetch_ack` | unknown；bridge 单元测试不等于 Codex 真机呈现 | recipient-only pull/claim、fetch、presented、ACK；断 push 后补拉 |
| `response.structured` | unknown；没有真实请求/义务 | 对带 response contract 的请求返回 Schema 合格回应；ACK 不替代回应 |
| `recovery.idempotent_reconnect` | unknown；桥接并发回归通过但无真机断线 | 命令到达服务端后断线，递增 epoch 恢复，旧连接不得再提交 |
| `delivery.deduplicate` | unknown；桥接单元测试通过但无真机重传 | 同 ID 同输入重试返回原结果；同 ID 改输入冲突，不产生第二次动作 |

`identity.session_isolation` 是此前 11 项中唯一有宿主原生证据的一项；它只证明 Codex 两个 thread 不同，**不能单独证明两个 Tsunagou Agent 已入会或相互隔离**。

## 实施进度、根因与最短后续顺序

代码检查与实测一致：当前 CLI 的 `agent enroll` 固定返回 `ticket_required`；默认 HTTP dispatcher 没有业务 handler；Codex adapter 仍主要是诊断映射，缺少把真实会话、私下票据、工具入口与共享 bridge 连起来的安装/运行路径。之前仅凭调用者提供 `X-Principal-*` 请求头不能当作可信身份。本工作区中的未提交改动已经补了旧 epoch 在途请求的缓存竞态、证据缺失不得 ready、票据只存哈希及 HTTP 拒绝自报身份；它们通过了本地回归，但**尚未实现真实 Codex 接入，也不增加任何一项真机 baseline**。

后续按依赖顺序推进，避免重复跑被前置条件阻断的十项：

1. 完成用户控制凭据、选择目标 Codex 对话、私下签发/交付一次性票据与服务端兑换；服务端绑定独立 HostSession 和凭据，不能让模型填写 actor 或看到 ticket/token。
2. 把真实 Codex app-server 会话身份和生命周期接入 adapter/bridge，并把经过认证的工具命令接到已注册领域 handler；先使两个会话得到可审计的 `ready` 或明确 `degraded`，不能硬改字符串。
3. 在独立临时项目里按上表顺序逐项取证；每项保存宿主/adapter/协议版本、schema digest、脱敏 session digest、时间、结果引用与失败原因。真实失败再修复并回归。
4. Codex 11 项全有真实 Tsunagou 链路证据后可称为“Codex 单宿主试点完成”。若要称为**原定首发版本通过**，仍需 OpenCode 与 DeepSeek Harness 同样通过，或由用户/Leader 明确批准变更发布范围；本轮未改发布门禁。
