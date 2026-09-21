# 首次真实验收执行单

2026-09-20更新：本文件保留原多宿主正式发布的验收流程。当前用户要求先交付独立运行的最小成品，请执行[当前代码与成品调试单](../standalone/debugging-runbook.md)。现有问题不止宿主证据缺失，[真实HTTP审计](../standalone/status-and-gaps.md)已复现核心功能缺口；旧任务完成标记不能据此跳过修复。

本文件保留原多宿主正式发布的验收模板。2026-09-20 用户要求关闭全部旧任务，T18–T21、T23–T24 已放弃归档，不再待本文件验收。下文是历史目标与操作参考，当前活动任务和关闭标准见 [M1 / R1–R6](../implementation/roadmap.md)。

2026-09-19 的 [Codex 单宿主试验记录](codex-pilot-2026-09-19.md)逐项说明其余十项当前为何被接入链路阻断，以及下次复测顺序；它不改变下文三宿主首发门禁。

执行目录假定为 `D:\Tsunagou`，宿主为 Windows PowerShell。路径、端口、项目目录和版本必须按实际机器替换；命令中的 `<...>` 不是可以原样提交的值。

## 1. 原计划未完成内容（任务已放弃归档）

| 任务 | 未完成内容 | 关闭所需的直接证据 |
|---|---|---|
| T18 Codex | 11 项共同基线、连续性、恢复、去重和正式 ready 判定 | 指定 Codex 版本的脱敏 evidence；11 项全部 `supported` 且每项有 `evidence_refs` |
| T19 OpenCode | 完整基线、重复/乱序事件、断线恢复和去重 | 指定 OpenCode 版本的真实 headless/宿主记录；不能只用当前 session probe |
| T20 ZCode（首发后置） | 保留适配器、Hook 研究和诊断；暂不进入首发验收 | 后续版本再补官方宿主、Hook、重启和完整基线；不阻塞本次发布 |
| T21 DeepSeek Harness | 完整基线、恢复、去重、并行会话和 typed tools | 指定 Harness 版本、临时家目录、无秘密 evidence；当前仅 session isolation 已有证据 |
| T23 工程与发布门禁 | Windows 完整基线、平台范围和所有发布检查 | 本地质量门禁全绿，三个首发宿主 live baseline 全绿，`release_check.py` 返回 0 |
| T24 演示与实验 | A/B/C/D 各至少 5 次、多 Agent、另一宿主复验和报告 | 20 个真实 run、原始结果引用、失败样本、指标报告和三个首发宿主演示记录 |

T01–T17、T22 保留历史完成记录。原依赖与 Trellis 文件见[旧任务计划](../implementation/task-plan-legacy-2026-09-18.json)以及各归档目录：

- [T18 Codex](../../.trellis/tasks/archive/2026-09/09-18-t18-adapter-codex/prd.md)
- [T19 OpenCode](../../.trellis/tasks/archive/2026-09/09-18-t19-adapter-opencode/prd.md)
- [T20 ZCode](../../.trellis/tasks/archive/2026-09/09-18-t20-adapter-zcode/prd.md)
- [T21 DeepSeek Harness](../../.trellis/tasks/archive/2026-09/09-18-t21-adapter-deepseek/prd.md)
- [T23 发布门禁](../../.trellis/tasks/archive/2026-09/09-18-t23-integration-release-gates/prd.md)
- [T24 实验与演示](../../.trellis/tasks/archive/2026-09/09-18-t24-experiments-demo/prd.md)

## 2. 验收规则

1. `unknown` 不是通过；没有 evidence 引用的 `supported` 也不是通过。
2. 模拟器、fixture、单元测试和模型 API 调用不能替代真实宿主证据。
3. 不把 token、cookie、原始宿主会话 ID、完整转录、绝对私有路径写入仓库。
4. 三个首发宿主都必须满足同一组 11 项基线：

   `identity.session_isolation`、`identity.continuity_evidence`、`context.project_read`、`command.typed_tools`、`task.lifecycle`、`cognition.report`、`contract.participation`、`inbox.pull_fetch_ack`、`response.structured`、`recovery.idempotent_reconnect`、`delivery.deduplicate`。

   其中前 4 项（`identity.session_isolation`、`identity.continuity_evidence`、`context.project_read`、`command.typed_tools`）是**准入能力**：会话 `ready` 只看这 4 项，可由宿主原生探针 + adapter 安装自测在入会前真实预攒。其余 7 项是**运营能力**，必须由 ready 会话经 Tsunagou 真实执行后产生。`release_check.py` 仍要求三个首发宿主各自 11 项全部有真实 `evidence_refs`；`ready` 不等于首发通过。

