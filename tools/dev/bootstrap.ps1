param([switch]$SkipNode)
$ErrorActionPreference = 'Stop'
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '../..')
Push-Location $repoRoot
try {
    uv sync --locked
    if ($LASTEXITCODE -ne 0) { throw 'uv sync failed' }
    if (-not $SkipNode) {
        npx --yes pnpm@12.4.2 install --frozen-lockfile
        if ($LASTEXITCODE -ne 0) { throw 'pnpm install failed' }
    }
    uv run --locked python -c "from tsunagou.bootstrap.container import build_application; print(build_application().title)"
    if ($LASTEXITCODE -ne 0) { throw 'Application import failed' }
} finally { Pop-Location }
