# 独立成品启动与详细调试执行单

日期：2026-09-21。PowerShell，源码目录`D:\Tsunagou`。

**A部分是当前可运行验证，B部分是故障注入和真实宿主验收流程。** 当前 daemon、CLI、SQLite、双 bridge 首轮协作、用户确认、checkpoint、过期 Job lease 机械恢复、重启恢复和真实 daemon commit 窗口 smoke 已通过；B 部分中尚未装配的主动后台 Job/物化中断和真实宿主步骤仍必须保持“待实现”标记。全过程只对新建临时 Git 项目执行，不在用户实际业务仓库中注入故障。

## A1. 先确认环境和已有测试

```powershell
Set-Location D:\Tsunagou
$ErrorActionPreference = 'Stop'
uv sync --locked --extra dev
if ($LASTEXITCODE -ne 0) { throw 'Python environment setup failed' }
$py = (Resolve-Path .venv\Scripts\python.exe).Path
& $py --version
git status --short
& $py -m pytest
if ($LASTEXITCODE -ne 0) { throw 'Existing Python tests failed' }
corepack pnpm install --frozen-lockfile
if ($LASTEXITCODE -ne 0) { throw 'Node installation failed' }
corepack pnpm exec vitest run
if ($LASTEXITCODE -ne 0) { throw 'Existing TypeScript tests failed' }
```

本轮实测 Python 3.13.13、110 个 Python 测试与 29 个 TS 测试通过。精确依赖由当前锁文件决定，不手工换较新版本绕过安装错误。测试通过不表示完整 M1 协作闭环已经解决。

## A2. 一条命令复现真实运行缺口

```powershell
Set-Location D:\Tsunagou
$reportPath = Join-Path $env:TEMP ('tsunagou-audit-' + [guid]::NewGuid().ToString('N') + '.json')
.\.venv\Scripts\python.exe tools/dev/audit_standalone.py --output $reportPath
$auditExit = $LASTEXITCODE
$report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
$report.checks | Format-Table check, passed, observed -AutoSize
Write-Output ('Audit exit: ' + $auditExit)
Write-Output ('Report: ' + $reportPath)
```

当前结束标准：报告16项检查全部通过，退出0。未来新增检查后失败数量可变化，不能把旧的16项当作完整 M1 测试。退出1表示产品断言失败；退出2是脚本或启动环境出错，需看最后完成的检查。

脚本实际做了：初始化一次性Git目录和项目；启动uvicorn；用HTTP建立两个本机测试身份；创建/claim/start/block/resume任务；创建契约与消息；kill/restart同项目daemon；验证CLI签票能否被运行中的daemon识别。每次调用都通过真实HTTP，不从脚本直接修改TaskService状态。

接入请求中的fixture仅让后端可被测试，不代表真实Agent。临时token只用于该子进程，结果JSON不记录秘密，结束后删除临时项目和停掉所有自建进程。此脚本针对当前扁平API的缺陷定位；R1改正式协议后应改用B部分的成品测试，不把脚本不兼容算产品失败。

## A3. 当前daemon怎样单独启动

首选使用真实 CLI 管理常驻进程。CLI 会在协调仓库的 `.tsunagou/local/` 写入非秘密 `endpoint.json`、私有 `control.token`、SQLite 和日志；后续命令只需设置 `TSUNAGOU_PROJECT_ROOT`，不需要复制 token 到命令行。

```powershell
Set-Location D:\Tsunagou
$env:PYTHONPATH = 'src'
$cli = (Resolve-Path .venv\Scripts\tsunagou.exe).Path
$testRoot = Join-Path $env:TEMP ('tsunagou-manual-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
git init --quiet $testRoot
& $cli daemon start --coordination-root $testRoot --name LocalTest --objective 'Run a local coordination test'
if ($LASTEXITCODE -ne 0) { throw 'daemon start failed' }
$env:TSUNAGOU_PROJECT_ROOT = $testRoot
& $cli doctor
& $cli daemon status --coordination-root $testRoot
& $cli agent enroll --adapter codex --installation-id manual-worker --conversation-id manual-conversation
```