5. `tsunagou agent enroll` 只签发一次性票据并写入 0600 私有文件（不打印到 stdout），不代表 Agent 已加入。只有宿主 bridge 从该文件领取票据、通过 `agent.enroll` 兑换、建立独立 session 并通过 4 项准入能力后，才算接入。

## 3. 准备验收工作区

在 PowerShell 中执行：

```powershell
Set-Location D:\Tsunagou
$ErrorActionPreference = "Stop"

$acceptRoot = Join-Path $env:TEMP ("tsunagou-first-acceptance-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
$coordRoot = Join-Path $acceptRoot "control-repo"
$evidenceRoot = Join-Path $acceptRoot "evidence"
New-Item -ItemType Directory -Force -Path $coordRoot, $evidenceRoot | Out-Null

git init --initial-branch=main $coordRoot
Set-Content -LiteralPath (Join-Path $coordRoot "README.md") -Value "# Tsunagou acceptance control repository`n"
git -C $coordRoot add README.md
git -C $coordRoot -c user.name="Tsunagou Acceptance" -c user.email="acceptance@localhost" commit -m "seed acceptance control repository"

Set-Location D:\Tsunagou
uv sync --extra dev
corepack pnpm install --frozen-lockfile
```

记录工作区位置，后续所有 evidence 和日志都写入 `$acceptRoot`。不要把真实用户项目作为故障注入或实验目录。

## 4. 先通过本地工程门禁

逐条执行，任何一条非零退出都先修复对应代码或环境，不进入宿主验收：

```powershell
Set-Location D:\Tsunagou
uv run pytest -q
uv run ruff check src tests tools
uv run mypy src tools/dev/release_check.py tools/conformance/probes/opencode/probe.py tools/conformance/probes/deepseek/probe.py tools/conformance/probes/zcode/probe.py
uv run python tools/codegen/validate_protocol.py
corepack pnpm run check
corepack pnpm exec vitest run
python tools/docs/validate_docs.py
```

预期：测试、Ruff、mypy、协议校验、TypeScript、Vitest 和文档校验均返回 0。当前发布门禁故意仍会失败，先不要把它混入本节；它要等三个首发宿主 evidence 更新后再运行。

## 5. 初始化协调项目并启动本机 HTTP

### 5.1 初始化项目

协调目录必须是 Git 仓库，且初始化从第一步就在项目内生成 `.tsunagou/`：

```powershell
Set-Location D:\Tsunagou
$initText = uv run tsunagou project init `
  --coordination-root $coordRoot `
  --name "Tsunagou first live acceptance" `
  --objective "验证三个首发宿主接入、任务边界、恢复和消息去重"
$initText | Tee-Object -FilePath (Join-Path $acceptRoot "project-init.json")
$projectId = ($initText | ConvertFrom-Json).project_id
Write-Host "project_id=$projectId"
Test-Path (Join-Path $coordRoot ".tsunagou\project.json")
```

预期：输出包含非空 `project_id`、`status` 为 `active`，最后一条输出为 `True`。如果出现 `coordination_repository_must_be_git_repository`，说明 Git 初始化没有成功。

### 5.2 启动 HTTP 服务

当前应用工厂提供 `/api/v1/health` 和命令 dispatcher。使用 loopback、固定的临时端口和独立日志启动，不开启 reload：

```powershell
$apiPort = 8765
$apiOut = Join-Path $acceptRoot "http.stdout.log"
$apiErr = Join-Path $acceptRoot "http.stderr.log"
$apiProcess = Start-Process -FilePath "uv" `
  -ArgumentList @("run", "uvicorn", "tsunagou.api.app:create_app", "--factory", "--host", "127.0.0.1", "--port", "$apiPort") `
  -WorkingDirectory "D:\Tsunagou" `
  -RedirectStandardOutput $apiOut `
  -RedirectStandardError $apiErr `
  -PassThru
Start-Sleep -Seconds 2

