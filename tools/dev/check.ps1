param([switch]$SkipNode)
$ErrorActionPreference = 'Stop'
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '../..')
Push-Location $repoRoot
try {
    uv run --locked ruff check src tests tools/dev
    if ($LASTEXITCODE -ne 0) { throw 'Ruff failed' }
    uv run --locked ruff format --check src tests tools/dev
    if ($LASTEXITCODE -ne 0) { throw 'Format check failed' }
    uv run --locked mypy
    if ($LASTEXITCODE -ne 0) { throw 'mypy failed' }
    uv run --locked python tools/dev/check_architecture.py
    if ($LASTEXITCODE -ne 0) { throw 'Architecture check failed' }
    uv run --locked pytest
    if ($LASTEXITCODE -ne 0) { throw 'pytest failed' }
    if (-not $SkipNode) {
        npx --yes pnpm@12.4.2 -r --if-present run build
        if ($LASTEXITCODE -ne 0) { throw 'TS build failed' }
        npx --yes pnpm@12.4.2 check
        if ($LASTEXITCODE -ne 0) { throw 'TS checks failed' }
        npx --yes pnpm@12.4.2 --filter @tsunagou/bridge-server run test:credentials
        if ($LASTEXITCODE -ne 0) { throw 'Credential handoff tests failed' }
        npx --yes pnpm@12.4.2 exec vitest run
        if ($LASTEXITCODE -ne 0) { throw 'TypeScript/frontend tests failed' }
    }
    python tools/docs/validate_docs.py
    if ($LASTEXITCODE -ne 0) { throw 'Documentation check failed' }
} finally { Pop-Location }
