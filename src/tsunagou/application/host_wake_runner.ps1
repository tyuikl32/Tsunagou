# Internal runner: only called after the authenticated message-scoped backend gate.
# No credentials, caller identity, endpoint or free-form commands are accepted.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$result = @{
    host = 'opencode'; version = $null; state = 'unknown'; can_queue = 'unknown'
    result = 'unsupported'; error_code = $null; evidence = @()
    observed_at = [DateTime]::UtcNow.ToString('o'); turn_started = $false; request_associated = $false
}
function Invoke-HostApi([string[]] $ApiArgs) {
    # The installed CLI privately authenticates its managed service. Explicit --server
    # bypasses that credential discovery, so do not copy endpoints/tokens into args.
    $raw = (& $script:launcher @ApiArgs 2>$null) -join "`n"
    $exitCode = $LASTEXITCODE
    try { $value = $raw | ConvertFrom-Json } catch { throw 'host_api_failed' }
    if ($exitCode -ne 0) {
        if ($value._tag -eq 'MessageNotFoundError') { return $null }
        throw 'host_api_failed'
    }
    return $value
}
try {
    $inputData = [Console]::In.ReadToEnd() | ConvertFrom-Json
    if ($inputData.action -notin @('status', 'wake') -or
        $inputData.conversation_id -notmatch '^ses[a-zA-Z0-9_-]+$' -or
        $inputData.message_id -notmatch '^[a-zA-Z0-9_-]+$') { throw 'host_input_invalid' }
    $script:launcher = (Get-Command opencode -ErrorAction Stop).Source
    $version = (& $script:launcher --version 2>$null) -join ''
    if ($LASTEXITCODE -ne 0) { throw 'host_version_unavailable' }
    if ($version.Trim() -ne 'opencode v2.0.18') { throw 'host_version_unverified' }
    $result.version = '2.0.18'
    # Do not use api until an already running background service is known.
    $service = (& $script:launcher service status 2>$null) -join ''
    if ($LASTEXITCODE -ne 0 -or $service.Trim() -notmatch '^http://127\.0\.0\.1:[0-9]+/?$') {
        throw 'host_service_unavailable'
    }
    $script:serviceURL = $service.Trim().TrimEnd('/')
    $serverInfo = Invoke-HostApi @('api', 'GET', '/api/info')
    if ($serverInfo.version -ne '2.0.18') { throw 'host_service_version_mismatch' }
    $sessionPath = '/api/session/' + $inputData.conversation_id
    $session = Invoke-HostApi @('api', 'GET', $sessionPath)
    if ($session.data.id -ne $inputData.conversation_id) { throw 'original_session_not_found' }
    # The authenticated private route binds the original session, not its cwd.
    # A worktree/business directory may differ from the coordination root.
    if (-not $session.data.location.directory -or
        -not [IO.Path]::IsPathRooted($session.data.location.directory) -or
        -not (Test-Path -LiteralPath $session.data.location.directory -PathType Container)) { throw 'host_location_unavailable' }
    $active = Invoke-HostApi @('api', 'GET', '/api/session/active')
    if ($null -eq $active.data -or $active.data -isnot [PSCustomObject]) { throw 'host_state_unavailable' }
    $activeItem = $active.data.PSObject.Properties[$inputData.conversation_id]
    $result.state = if ($null -eq $activeItem) { 'idle' } elseif ($activeItem.Value.type -eq 'running') { 'running' } else { 'unknown' }
    $result.can_queue = $true
    $result.result = 'observed'
    $result.evidence = @('opencode:2.0.18:session.get', 'opencode:2.0.18:session.location_verified', 'opencode:2.0.18:session.active')
    $hashBytes = [System.Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($inputData.message_id))
    $requestID = 'msg_tsunagou_' + ([BitConverter]::ToString($hashBytes).Replace('-', '').ToLowerInvariant())
    $inbox = Invoke-HostApi @('api', 'GET', ($sessionPath + '/inbox'))
    $queued = @($inbox.data | Where-Object { $_.id -eq $requestID })
    if ($queued.Count -gt 0) {
        $result.result = 'queued'; $result.request_associated = $true
    } else {
        # Direct lookup of our deterministic request only; never return chat contents.
        $delivered = $null
        $delivered = Invoke-HostApi @('api', 'GET', ($sessionPath + '/message/' + $requestID))
        if ($null -ne $delivered -and $delivered.data.id -ne $requestID) { throw 'host_admission_unknown' }
        if ($null -ne $delivered.data) {
            $result.result = 'request_already_delivered'; $result.request_associated = $true
        } elseif ($inputData.action -eq 'wake') {
            if ($result.state -eq 'unknown') { throw 'host_state_unavailable' }
            $body = @{
                id = $requestID; text = ('请读取自己的 Tsunagou 项目上下文和收件箱，处理消息 ' + $inputData.message_id + '；遵守已有授权。')
                metadata = @{ tsunagou_message_id = $inputData.message_id }; delivery = 'queue'; resume = $true
            } | ConvertTo-Json -Depth 4 -Compress
            $admitted = Invoke-HostApi @('api', 'POST', ($sessionPath + '/prompt'), '--data', $body)
            if ($admitted.data.id -ne $requestID -or $admitted.data.sessionID -ne $inputData.conversation_id) {
                throw 'host_admission_unknown'
            }
            $result.result = 'queued'; $result.request_associated = $true
            $result.evidence += 'opencode:2.0.18:session.prompt:admitted'
        }
    }
} catch {
    $code = $_.Exception.Message
    if ($code -notin @('host_input_invalid','host_version_unverified','host_version_unavailable','host_service_unavailable',
        'host_service_version_mismatch','original_session_not_found','host_location_unavailable',
        'host_state_unavailable','host_admission_unknown','host_api_failed')) { $code = 'host_runner_failed' }
    $result.error_code = $code
    $result.result = if ($code -in @('host_version_unverified','host_service_version_mismatch','host_service_unavailable')) { 'unsupported' } else { 'unknown' }
}
$result | ConvertTo-Json -Depth 5 -Compress
