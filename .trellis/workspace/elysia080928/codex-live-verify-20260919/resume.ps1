param([ValidateSet('main','worker')][string]$Role, [string]$LogName, [string]$Prompt)
$ErrorActionPreference = 'Stop'
$work = 'D:\AB\git\AB\Tsunagou\.trellis\workspace\elysia080928\codex-live-verify-20260919'
$private = (Get-Content -LiteralPath (Join-Path $work 'private-root.pointer') -Raw).Trim()
$port = (Get-Content -LiteralPath (Join-Path $private 'port.txt') -Raw).Trim()
$id = (Get-Content -LiteralPath (Join-Path $private "$Role-thread.private") -Raw).Trim()
$bridge = 'D:/AB/git/AB/Tsunagou/packages/bridge-server/dist/server.js'
$cfg = @(
  '-c', "mcp_servers.tsunagou.command='node'",
  '-c', "mcp_servers.tsunagou.args=['$bridge']",
  '-c', "mcp_servers.tsunagou.default_tools_approval_mode='approve'",
  '-c', "sandbox_mode='read-only'",
  '-c', "approval_policy='never'"
)
$vars = @{
  TSUNAGOU_HTTP_URL = "http://127.0.0.1:$port"
  TSUNAGOU_TICKET_FILE = Join-Path $private "$Role-ticket.private.json"
  TSUNAGOU_SESSION_FILE = Join-Path $private "$Role-session.private.json"
  TSUNAGOU_PROJECT_ROOT = Join-Path $private 'project'
  TSUNAGOU_STATE_DIR = Join-Path $private "$Role-bridge"
}
foreach ($key in $vars.Keys) { $cfg += @('-c', "mcp_servers.tsunagou.env.$key='$($vars[$key].Replace('\','/'))'") }
$log = Join-Path $private "$Role-$LogName.raw.jsonl"
& codex exec resume --json --ignore-user-config --skip-git-repo-check @cfg $id $Prompt *> $log
$code = $LASTEXITCODE
$events = Get-Content -LiteralPath $log | ForEach-Object { try { $_ | ConvertFrom-Json } catch {} }
$calls = @($events | Where-Object { $_.item.type -eq 'mcp_tool_call' } | ForEach-Object { [pscustomobject]@{ tool = $_.item.tool; status = $_.item.status } })
$sessionPath = Join-Path $private "$Role-session.private.json"
$session = if (Test-Path $sessionPath) { Get-Content -LiteralPath $sessionPath -Raw | ConvertFrom-Json } else { $null }
[pscustomobject]@{ role = $Role; log = $LogName; exit_code = $code; mcp_calls = $calls; baseline_status = if ($session) { $session.baseline_status } else { 'no_session' }; epoch = if ($session) { $session.connection_epoch } else { $null }; ticket_consumed = -not (Test-Path (Join-Path $private "$Role-ticket.private.json")) } | ConvertTo-Json -Depth 5 -Compress