结束时：

```powershell
& $cli daemon stop --coordination-root $testRoot
Remove-Item Env:TSUNAGOU_PROJECT_ROOT -ErrorAction SilentlyContinue
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
```

期望：`doctor` 报 reachable，`agent enroll` 报 ticket_issued；票据内容只写入临时私有文件，不出现在标准输出。下面的旧手工 uvicorn 段落仅用于诊断 daemon 启动失败时的日志，不是正常用户入口。

以下建立一个可观察的临时项目并在后台启动当前程序。它验证底层 HTTP 入口，不覆盖尚未装配的完整协作步骤。

```powershell
Set-Location D:\Tsunagou
$py = (Resolve-Path .venv\Scripts\python.exe).Path
$testRoot = Join-Path $env:TEMP ('tsunagou-manual-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
git init --quiet $testRoot
if ($LASTEXITCODE -ne 0) { throw 'git init failed' }

$projectResult = & $py -m tsunagou project init --coordination-root $testRoot --name LocalTest --objective 'Run a local coordination test'
if ($LASTEXITCODE -ne 0) { throw 'project init failed' }
$projectId = ($projectResult | ConvertFrom-Json).project_id

$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
$listener.Start()
$testPort = $listener.LocalEndpoint.Port
$listener.Stop()
$endpoint = 'http://127.0.0.1:' + $testPort

# These environment keys are the current prototype's actual configuration.
# Do not print the control token or add it to a request payload or shell command.
$env:TSUNAGOU_CONTROL_TOKEN = & $py -c 'import secrets; print(secrets.token_urlsafe(32))'
$env:TSUNAGOU_PROJECT_ROOT = $testRoot
$env:TSUNAGOU_STATE_DIR = Join-Path $testRoot '.tsunagou\local'
Remove-Item Env:TSUNAGOU_PROJECT_ID -ErrorAction SilentlyContinue
$stdoutLog = Join-Path $testRoot 'server.out.log'
$stderrLog = Join-Path $testRoot 'server.err.log'
$server = Start-Process -FilePath $py -ArgumentList @(
  '-m', 'uvicorn', 'tsunagou.bootstrap.container:build_application',
  '--factory', '--host', '127.0.0.1', '--port', "$testPort", '--no-access-log'
) -WorkingDirectory D:\Tsunagou -PassThru -WindowStyle Hidden `
  -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog

