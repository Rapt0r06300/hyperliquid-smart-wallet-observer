[CmdletBinding()]
param(
    [ValidateSet('Status', 'Start', 'Stop', 'Resume', 'Heartbeat', 'Diagnostic')]
    [string]$Action = 'Status',
    [string]$RunnerRoot = 'C:\actions-runner',
    [string]$ProjectRoot = 'C:\Users\flo\Desktop\Projet invest',
    [string]$RequiredLabel = 'hypersmart-final-v1'
)

$ErrorActionPreference = 'Stop'
$RunnerRoot = [System.IO.Path]::GetFullPath($RunnerRoot)
$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)

function Get-RunnerService([string]$Root) {
    $escaped = [Regex]::Escape($Root.TrimEnd('\'))
    $serviceFile = Join-Path $Root '.service'
    if (Test-Path -LiteralPath $serviceFile -PathType Leaf) {
        $name = (Get-Content -LiteralPath $serviceFile -Raw -Encoding UTF8).Trim()
        if (-not [string]::IsNullOrWhiteSpace($name)) {
            $info = Get-CimInstance Win32_Service -Filter "Name='$name'" -ErrorAction SilentlyContinue
            if ($info -and [string]$info.PathName -match $escaped) {
                return Get-Service -Name $name -ErrorAction SilentlyContinue
            }
        }
    }
    $match = Get-CimInstance Win32_Service -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like 'actions.runner.*' -and [string]$_.PathName -match $escaped } |
        Select-Object -First 1
    if ($match) { return Get-Service -Name $match.Name -ErrorAction SilentlyContinue }
    return $null
}

function Get-ProjectState([string]$Root) {
    if (-not (Test-Path -LiteralPath (Join-Path $Root '.git') -PathType Container)) {
        throw "PROJECT_ROOT_INVALID: $Root"
    }
    $branch = (& git -C $Root branch --show-current).Trim()
    $head = (& git -C $Root rev-parse HEAD).Trim().ToLowerInvariant()
    $remote = (& git -C $Root rev-parse origin/main 2>$null).Trim().ToLowerInvariant()
    $dirty = @(& git -C $Root status --porcelain)
    return [ordered]@{
        branch = $branch
        head = $head
        origin_main = $remote
        clean = ($dirty.Count -eq 0)
        exact_main = ($branch -eq 'main' -and $dirty.Count -eq 0 -and $head -eq $remote -and $head -match '^[0-9a-f]{40}$')
    }
}

function Assert-PaperOnlyGuards {
    $expected = [ordered]@{
        HL_ENABLE_MAINNET_EXECUTION = '0'
        HL_ENABLE_TESTNET_EXECUTION = '0'
        REAL_MAINNET_TRADING = 'false'
        TESTNET_EXECUTION_ENABLED = 'false'
        HYPERSMART_ENABLE_REAL_ORDERS = '0'
        ENABLE_REAL_ORDERS = '0'
        HYPERSMART_ANALYSIS_LOCAL_ONLY = '1'
    }
    foreach ($entry in $expected.GetEnumerator()) {
        $actual = [Environment]::GetEnvironmentVariable([string]$entry.Key, 'Machine')
        if ([string]$actual -cne [string]$entry.Value) {
            throw "PAPER_GUARD_REFUSED: $($entry.Key)=$actual attendu=$($entry.Value)"
        }
    }
}

function Assert-StartGate {
    $manifestPath = Join-Path $RunnerRoot 'HYPERSMART_RUNNER_PREPARED.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw 'RUNNER_MANIFEST_MISSING' }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$manifest.required_label -cne $RequiredLabel) { throw 'RUNNER_LABEL_REFUSED' }
    if ($manifest.paper_only -ne $true -or $manifest.real_execution -ne $false) { throw 'RUNNER_SAFETY_MANIFEST_REFUSED' }
    if ($manifest.configured -ne $true) { throw 'RUNNER_NOT_REGISTERED' }
    if ([string]$manifest.runner_workspace -cne (Join-Path $RunnerRoot '_work')) { throw 'RUNNER_WORKSPACE_REFUSED' }
    if ([string]$manifest.project_root -cne $ProjectRoot) { throw 'PROJECT_ROOT_MANIFEST_REFUSED' }
    $project = Get-ProjectState -Root $ProjectRoot
    if (-not $project.exact_main) {
        throw "PROJECT_SHA_REFUSED: branch=$($project.branch) clean=$($project.clean) HEAD=$($project.head) origin/main=$($project.origin_main)"
    }
    if ([string]$manifest.project_sha -cne [string]$project.head) {
        throw "PREPARED_SHA_STALE: prepared=$($manifest.project_sha) current=$($project.head)"
    }
    Assert-PaperOnlyGuards
}

function Write-Heartbeat([string]$State, $Service, $Project) {
    $labRoot = [Environment]::GetEnvironmentVariable('ALINA_RESEARCH_HOME', 'Machine')
    if ([string]::IsNullOrWhiteSpace($labRoot)) { throw 'ALINA_RESEARCH_HOME_MISSING' }
    $statusDir = Join-Path $labRoot 'status'
    New-Item -ItemType Directory -Force -Path $statusDir | Out-Null
    $path = Join-Path $statusDir 'RUNNER_HEARTBEAT.json'
    $tmp = "$path.$PID.tmp"
    $payload = [ordered]@{
        schema = 'hypersmart.runner_heartbeat.v1'
        heartbeat_utc = [DateTimeOffset]::UtcNow.ToString('o')
        heartbeat_unix = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0
        state = $State
        service = if ($Service) { [string]$Service.Name } else { $null }
        service_status = if ($Service) { [string]$Service.Status } else { 'ABSENT' }
        project_sha = if ($Project) { [string]$Project.head } else { $null }
        exact_main = if ($Project) { [bool]$Project.exact_main } else { $false }
        required_label = $RequiredLabel
        paper_only = $true
        read_only_mainnet = $true
        real_execution = $false
    }
    $payload | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $path -Force
    return $path
}

$service = Get-RunnerService -Root $RunnerRoot
$project = Get-ProjectState -Root $ProjectRoot

switch ($Action) {
    'Start' {
        Assert-StartGate
        if (-not $service) { throw 'RUNNER_SERVICE_MISSING' }
        if ($service.Status -ne 'Running') { Start-Service -Name $service.Name }
        $service = Get-Service -Name $service.Name
        Write-Heartbeat -State 'RUNNING' -Service $service -Project $project | Out-Null
    }
    'Resume' {
        Assert-StartGate
        if (-not $service) { throw 'RUNNER_SERVICE_MISSING' }
        if ($service.Status -ne 'Running') { Start-Service -Name $service.Name }
        $service = Get-Service -Name $service.Name
        Write-Heartbeat -State 'RESUME_REQUESTED' -Service $service -Project $project | Out-Null
    }
    'Stop' {
        if (-not $service) { throw 'RUNNER_SERVICE_MISSING' }
        if ($service.Status -ne 'Stopped') { Stop-Service -Name $service.Name }
        $service = Get-Service -Name $service.Name
        Write-Heartbeat -State 'STOPPED' -Service $service -Project $project | Out-Null
    }
    'Heartbeat' {
        $path = Write-Heartbeat -State 'STATUS' -Service $service -Project $project
        Write-Host "HEARTBEAT_OK $path" -ForegroundColor Green
    }
    'Diagnostic' {
        $verifier = Join-Path $PSScriptRoot 'VERIFIER_ALINA_RUNNER_WINDOWS.ps1'
        & $verifier -RunnerRoot $RunnerRoot -ProjectRoot $ProjectRoot -RequiredLabel $RequiredLabel
        exit $LASTEXITCODE
    }
    'Status' {}
}

$service = Get-RunnerService -Root $RunnerRoot
$summary = [ordered]@{
    action = $Action
    runner_root = $RunnerRoot
    workspace = (Join-Path $RunnerRoot '_work')
    service = if ($service) { [string]$service.Name } else { $null }
    service_status = if ($service) { [string]$service.Status } else { 'ABSENT' }
    project_root = $ProjectRoot
    project_sha = [string]$project.head
    exact_main = [bool]$project.exact_main
    required_label = $RequiredLabel
    paper_only = $true
    real_execution = $false
}
$summary | ConvertTo-Json -Depth 4