$health = Invoke-RestMethod -Method Get -Uri ("http://127.0.0.1:{0}/api/v1/health" -f $apiPort)
$health | ConvertTo-Json -Depth 5
if ($health.status -ne "ok") { throw "HTTP health check failed" }
```

预期：JSON 中 `status` 为 `ok`、`version` 为 `0.1.0`。服务只绑定 `127.0.0.1`。当前 HTTP dispatcher 未为所有领域命令装配 handler，收到 `handler_not_registered` 属于当前未完成实现，不能伪造成功响应。

停止服务的命令：

```powershell
Stop-Process -Id $apiProcess.Id -Force
```

## 6. 验证用户边界和当前接入外壳

先运行 CLI 的可执行外壳：

```powershell
Set-Location D:\Tsunagou
uv run tsunagou --version
uv run tsunagou doctor
uv run tsunagou agent enroll --adapter codex --mode attach
uv run tsunagou agent enroll --adapter opencode --mode attach
uv run tsunagou agent enroll --adapter deepseek --mode attach
```

当前四条 `enroll` 都应输出类似：

```json
{"adapter":"codex","mode":"attach","status":"ticket_required"}
```

这一步只证明 CLI 不会凭空把 Agent 标为已加入；它不能关闭 T18–T21。要关闭任务，必须在对应适配器中完成 ticket 创建、bridge 私下兑换、HostSession 绑定、独立 principal 和真实基线，然后让 `agent enroll` 返回可审计的 `ready` 或明确的 `degraded` 诊断。

## 7. 启动并探测真实宿主

每种宿主都使用新的临时目录。探针输出写入 `$evidenceRoot`，完成后把脱敏 JSON 复制到 `docs/research/evidence/`；复制前先检查其中没有 token、cookie、原始会话 ID、转录或私有绝对路径。

### 7.1 Codex

先确认目标可执行文件和版本：

```powershell
Get-Command codex
codex --version
```

运行无模型 disposable app-server 探针：

```powershell
$codexEvidence = Join-Path $evidenceRoot ("codex-" + (Get-Date -Format "yyyy-MM-dd-HHmmss") + ".json")
uv run python tools/conformance/probes/codex/probe.py --output $codexEvidence
Get-Content $codexEvidence
```

该探针只能验证安装、初始化和部分 thread 身份隔离。要完成 T18，必须在真实 Codex 会话中通过 adapter/bridge 验证项目读取、typed tools、任务操作、认知报告、契约、inbox、结构化响应、重连和去重；不能用本探针的 `ready: false` 改写成 `ready: true`。

### 7.2 OpenCode

启动官方 npm 包的纯 headless 服务：

```powershell
$openCodePort = 4096
$openCodeOut = Join-Path $acceptRoot "opencode.stdout.log"
$openCodeErr = Join-Path $acceptRoot "opencode.stderr.log"
$openCodeProcess = Start-Process -FilePath "npx" `
  -ArgumentList @("--yes", "opencode-ai@1.18.31", "serve", "--pure", "--hostname", "127.0.0.1", "--port", "$openCodePort") `
  -WorkingDirectory $coordRoot `
  -RedirectStandardOutput $openCodeOut `
  -RedirectStandardError $openCodeErr `
  -PassThru
Start-Sleep -Seconds 3

$openCodeEvidence = Join-Path $evidenceRoot ("opencode-" + (Get-Date -Format "yyyy-MM-dd-HHmmss") + ".json")
uv run python tools/conformance/probes/opencode/probe.py `
  --base-url ("http://127.0.0.1:{0}" -f $openCodePort) `
  --directory $coordRoot `
  --output $openCodeEvidence
Get-Content $openCodeEvidence
```

探针结束后停止服务：

```powershell
Stop-Process -Id $openCodeProcess.Id -Force
```

当前探针已证明同目录独立 session、session detail、fork、history 和 typed API；T19 仍需真实 bridge 验证其余 10 项及重复/乱序通知和断线恢复。

### 7.3 DeepSeek Harness

必须使用临时 Harness 家目录，不能使用用户现有 `C:\Users\...\.dsh`：

```powershell
$dshHome = Join-Path $acceptRoot "dsh-home"
$dshAgents = Join-Path $acceptRoot "dsh-agents"
$env:DSH_HOME = $dshHome
$env:DSH_AGENTS_HOME = $dshAgents
$env:DSH_TELEMETRY_DISABLED = "1"

