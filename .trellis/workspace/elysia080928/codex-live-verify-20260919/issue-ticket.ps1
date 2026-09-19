param([ValidateSet('main','worker')][string]$Role)
$ErrorActionPreference = 'Stop'
$work = 'D:\AB\git\AB\Tsunagou\.trellis\workspace\elysia080928\codex-live-verify-20260919'
$private = (Get-Content -LiteralPath (Join-Path $work 'private-root.pointer') -Raw).Trim()
$port = (Get-Content -LiteralPath (Join-Path $private 'port.txt') -Raw).Trim()
$control = (Get-Content -LiteralPath (Join-Path $private 'control.private') -Raw).Trim()
$id = (Get-Content -LiteralPath (Join-Path $private "$Role-thread.private") -Raw).Trim()
$installation = "codex-verify-$Role"
$envelope = @{
  command_id = [guid]::NewGuid().ToString()
  protocol_version = '1.0'
  schema_bundle_digest = 'sha256:dfda63da8594b8a2e02d080ef33dd17a8259b74900cc69e3b605b5068e95b122'
  payload = @{ installation_id = $installation; conversation_evidence = @{ conversation_id = $id }; ttl_seconds = 600 }
}
$reply = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$port/api/v1/commands/agent.ticket.create.user" -Headers @{ Authorization = "Bearer $control" } -ContentType 'application/json' -Body ($envelope | ConvertTo-Json -Depth 10 -Compress)
if (-not $reply.result.secret) { throw 'ticket_missing_secret' }
@{ installation_id = $installation; conversation_id = $id; secret = $reply.result.secret } | ConvertTo-Json -Compress | Set-Content -LiteralPath (Join-Path $private "$Role-ticket.private.json")
[pscustomobject]@{ role = $Role; http_status = 200; ticket_created = $true } | ConvertTo-Json -Compress
