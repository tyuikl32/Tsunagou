param([ValidateSet('main','worker')][string]$Role)
$ErrorActionPreference = 'Stop'
$work = 'D:\AB\git\AB\Tsunagou\.trellis\workspace\elysia080928\codex-live-verify-20260919'
$private = (Get-Content -LiteralPath (Join-Path $work 'private-root.pointer') -Raw).Trim()
$project = Join-Path $private 'project'
$prompt = "Isolated Tsunagou $Role acceptance seed. Reply SEED only. Do not call tools or modify files."
$log = Join-Path $private "$Role-seed.raw.jsonl"
& codex exec --json --ignore-user-config --skip-git-repo-check -s read-only -C $project $prompt *> $log
$code = $LASTEXITCODE
$events = Get-Content -LiteralPath $log | ForEach-Object { try { $_ | ConvertFrom-Json } catch {} }
$id = ($events | Where-Object { $_.type -eq 'thread.started' } | Select-Object -First 1).thread_id
if (-not $id) { throw 'seed_thread_missing' }
Set-Content -LiteralPath (Join-Path $private "$Role-thread.private") -Value $id
$digest = [Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData([System.Text.Encoding]::UTF8.GetBytes("conversation_id:$id"))).ToLowerInvariant()
[pscustomobject]@{ role = $Role; exit_code = $code; thread_digest = $digest; event_types = @($events | ForEach-Object { $_.type } | Select-Object -Unique) } | ConvertTo-Json -Compress