npx --yes @deepseek-ai/dsh@0.1.5-rc.2 web --no-open --host 127.0.0.1 --port 0
```

在该进程仍运行时，把启动输出中的一次性 token 只放入当前 PowerShell 进程，不要回显、写文件或提交：

```powershell
$env:DSH_WEB_TOKEN = "<temporary-token-from-launch-output>"
$dshEvidence = Join-Path $evidenceRoot ("deepseek-" + (Get-Date -Format "yyyy-MM-dd-HHmmss") + ".json")
uv run python tools/conformance/probes/deepseek/probe.py `
  --base-url "http://127.0.0.1:<port>" `
  --directory $coordRoot `
  --output $dshEvidence
Get-Content $dshEvidence
```

停止 Harness 后清理临时目录和 token：

```powershell
Remove-Item Env:DSH_WEB_TOKEN -ErrorAction SilentlyContinue
Remove-Item Env:DSH_HOME, Env:DSH_AGENTS_HOME, Env:DSH_TELEMETRY_DISABLED -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $dshHome, $dshAgents -Recurse -Force -ErrorAction SilentlyContinue
```

当前 probe 只证明 token 交换、cookie 认证、同目录独立 session 和 session list；T21 还必须验证并行 session、工具调用、恢复、重复事件和去重。

### 7.4 ZCode（首发后置，不执行也不阻塞本次验收）

先确认是否有官方可执行文件：

```powershell
Get-Command zcode -ErrorAction SilentlyContinue
```

如果不存在，生成明确的 unknown 证据：

```powershell
$zcodeEvidence = Join-Path $evidenceRoot ("zcode-" + (Get-Date -Format "yyyy-MM-dd-HHmmss") + ".json")
uv run python tools/conformance/probes/zcode/probe.py --output $zcodeEvidence
Get-Content $zcodeEvidence
```

此时 T20 仍保持首发后置。只有找到可核验的官方 CLI/API、锁定版本、安装 Hook/MCP、创建新会话并完成 11 项基线后，才可在后续版本更新证据。非官方 npm 包、社区 bridge 或只读网页文档不能作为正式宿主证据；本次首发不需要执行本节。

## 8. Agent 接入后的 11 项测试顺序

当对应 adapter 已经能返回 `ready` 后，打开两个同项目、同根目录但不同宿主会话：一个登记为 `main`，一个登记为 `worker`。不要把宿主临时 subagent 自动当作项目成员；每个会话都必须经过独立 ticket、bridge 和 HostSession。

由用户先执行用户级接入：

```powershell
uv run tsunagou agent enroll --adapter <codex|opencode|deepseek> --mode attach
```

然后由目标宿主的 bridge 私下兑换 ticket。不要把 ticket 或 session token 粘贴进 Agent 对话。用户只确认是否任命 main；普通 worker 不要求用户逐项确认普通任务。

在 main Agent 中创建一个低风险测试任务，并让 worker 按下列顺序报告。报告只能包含显式理解、假设、不确定性、证据引用和结构化结果，不要求暴露隐藏思维链：

| 顺序 | 检查 | 操作和通过条件 |
|---:|---|---|
| 1 | 会话隔离 | 同一项目/目录建立两个 HostSession；两个脱敏身份 digest 不同，worker 不能读取 main 的 inbox 或 Attempt |
| 2 | 连续性 | 在同一会话执行 `resume/new/clear/fork` 或宿主等价操作；bridge 能把同一 conversation 绑定到原 session，分叉得到新身份 |
| 3 | 项目上下文 | worker 通过 blackboard/project query 读取项目 ID、当前任务和自己的 scope；共享结果不得含 token 或绝对私有路径 |
| 4 | 类型化工具 | worker 只能看到已注册 command/schema；未知字段和伪造 actor 被拒绝 |
| 5 | 任务生命周期 | worker 依次执行 claim、preflight、start、progress、submit；每一步状态和 owner 与任务记录一致 |
| 6 | 认知报告 | worker 提交 understanding、assumptions、uncertainties、claims、confidence 和 evidence refs；main 能看到报告版本 |
| 7 | 契约协商 | main/worker 对同一 proposal 分别提交 accept 或 reject；只 ACK 消息不能代替 contract acceptance |
| 8 | 收件箱 | worker 执行 pull/claim、fetch、presented、ACK；断开 push 后仍可用 pull/sync 完整恢复 |
| 9 | 结构化回应 | 对带 `response_contract` 的请求产生符合 Schema 的 response；普通 ACK 不能伪装成回应 |
| 10 | 断线恢复 | 请求已到达服务端后断开 bridge，重连时使用递增 connection epoch；不得重复创建 Attempt、消息或 Grant |
| 11 | 去重 | 相同 `command_id` 和相同输入重试得到原结果；相同 ID 改输入得到 `idempotency_conflict`，不得执行第二次 |

