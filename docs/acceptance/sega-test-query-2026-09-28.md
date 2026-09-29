# 本轮测试数据的 PowerShell 查询

验证日期：2026-09-28。项目为 `D:\ALL.NET\SegaImageManageTool`，源码为 `D:\Tsunagou`。下面操作均为读取；在线查询要求现有 daemon 运行。

版本说明：编写本操作单时读取到的 `a3954ae` checkout 没有 project history/audit 查询命令，checkpoint list 也因未附带认证失败。后续规划开始时，当前 checkout 已更新到 `1fb86e0`，包含 PT 查询实现，`project history --help` 已重新验证可用。原问题属于当时读到的版本，不应继续描述为最新源码缺功能。下面 HTTP 命令仍可用于原始结果核对，第 7 节补充当前原生 CLI 入口；task list 仍不能凭空假设存在。

## 1. 设置查询目标

在任意目录打开 PowerShell，完整执行一次。Get-Tg 是本段定义的临时便捷函数，不是 Tsunagou 自带命令。控制凭据只读入变量，下面不会打印它。

```powershell
$tgRoot = 'D:\ALL.NET\SegaImageManageTool'
$tgState = Join-Path $tgRoot '.tsunagou\local'
$tgBase = (Get-Content (Join-Path $tgState 'endpoint.json') -Raw | ConvertFrom-Json).url.TrimEnd('/')
$tgProject = (Get-Content (Join-Path $tgRoot '.tsunagou\project.json') -Raw | ConvertFrom-Json).project_id
$tgHeaders = @{ Authorization = 'Bearer ' + (Get-Content (Join-Path $tgState 'control.token') -Raw).Trim() }
$tgPrefix = "/api/v1/projects/$tgProject"

function Get-Tg {
    param([string]$Path)
    Invoke-RestMethod -Uri "$tgBase$Path" -Headers $tgHeaders -TimeoutSec 10
}

Get-Tg '/api/v1/health'
```

端口从 endpoint.json 读取，不固定使用业务网页端口。daemon 重启或更换项目后重新执行本段。

## 2. 看任务、Worker 和执行状态

```powershell
# 任务列表与更新时间
(Get-Tg "$tgPrefix/tasks").items |
    Select-Object title, status, task_id, current_attempt_id, updated_at |
    Format-List

# Agent 身份与角色；active 不等于宿主正在生成新回合
(Get-Tg "$tgPrefix/agents").items |
    Format-Table agent_id, role, status -AutoSize

# 所有执行尝试，以及它们的执行者
$attempts = @((Get-Tg "$tgPrefix/attempts").items)
$attempts | Format-Table task_id, attempt_id, owner_agent_id, status -AutoSize
$attempts | Group-Object status | Format-Table Name, Count -AutoSize

# 只看失去执行资格的尝试
$attempts | Where-Object status -eq 'orphaned' | Format-List
```

验证时结果：2 个 completed Attempt，9 个 orphaned；两个交付任务 completed，主任务 open，两个旧任务 cancel_requested。后续状态可能继续改变。

## 3. 看租约、消息、契约及唤醒

```powershell
(Get-Tg "$tgPrefix/resources").items |
    Format-Table lease_set_id, attempt_id, status, expires_at -AutoSize

(Get-Tg "$tgPrefix/messages").items |
    Sort-Object created_at |
    Select-Object created_at, sender_agent_id, recipient_agent_id, kind, summary |
    Format-List

(Get-Tg "$tgPrefix/contracts").items | Format-List

# 本轮实际测试的宿主唤醒
(Get-Tg '/api/v1/host-wake/attempts/wake:369a92b4-659b-423a-b2e3-b1a5e46f70a6').attempt |
    Select-Object state, error_code, error_message, updated_at, evidence |
    Format-List

# 唤醒及呈现诊断时间线
(Get-Tg "$tgPrefix/diagnostics").items |
    Select-Object observed_at, kind, agent_id, message_id, wake_attempt_id |
    Format-List
```

messages 是服务公开的脱敏摘要，不等于私人收件箱全文或完整 ACK 状态。唤醒验证时返回 failed / desktop_thread_unavailable；agent_presented 不能单独证明自动唤醒成功。

## 4. 获取完整可见审计记录，避免只读第一页

```powershell
$audit = @()
$cursor = $null
$seenCursors = [System.Collections.Generic.HashSet[string]]::new()
do {
    $path = "$tgPrefix/audit?limit=100"
    if ($cursor) { $path += '&cursor=' + [uri]::EscapeDataString($cursor) }
    $page = Get-Tg $path
    $audit += @($page.items)
    $cursor = $page.next_cursor
    if ($cursor -and -not $seenCursors.Add([string]$cursor)) {
        throw '审计分页返回重复 cursor，已停止。'
    }
} while ($cursor)

# 谁在什么时候执行了什么，结果及理由是什么
$audit | Select-Object event_seq, occurred_at, actor_ref, action, outcome, reason_code |
    Format-Table -AutoSize

# 复核本轮报告中的次数
$audit | Where-Object {
    $_.action -in @('task.claim', 'workspace.select', 'resource.lease.expired', 'task.submit')
} | Group-Object action | Format-Table Name, Count -AutoSize

# 查看最近 20 条及完整细节
$audit | Sort-Object event_seq | Select-Object -Last 20 | Format-List
```

