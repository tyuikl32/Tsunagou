$ErrorActionPreference = 'Stop'
$repo = 'D:\AB\git\AB\Tsunagou'
$work = Join-Path $repo '.trellis\workspace\elysia080928\codex-live-verify-20260919'
$private = Join-Path $env:TEMP ('tsunagou-codex-verify-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $private, (Join-Path $private 'state'), (Join-Path $private 'project') | Out-Null
Set-Content -LiteralPath (Join-Path $work 'private-root.pointer') -Value $private
$control = [Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
Set-Content -LiteralPath (Join-Path $private 'control.private') -Value $control
$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
$listener.Start()
$port = $listener.LocalEndpoint.Port
$listener.Stop()
Set-Content -LiteralPath (Join-Path $private 'port.txt') -Value $port
$env:TSUNAGOU_CONTROL_TOKEN = $control
$env:TSUNAGOU_STATE_DIR = Join-Path $private 'state'
$python = Join-Path $repo '.venv\Scripts\python.exe'
$server = Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','tsunagou.bootstrap.container:build_application','--factory','--host','127.0.0.1','--port',"$port") -WorkingDirectory $repo -WindowStyle Hidden -RedirectStandardOutput (Join-Path $private 'http.stdout.log') -RedirectStandardError (Join-Path $private 'http.stderr.log') -PassThru
Remove-Item Env:TSUNAGOU_CONTROL_TOKEN,Env:TSUNAGOU_STATE_DIR
Set-Content -LiteralPath (Join-Path $private 'server-pid.txt') -Value $server.Id
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
  try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/v1/health" -TimeoutSec 2
    if ($health.status -eq 'ok') { $ok = $true; break }
  } catch { Start-Sleep -Milliseconds 300 }
}
if (-not $ok) { throw 'isolated_server_health_failed' }
[pscustomobject]@{ health = $health.status; version = $health.version; port = $port; pid = $server.Id } | ConvertTo-Json -Compress