$healthy = $false
for ($attempt = 0; $attempt -lt 50; $attempt++) {
  if ($server.HasExited) { break }
  try {
    $health = Invoke-RestMethod -Uri "$endpoint/api/v1/health" -TimeoutSec 2
    $healthy = $health.status -eq 'ok'
    if ($healthy) { break }
  } catch { Start-Sleep -Milliseconds 200 }
}
if (-not $healthy) {
  if (-not $server.HasExited) { Stop-Process -Id $server.Id }
  Get-Content -LiteralPath $stderrLog -Tail 30
  throw 'Server did not start; inspect the log before continuing'
}
Write-Output "Endpoint: $endpoint"
Write-Output "Project ID: $projectId"
Write-Output "Disposable project: $testRoot"
$health
```

如提示端口被占用，重新选择空闲端口并启动，不停止不属于本步骤的服务。不要同时启动两个 daemon 加载同一项目；项目 runtime lock 会拒绝第二个 writer。

当前可验证：health为ok、`.tsunagou/project.json`存在、`.tsunagou/local/state.sqlite3`建立。它不会把未接通命令变为可用。

查看当前真实路由：

```powershell
$openapi = Invoke-RestMethod -Uri "$endpoint/openapi.json"
$openapi.paths.PSObject.Properties.Name
```

当前业务路径包括`/api/v1/health`、`/api/v1/commands/{command_kind}`、项目任务/agents/contracts/messages 查询、decisions、operations 和 recovery。协议 registry 中尚未装配的 command 仍会明确报错；OpenAPI文件出现在仓库中不等于每个领域动作都已注册。

## A4. 验证两个不需要Agent的边界

### CLI决定命令必须失败而不能伪成功

```powershell
& $py -m tsunagou decision resolve not-a-real-decision --choice approve --expected-revision 1 --digest sha256:not-real
Write-Output ('Exit: ' + $LASTEXITCODE)
```

当前应输出对象不存在或未接通错误并返回非零退出；它不能打印 submitted。不要用不存在的 ID 作为真实用户确认。

### 任务列表必须走同一daemon

```powershell
try {
  Invoke-RestMethod -Uri "$endpoint/api/v1/projects/$projectId/tasks" `
    -Headers @{ Authorization = "Bearer $env:TSUNAGOU_CONTROL_TOKEN" }
} catch {
  Write-Output $_.Exception.Message
}
```

当前返回认证后的 TaskPage；空项目返回`items=[]`，已创建任务必须出现在同一 daemon 的列表中。若返回404，先检查 endpoint/project root 是否指向同一项目。

## A5. wheel离开源码目录的复现

这一段不会修改原项目安装，仅在临时目录安装 wheel 内容，并使用现有 venv 依赖。它验证包内资源；完整无源码的新 venv 交付测试在 B 部分。

```powershell
Set-Location D:\Tsunagou
$py = (Resolve-Path .venv\Scripts\python.exe).Path
$wheelRoot = Join-Path $env:TEMP ('tsunagou-wheel-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $wheelRoot | Out-Null
uv build --wheel --out-dir $wheelRoot
if ($LASTEXITCODE -ne 0) { throw 'wheel build failed' }
$wheel = Get-ChildItem -LiteralPath $wheelRoot -Filter '*.whl' | Select-Object -First 1
$installedSite = Join-Path $wheelRoot 'site'
uv pip install --python $py --no-deps --target $installedSite $wheel.FullName
if ($LASTEXITCODE -ne 0) { throw 'wheel installation failed' }
Push-Location $wheelRoot
try {
  & $py -c 'import sys; sys.path.insert(0, sys.argv[1]); from tsunagou.bootstrap.container import build_application; build_application()' $installedSite
  Write-Output ('Installed application exit: ' + $LASTEXITCODE)
} finally { Pop-Location }
```

当前应退出0并打印 wheel 内的 `protocol_data/registry/commands.json` 路径；若出现 FileNotFoundError，说明 R1/R6 回归失败，不能只把源码的 protocol 目录手动复制到运行目录当作修复。

## A6. 结束手工调试

仍在A3的同一PowerShell会话里：

```powershell
if ($null -ne $server -and -not $server.HasExited) {
  Stop-Process -Id $server.Id
  $server.WaitForExit()
}
Remove-Item Env:TSUNAGOU_CONTROL_TOKEN -ErrorAction SilentlyContinue
Remove-Item Env:TSUNAGOU_STATE_DIR -ErrorAction SilentlyContinue
Remove-Item Env:TSUNAGOU_PROJECT_ROOT -ErrorAction SilentlyContinue
```

保留临时目录便于看日志；含本机身份数据，不作为共享材料提交。不要执行全机器`Stop-Process python`，也不要递归删除推导不明的路径。

## B1. R1–R6交付后必须能执行的操作

**以下是待实现的成品命令和测试签名，不是当前可用承诺。** 原有CLI形式沿用实施目录；新增仅是进程参数、非秘密配置输出与测试工具参数，不添加用户领域权限。

R6必须提供的安装产物：Python wheel、可执行stdio bridge目录或npm包、锁文件、Windows安装/启动脚本。正常安装不得要求源码checkout、editable install、手工改JSON或共享Agent token。

隔离安装检查：

```powershell
Set-Location D:\Tsunagou
$packageRoot = Join-Path $env:TEMP ('tsunagou-package-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $packageRoot | Out-Null
uv build --wheel --out-dir $packageRoot
if ($LASTEXITCODE -ne 0) { throw 'build failed' }
$wheel = Get-ChildItem -LiteralPath $packageRoot -Filter '*.whl' | Select-Object -First 1
uv venv --python 3.13 (Join-Path $packageRoot 'venv')
$installedPython = Join-Path $packageRoot 'venv\Scripts\python.exe'
uv pip install --python $installedPython $wheel.FullName
if ($LASTEXITCODE -ne 0) { throw 'install failed' }
Push-Location $packageRoot
& $installedPython -m tsunagou --version
& $installedPython -m tsunagou daemon --help
Pop-Location
```

停止条件：缺协议资源、源码外启动失败、daemon子命令不存在、help宣称存在但命令只打印固定状态，均不算交付。

## B2. 用户启动与项目初始化

终端1，使用安装后的可执行文件：

```powershell
# R2/R6 add --foreground as a process-management option.
tsunagou daemon start --foreground
```

成功：daemon绑定空闲loopback端口并写非秘密endpoint manifest，显示运行实例。control credential放用户私有目录。终端2：

```powershell
tsunagou daemon status
$demoRoot = Join-Path $env:TEMP ('tsunagou-demo-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $demoRoot | Out-Null
git init --quiet $demoRoot
$created = tsunagou --json project init --coordination-root $demoRoot --name Demo --objective 'Two agents agree on an API and deliver a tested implementation' | ConvertFrom-Json
$demoId = $created.result.project_id
tsunagou --project $demoId --json project show
tsunagou --project $demoId --json task list
```

CLI统一返回协议CommandResult；`project init`输出的project_id位于`result`，这是目标协议形式，与A部分旧输出不同。查询返回对应DTO，不套mutation envelope。

成功：project active、task list空、项目内SQLite已建立并有genesis事实；停止daemon再查询必须报连接失败，不能继续返回假空列表。

## B3. 用户怎样使两个Agent加入

R5扩展现有enroll的本机参数：`--output-dir <path>`生成非秘密MCP启动配置；`--mode attach`仍使用原语义。CLI内部向daemon申请票据和本机会话绑定，通过私有路径交给bridge，不让用户填host conversation ID。尚未实现时必须直接标明缺失，不能退回让用户手写probe。

```powershell
$attachRoot = Join-Path $env:TEMP ('tsunagou-attach-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $attachRoot | Out-Null
tsunagou --project $demoId agent enroll --adapter codex --mode attach --output-dir (Join-Path $attachRoot 'main')
tsunagou --project $demoId agent enroll --adapter codex --mode attach --output-dir (Join-Path $attachRoot 'worker')
```

输出为各自启动描述/配置位置和等待接入状态；此时只是等待bridge兑换，不能输出已经connected。适配器的本机配置生成器必须输出实际的可执行路径，不写假设机器上存在的`node dist/server.js`相对路径。

人工操作：

1. 在IDE/Harness打开两个独立会话，工作目录均为`$demoRoot`。同目录不等于同身份。
2. 分别把main/worker生成的MCP启动配置加载到对应会话。只允许非秘密启动描述路径进入宿主配置，token和票据不得进入模型上下文。
3. 让两个会话分别调用项目查询工具。daemon记录两个不同的agent_id/session_id；主机没有运行MCP子进程就不能假定已加入。
4. 用户从CLI查看接入身份并选定主Agent。身份ID从查询结果取得，不由模型编造。

```powershell
tsunagou --project $demoId --json agent list
tsunagou --project $demoId --json authority show
```

R5必须输出非秘密`enrollment.json`接入回执，至少包含`project_id/agent_id/session_id/status`，分别位于两个output目录。用户通过现有任命入口执行：

```powershell
$mainReceipt = Get-Content (Join-Path $attachRoot 'main\enrollment.json') -Raw | ConvertFrom-Json
$mainId = $mainReceipt.agent_id
# R5 must create this non-secret request file from the ceiling chosen at init
# and the current authority view. It cannot silently approve a changed version.
$appointmentFile = Join-Path $attachRoot 'main\appointment-request.json'
$authority = tsunagou --project $demoId --json authority show | ConvertFrom-Json
tsunagou --project $demoId authority appoint $mainId --request-file $appointmentFile --expected-revision $authority.revision
```

`appointment-request.json`由接入向导准备，包含expected_authority_epoch/ceiling_template/reason；用户执行任命前可阅读它。期间authority改变必须412并重新展示，CLI不自动取最新批准。

结束标准：一个main、一个worker；worker试图任命main或操作main-owned任务被403拒绝。没有宿主能力证据填报步骤。

## B4. 两个Agent实际完成一个文件任务

对主Agent给出一次业务任务：

```text
在当前项目创建一个纯 Python 模块 demo_api.py。
目标函数 normalize_user 接受字典并返回规范化用户记录，输入原样保留。
你负责协调、审查与 Git，worker 负责实现和测试。
先与 worker 通过 Tsunagou 报告并协商返回字段究竟为 user_id 还是 id，
明确未知字段处理规则，双方接受同一契约后再开始文件任务。
请显式选择 shared 工作空间。提交结果时引用实际 patch 与测试结果。
普通任务完成由指定审查者确认；项目整体完成提案留给我用用户 CLI 确认。
```

对worker只需说明加入项目并从黑板读取分配，不转发主Agent token。主Agent负责用typed tools创建draft、ready/publish、设置scope/验收者，并通过message发送task ref；worker自己claim。

运行中检查：

```powershell
tsunagou --project $demoId --json task list
tsunagou --project $demoId --json decision list
```

服务端必须可查询并验证的顺序：

| 检查点 | 预期事实 |
|---|---|
| 创建 | draft；无Attempt、无执行Grant |
| 发布/认领 | open→claimed；唯一worker owner |
| 不同字段理解 | 两份report、可见分歧、受影响action blocker |
| 共同接受 | 同一proposal digest、所有required slots接受 |
| 准备 | shared真实baseline、scope内Lease、有效preflight |
| 启动 | 同事务Task/Attempt running、执行Grant |
| 实际文件任务 | demo_api.py和测试文件存在，测试子进程退出0 |
| 提交 | workspace result/patch/validation引用，Task submitted；执行Grant/Lease释放 |
| 审查 | 指定reviewer接受，Task completed；Project仍active |

如果Agent跳过系统直接修改文件，文件有了也不算闭环通过。可以由main组织补救，但运行记录必须注明。判断写代码是否正确由main和实际测试完成，daemon不替LLM审查业务含义。

## B5. 用户决定与项目完成

若主Agent认为设计方向改变，需要提出UserDecision。用户读取精确对象：

```powershell
$decisions = tsunagou --project $demoId --json decision list | ConvertFrom-Json
$decisionId = ($decisions.items | Where-Object status -eq 'pending' | Select-Object -First 1).id
if (-not $decisionId) { throw 'No pending decision; do not invent an ID' }
$decision = tsunagou --project $demoId --json decision show $decisionId | ConvertFrom-Json
$decision
```

阅读后按该决定`choices`中的真实值填写；以下选择approved只用于该选项确实存在时：

```powershell
tsunagou --project $demoId decision resolve $decisionId --choice approved --expected-revision $decision.revision --digest $decision.proposal_digest --reason 'Reviewed the proposed change'
```

成功只表示决定已解决，相关worker仍须resume/preflight/start；它不自动代表项目完成。

项目完成由主Agent生成已登记的CompletionProposal，用户调用独立 `project complete`。R5向用户输出可审阅的非秘密提案：proposal_id、proposal revision、proposal_digest 和 expected_project_revision；提案变化需重审。

```powershell
# These values must come from the same reviewed completion proposal.
$proposal = Get-Content (Join-Path $demoRoot 'completion-proposal-view.json') -Raw | ConvertFrom-Json
$proposalId = $proposal.proposal_id
tsunagou --project $demoId project complete $proposalId --expected-project-revision $proposal.expected_project_revision --digest $proposal.proposal_digest
tsunagou --project $demoId --json project show
tsunagou --project $demoId --json operation list
tsunagou --project $demoId --json checkpoint list
```

这些文件是主Agent/查询客户端输出的非秘密审阅材料，不是信任凭据；服务器必须重新验摘要、revision及U权限。确认成功后Project completed；checkpoint物化失败只显示错误，不撤销完成事实。

## B6. 重启和反例调试矩阵

R6 的主动 Job runner 中断仍需补齐；checkpoint 物化失败/查询/CLI retry 已由真实 daemon smoke 覆盖，过期 Job lease 的机械回收已有维护线程和公共 jobs 查询。提交窗口的真实 daemon 进程退出已经可以用以下命令执行；其余矩阵仍不能用不存在的测试路径代替：

```powershell
\.venv\Scripts\python.exe tools/dev/smoke_standalone.py
\.venv\Scripts\python.exe tools/dev/commit_window_process_smoke.py
```

`smoke_standalone.py`自己创建临时项目和main/worker bridge，使用同CLI签票路径；测试动作走MCP/HTTP，随后通过CLI完成用户决定、项目确认、checkpoint 查询和 daemon 重启恢复。`commit_window_process_smoke.py`启动两个独立临时 daemon，分别在 SQLite commit 前和 HTTP 响应前退出，再重启并重放同一 `command_id`。两个脚本都只输出非秘密摘要，失败退出1，全部通过才退出0；清理仅限自建进程和临时目录。完整故障注入场景仍按下表逐项实现和记录，不能用本 smoke 替代它们。

| 场景/测试名 | 操作 | 明确断言 | 优先检查 |
|---|---|---|---|
| test_restart_preserves_facts | 创建任务/报告/契约/消息→kill→重启 | 对象ID和值保留；执行权失效待准备 | container/repositories/recovery |
| test_duplicate_command | 同主体同ID同输入发两遍 | 同task_id/result，replayed=true；一组事件 | dispatcher/commands表 |
| test_idempotency_conflict | 同ID改payload | 409，第二次无写入 | canonical hash/目标映射 |
| test_foreign_owner_denied | worker B对A任务block/resume/submit | 403，owner/status/revision不变 | Task端口关系校验 |
| test_failed_start_atomic | 已claim任务传错Attempt | 4xx，Task仍claimed，无Grant/Lease副作用 | workflow/UoW |
| test_changed_preflight | preflight后改变契约/范围/基线 | start拒绝，返回精确blocker | 输入revision/digest |
| test_atomic_claim | 两会话并发claim同一open task | 一成功一冲突，一条当前Attempt | SQLite约束/writer |
| test_lease_expiry | 禁用测试bridge续租，推动注入时钟 | expired+orphaned+撤Grant同事务 | expiry Job/任务编排 |
| test_long_user_wait | 保留pending并推动时钟 | pending不失效，相关blocked，无关继续 | UserDecision/blocker范围 |
| test_message_restart_and_ack | 发送→重启→fetch→presented→ACK | 一条delivery；ACK不满足业务义务 | messages/delivery/obligation |
| test_manual_file_edit | baseline后在临时scope改文件 | 下一检查点观察变化，无回滚，无自动判定作者 | workspace scanner/manifest |
| test_commit_crash_windows | `commit_window_process_smoke.py` 在真实 daemon 中提交前/后退出 | 前者无半写；后者重放原结果 | SQLite commit/idempotency |
| test_checkpoint_failure | 物化rename前注入失败 | 旧checkpoint可读；Operation失败；completed保留 | staging/Job/水位 |
| test_single_writer | 同项目启动第二daemon | 明确失败；首个服务和DB仍正常 | 项目OS锁 |
| test_old_session_epoch | 重连后旧token/epoch写入 | 401/409，无旧授权复活 | session/runtime fencing |
| test_installed_package | 无源码目录的新venv启动并执行场景 | 无FileNotFoundError，不导入源码 | wheel resources/entrypoint |

不使用等待用户几十分钟的测试；pending语义使用可注入时钟验证。测试续租失效用测试fixture/注入clock，不向生产增加任意“跳过权限”开关。

## B7. 断点和数据库查错方法

| 症状 | 顺序检查 | 最关键的断点 |
|---|---|---|
| HTTP200但查不到任务 | 确认project_id→handler→UoW→commit→同项目query | dispatcher，tasks repository insert，UnitOfWork commit |
| 相同ID重试产生两任务 | normalized目标与principal→commands表键→是否共用事务 | ProjectDatabase.dispatch，handler入口 |
| CLI结果和MCP不同 | endpoint instance→project→调用路径→是否CLI new app | cli/client，bootstrap装配 |
| start前检查有效但运行缺资源 | preflight evidence→start重读→Lease过期→workspace revision | TaskExecutionWorkflow.start |
| 重启后消息在但任务没了 | 是否仍用内存TaskService；SQLite表和恢复入口 | container/runtime.startup |
| 项目completed但没有checkpoint | completion事务有无Operation/outbox→Job状态→staging | completion workflow，Job runner，CheckpointStore |
| 子Agent影响主Agent任务 | 主体来自哪里→task.current_attempt owner→scope/Grant | authenticator，tasks public.handle |
| 修改文件后无反应 | 是否已到扫描检查点→baseline/diff→观察事件 | workspace prepare/result；不要寻找尚未实现的watcher |

优先通过CLI和HTTP查询。必须检查数据库时用只读连接，不能用SQL修业务状态：

```powershell
$stateDb = Join-Path $demoRoot '.tsunagou\local\state.sqlite3'
if (-not (Test-Path -LiteralPath $stateDb)) { throw 'No project database was created' }
@'
import sqlite3
import sys
from pathlib import Path

uri = Path(sys.argv[1]).resolve().as_uri() + "?mode=ro"
with sqlite3.connect(uri, uri=True) as db:
    print("integrity:", db.execute("PRAGMA integrity_check").fetchone()[0])
    print("foreign_key_violations:", len(db.execute("PRAGMA foreign_key_check").fetchall()))
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        print(name)
'@ | uv run python - $stateDb
```

不在日志里dump整张session/ticket/private message表。需要跨请求定位时只记录command_id、task_id、attempt_id、事件seq和错误code。人工排错不应新增控制权限或改owner以让测试通过。

## B8. 最终结束标准

- 安装在源码树外的成品能用CLI启停，不能依赖开发目录。
- 用户能让main和worker真正加入，完成B4真实文件任务和审查，并独立确认项目完成。
- A部分与 B6 中已实现的提交窗口、checkpoint 失败重试、旧 epoch、越权和安装检查均通过，kill/restart后仍可继续；B6 标为待实现的完整 Job runner/宿主矩阵属于 R1-R6 follow-on。最小成品测试不要求补填任何宿主能力报告。
- 项目数据留在协调仓库`.tsunagou/`，秘密/本机数据留local，shared checkpoint可校验。
- 本文每个标为成品的命令已实际执行；未实现命令不继续显示成功。
- 最终报告分别列出已完成M1功能、仍属M2/M3的原设计范围，以及真实缺陷。只有文档和测试清单落盘不算产品完成。
