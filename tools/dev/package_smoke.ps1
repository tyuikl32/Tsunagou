param(
    [switch]$Keep
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$tempRoot = Join-Path $env:TEMP ('tsunagou-package-smoke-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tempRoot | Out-Null

function Invoke-Checked {
    param([string]$FilePath, [string[]]$ArgumentList, [string]$WorkingDirectory = $repoRoot)
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "command_failed:$FilePath $($ArgumentList -join ' ') (exit $LASTEXITCODE)"
    }
}

$bridgeProcess = $null
try {
    $wheelDir = Join-Path $tempRoot 'wheel'
    New-Item -ItemType Directory -Path $wheelDir | Out-Null
    Invoke-Checked 'uv' @('build', '--wheel', '--out-dir', $wheelDir)
    $wheel = Get-ChildItem -LiteralPath $wheelDir -Filter '*.whl' | Select-Object -First 1
    if ($null -eq $wheel) { throw 'wheel_missing' }

    $venvDir = Join-Path $tempRoot 'venv'
    Invoke-Checked 'uv' @('venv', '--python', '3.13', $venvDir)
    $installedPython = Join-Path $venvDir 'Scripts/python.exe'
    Invoke-Checked 'uv' @('pip', 'install', '--python', $installedPython, $wheel.FullName)
    $helpOutput = & $installedPython -m tsunagou --help
    if ($LASTEXITCODE -ne 0 -or -not ($helpOutput -match 'daemon')) { throw 'wheel_cli_help_failed' }

    Invoke-Checked 'corepack' @('pnpm', '--filter', '@tsunagou/bridge-server', 'run', 'build')
    $bridgePackageDir = Join-Path $repoRoot 'packages/bridge-server'
    $packOutput = & npm pack --pack-destination $tempRoot $bridgePackageDir
    if ($LASTEXITCODE -ne 0) { throw 'bridge_npm_pack_failed' }
    $archive = Get-ChildItem -LiteralPath $tempRoot -Filter '*.tgz' | Select-Object -First 1
    if ($null -eq $archive) { throw 'bridge_archive_missing' }
    $extractRoot = Join-Path $tempRoot 'bridge-extract'
    New-Item -ItemType Directory -Path $extractRoot | Out-Null
    Invoke-Checked 'tar' @('-xzf', $archive.FullName, '-C', $extractRoot)
    $installedBridge = Join-Path $extractRoot 'package'
    Push-Location $installedBridge
    try {
        Invoke-Checked 'npm' @('install', '--omit=dev', '--ignore-scripts') $installedBridge
        $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
        $startInfo.FileName = 'node'
        $startInfo.WorkingDirectory = $installedBridge
        $startInfo.UseShellExecute = $false
        $startInfo.RedirectStandardInput = $true
        $startInfo.RedirectStandardError = $true
        $startInfo.Arguments = '"' + (Join-Path $installedBridge 'dist/server.js') + '"'
        $bridgeProcess = [System.Diagnostics.Process]::new()
        $bridgeProcess.StartInfo = $startInfo
        $null = $bridgeProcess.Start()
        Start-Sleep -Seconds 2
        if ($bridgeProcess.HasExited) {
            $details = $bridgeProcess.StandardError.ReadToEnd()
            throw "bridge_exited:$details"
        }
    } finally {
        Pop-Location
    }

    [pscustomobject]@{
        status = 'passed'
        wheel = $wheel.Name
        bridge_archive = $archive.Name
        source_tree = $false
        protocol_resource = 'package/ protocol/registry/commands.json'
    } | ConvertTo-Json -Compress
} finally {
    if ($null -ne $bridgeProcess -and -not $bridgeProcess.HasExited) {
        $bridgeProcess.StandardInput.Close()
        $bridgeProcess.Kill()
        $bridgeProcess.WaitForExit()
    }
    if (-not $Keep) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    } else {
        Write-Output ("kept_package_smoke_root=" + $tempRoot)
    }
}