每一项都要记录：宿主版本、adapter 版本、protocol/schema digest、脱敏 session digest、步骤时间、结果引用和失败原因。没有这些字段的手工截图不能作为正式 evidence。

## 9. 运行发布门禁

把确认过且已脱敏的四个 evidence 文件放入 `docs/research/evidence/`，命名为 `<host>-<date>.json`。不要修改 `baseline` 只为让检查通过；每一行必须由真实操作产生。

```powershell
Set-Location D:\Tsunagou
uv run python tools/dev/release_check.py
```

当前不完整证据会返回退出码 1，并列出每个宿主缺少的 capability。只有以下结果才算 T23 的宿主门禁通过：

```json
{"failures":[],"missing_capabilities":{},"passed":true}
```

随后重新运行完整质量门禁：

```powershell
uv run pytest -q
uv run ruff check src tests tools
uv run mypy src tools/dev/release_check.py tools/conformance/probes/opencode/probe.py tools/conformance/probes/deepseek/probe.py tools/conformance/probes/zcode/probe.py
corepack pnpm run check
corepack pnpm exec vitest run
python tools/docs/validate_docs.py
```

## 10. 准备并执行 T24 实验

先生成预注册计划；这个命令只生成 20 个 planned run，不会伪造结果：

```powershell
Set-Location D:\Tsunagou
$planPath = Join-Path $coordRoot ".tsunagou\evaluation\plan.json"
New-Item -ItemType Directory -Force -Path (Split-Path $planPath) | Out-Null
uv run python tools/experiments/prepare.py --replicates 5 --output $planPath
Get-Content $planPath -TotalCount 80
```

实验臂必须保持以下定义：

- A：单 Agent。
- B：多 Agent + Worktree。
- C：完整认知报告、契约协商、持久 inbox 和恢复。
- D：多 Agent，但关闭认知协调能力作为消融条件。

执行时锁定同一任务集 digest、模型版本、宿主版本、adapter/protocol/config digest、预算和随机顺序。B/C/D 的正式多 Agent 组至少使用 3 个 Agent；每臂至少 5 次；至少在另一种宿主复验方向。失败、超时和 token unavailable 都保留，不能删除失败 run。

当前仓库只有计划生成器，没有一个可以凭空替用户完成真实 Agent 运行的命令。每个 run 必须由实际宿主执行并写入追加式结果，至少记录 correctness、hard discrepancy detection、false blocking、interventions、rework、wall time、token availability 和 failure/evidence refs。完成后更新 [实验报告](../research/experiment-report.md)，状态只有在 20 个真实 run 和统计结果写入后才能从 `not_run` 改变。

## 11. 最终结束标准

只有全部条件同时满足，才可以关闭 T18–T24 并宣布首发验收完成：

1. Codex、OpenCode、DeepSeek Harness 三个首发宿主各自 11 项 baseline 全部为 `supported`，每项都有脱敏 `evidence_refs`。
2. 三个首发宿主均有独立 session、恢复、重复/乱序事件和去重记录；ZCode 的缺失不阻塞本次首发。
3. `uv run python tools/dev/release_check.py` 返回 0，输出 `passed: true`、空 `failures` 和空 `missing_capabilities`。
4. 本地 pytest、Ruff、mypy、TypeScript、Vitest、协议校验和文档校验全部返回 0。
5. T24 保存 20 个真实 run、A/B/C/D 报告、另一宿主复验、至少一个三 Agent 协作记录和失败样本引用。
6. `.tsunagou/` 项目事实留在协调 Git 仓库中；秘密、原始会话 ID、完整转录和用户私有绝对路径不进入 Git。
7. 更新对应 `.trellis/tasks/.../implement.md`、`check.jsonl`、`task.json`、`docs/research/host-matrix.md`、`docs/research/experiment-report.md` 和 `.trellis/workspace/tyuikl32/journal-*.md`，让状态、证据路径和命令结果一致。

验收结束后关闭临时进程并确认没有遗留服务：

```powershell
Get-Process | Where-Object { $_.ProcessName -match "uvicorn|opencode|dsh|codex|zcode" }
Remove-Item -LiteralPath $acceptRoot -Recurse -Force
```

删除前必须确认需要长期保存的脱敏 evidence、实验结果和日志已经复制到仓库；任何含秘密的日志应先安全删除，不能为了保留“原始记录”提交它。