验证时分页共返回 318 条可见记录，snapshot_event_seq 为 405；数据库有 405 个事件。公共审计按可见性过滤，不是原始事件表的完整复制，因此条数不同不能直接判断丢失。分页实测统计：task.claim 11、workspace.select 11、resource.lease.expired 12、task.submit 2。

## 5. 查指定任务时间线与耗时

先运行上节获取完整 `$audit`。WebUI 和 HTTP 的交付任务 ID 已填好：

```powershell
$webTask = '0a28f9e6-52c8-4d80-b805-64807da75931'
$httpTask = 'ab418fd1-b3a8-48a9-9ac2-f595cd833f14'

foreach ($taskId in @($webTask, $httpTask)) {
    $taskEvents = @($audit | Where-Object subject_ref -eq "task/$taskId" | Sort-Object event_seq)
    $taskEvents | Where-Object {
        $_.action -in @('task.start', 'task.submit', 'task.review.accept')
    } | Select-Object event_seq, occurred_at, action, subject_ref | Format-Table -AutoSize

    $start = $taskEvents | Where-Object action -eq 'task.start' | Select-Object -First 1
    $submit = $taskEvents | Where-Object action -eq 'task.submit' | Select-Object -Last 1
    $review = $taskEvents | Where-Object action -eq 'task.review.accept' | Select-Object -Last 1
    if ($start -and $submit) {
        [pscustomobject]@{
            Task = $taskId
            StartToSubmit = ([datetimeoffset]$submit.occurred_at - [datetimeoffset]$start.occurred_at).ToString()
            SubmitToReview = if ($review) {
                ([datetimeoffset]$review.occurred_at - [datetimeoffset]$submit.occurred_at).ToString()
            } else { '尚未审查' }
        } | Format-List
    }
}
```

JSON 时间戳使用 UTC（Z）；不同 PowerShell 版本可能自动解析为日期并改变显示格式。流程耗时包含等待和恢复，不能当作纯编码耗时。

## 6. 看 checkpoint 与导出

```powershell
Get-Tg '/api/v1/checkpoints' | ConvertTo-Json -Depth 15

# 把本次读取的审计另存到一个新的用户目录文件；不修改业务状态
$auditExport = Join-Path $env:TEMP ('tsunagou-audit-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.json')
ConvertTo-Json -InputObject @($audit) -Depth 30 |
    Set-Content -LiteralPath $auditExport -Encoding utf8
$auditExport
```

验证时只有 genesis checkpoint，through_event_seq=1；这不表示后续事件没有入数据库，也不是项目完成快照。

## 7. 已验证可用的原生 CLI 查询

当前安装已有 Python 虚拟环境，可直接调用，避免切到业务目录后找不到包：

```powershell
$env:TSUNAGOU_PROJECT_ROOT = $tgRoot
$env:TSUNAGOU_STATE_DIR = $tgState
$env:TSUNAGOU_DAEMON_URL = $tgBase
$env:TSUNAGOU_CONTROL_TOKEN = (Get-Content (Join-Path $tgState 'control.token') -Raw).Trim()
$tgPython = 'D:\Tsunagou\.venv\Scripts\python.exe'

& $tgPython -m tsunagou --help
& $tgPython -m tsunagou --json daemon status --coordination-root $tgRoot
& $tgPython -m tsunagou --json host wake-status 'wake:369a92b4-659b-423a-b2e3-b1a5e46f70a6'

# 1fb86e0 已包含的查询入口；history 每次返回一页
& $tgPython -m tsunagou project history $tgProject --limit 200
& $tgPython -m tsunagou project diagnostics $tgProject --json
& $tgPython -m tsunagou checkpoint list
```

这些变量仅在当前 PowerShell 进程及其子进程生效。此处不运行 connect/enroll、recover、retry 或 complete：查询已有数据不需要创建身份、恢复任务或确认项目完成。

## 8. daemon 不在运行时，读本轮已保存的复盘快照

```powershell
$saved = Get-Content 'D:\Tsunagou\docs\acceptance\sega-test-retrospective-2026-09-28.json' -Raw | ConvertFrom-Json
$saved.recorded_at_utc
$saved.event_counts | Format-List
$saved.task_records |
    Format-Table task_id, status, start_to_submit_seconds, submit_to_review_seconds -AutoSize
$saved.wake_attempts | ConvertTo-Json -Depth 15
```

这是复盘记录时的快照，不是实时查询。[复盘总结](sega-test-retrospective-2026-09-28.md)说明统计口径、证据缺口和修复优先级。
