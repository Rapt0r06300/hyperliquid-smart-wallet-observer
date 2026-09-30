[CmdletBinding()]
param(
    [string]$LabRoot = $env:ALINA_RESEARCH_HOME,
    [string]$RunnerRoot = 'C:\actions-runner',
    [string]$ProjectRoot = $env:HYPERSMART_PROJECT_ROOT,
    [string]$RequiredLabel = 'hypersmart-final-v1',
    [switch]$AllowPrepared
)

$ErrorActionPreference = 'SilentlyContinue'
$failures = New-Object System.Collections.Generic.List[string]
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$RunnerRoot = [System.IO.Path]::GetFullPath($RunnerRoot).TrimEnd('\')
$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
$manifestPath = Join-Path $RunnerRoot 'HYPERSMART_RUNNER_PREPARED.json'

function Row([string]$Name, [bool]$Ok, [string]$Detail) {
    $color = if ($Ok) { [ConsoleColor]::Green } else { [ConsoleColor]::Red }
    $mark = if ($Ok) { 'OK' } else { 'ECHEC' }
    Write-Host ($Name.PadRight(36) + ' : ') -NoNewline
    Write-Host ($mark.PadRight(6) + ' ' + $Detail) -ForegroundColor $color
    if (-not $Ok) { $failures.Add($Name) | Out-Null }
}

function Resolve-GitExe([string]$Root) {
    $embedded = Join-Path $Root 'tools\git\cmd\git.exe'
    if (Test-Path -LiteralPath $embedded -PathType Leaf) { return $embedded }
    $command = Get-Command git -ErrorAction SilentlyContinue
    if ($command) { return [string]$command.Source }
    return ''
}

function Get-RunnerServiceInfo([string]$Root) {
    $serviceName = ''
    $serviceFile = Join-Path $Root '.service'
    if (Test-Path -LiteralPath $serviceFile -PathType Leaf) {
        $serviceName = (Get-Content -LiteralPath $serviceFile -Raw -Encoding UTF8).Trim()
    }
    $services = @(Get-CimInstance Win32_Service -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like 'actions.runner.*' })
    if (-not [string]::IsNullOrWhiteSpace($serviceName)) {
        $services = @($services | Where-Object { $_.Name -eq $serviceName })
    }
    $prefix = [Regex]::Escape($Root)
    return @($services | Where-Object { [string]$_.PathName -match $prefix } | Select-Object -First 1)
}

function Read-Json([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $null }
}

Write-Host ''
Write-Host '================================================================================' -ForegroundColor Cyan
Write-Host ' HYPERSMART - DIAGNOSTIC DU RUNNER WINDOWS SELF-HOSTED' -ForegroundColor Cyan
Write-Host '================================================================================' -ForegroundColor Cyan

$manifest = Read-Json -Path $manifestPath
Row 'Manifeste runner HyperSmart' ($null -ne $manifest) $manifestPath
$preparedOnly = $false
if ($manifest) {
    $preparedOnly = ($manifest.configured -ne $true)
    Row 'Dépôt GitHub attendu' ([string]$manifest.repository -ceq 'Rapt0r06300/hyperliquid-smart-wallet-observer') ([string]$manifest.repository)
    Row 'Label HyperSmart dédié' ([string]$manifest.required_label -ceq $RequiredLabel) ([string]$manifest.required_label)
    Row 'Mode PAPER/READ-ONLY' ($manifest.paper_only -eq $true -and $manifest.real_execution -eq $false) "paper=$($manifest.paper_only) real=$($manifest.real_execution)"
    Row 'Workspace Actions séparé' ([string]$manifest.runner_workspace -ceq (Join-Path $RunnerRoot '_work')) ([string]$manifest.runner_workspace)
}

$runnerExists = Test-Path -LiteralPath $RunnerRoot -PathType Container
Row 'Dossier C:\actions-runner' $runnerExists $RunnerRoot
$projectExists = Test-Path -LiteralPath (Join-Path $ProjectRoot '.git') -PathType Container
Row 'Dépôt de développement' $projectExists $ProjectRoot
$separate = -not ($RunnerRoot.StartsWith($ProjectRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or
    $ProjectRoot.StartsWith($RunnerRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or
    $RunnerRoot.Equals($ProjectRoot, [StringComparison]::OrdinalIgnoreCase))
Row 'Runner séparé du dépôt' $separate "$RunnerRoot <> $ProjectRoot"

$gitExe = Resolve-GitExe -Root $ProjectRoot
Row 'Git for Windows' (-not [string]::IsNullOrWhiteSpace($gitExe)) $(if ($gitExe) { $gitExe } else { 'git.exe absent' })
$branch = ''
$head = ''
$originMain = ''
$clean = $false
if ($projectExists -and $gitExe) {
    $branch = (& $gitExe -C $ProjectRoot branch --show-current 2>$null).Trim()
    $head = (& $gitExe -C $ProjectRoot rev-parse HEAD 2>$null).Trim().ToLowerInvariant()
    $originMain = (& $gitExe -C $ProjectRoot rev-parse origin/main 2>$null).Trim().ToLowerInvariant()
    $dirty = @(& $gitExe -C $ProjectRoot status --porcelain 2>$null)
    $clean = ($dirty.Count -eq 0)
}
Row 'Branche main' ($branch -ceq 'main') $branch
Row 'Worktree de développement propre' $clean $(if ($clean) { 'aucune modification' } else { 'modifications présentes' })
$exactMain = ($head -match '^[0-9a-f]{40}$' -and $head -ceq $originMain)
Row 'SHA exact de origin/main' $exactMain "HEAD=$head origin/main=$originMain"
if ($manifest) {
    Row 'SHA préparé encore exact' ([string]$manifest.project_sha -ceq $head) ([string]$manifest.project_sha)
    Row 'Chemin projet du manifeste' ([string]$manifest.project_root -ceq $ProjectRoot) ([string]$manifest.project_root)
}

$guards = [ordered]@{
    HL_ENABLE_MAINNET_EXECUTION = '0'
    HL_ENABLE_TESTNET_EXECUTION = '0'
    REAL_MAINNET_TRADING = 'false'
    TESTNET_EXECUTION_ENABLED = 'false'
    HYPERSMART_ENABLE_REAL_ORDERS = '0'
    ENABLE_REAL_ORDERS = '0'
    HYPERSMART_ANALYSIS_LOCAL_ONLY = '1'
}
foreach ($entry in $guards.GetEnumerator()) {
    $actual = [Environment]::GetEnvironmentVariable([string]$entry.Key, 'Machine')
    Row ("Garde " + [string]$entry.Key) ([string]$actual -ceq [string]$entry.Value) "actuel=$actual attendu=$($entry.Value)"
}

$machineLab = [Environment]::GetEnvironmentVariable('ALINA_RESEARCH_HOME', 'Machine')
if ([string]::IsNullOrWhiteSpace($LabRoot)) { $LabRoot = $machineLab }
$labOk = -not [string]::IsNullOrWhiteSpace($LabRoot)
if ($labOk) {
    try { $LabRoot = [System.IO.Path]::GetFullPath($LabRoot) } catch { $labOk = $false }
}
Row 'Variable ALINA_RESEARCH_HOME' ($labOk -and [string]$machineLab -ceq [string]$LabRoot) ([string]$LabRoot)
Row 'Dossier laboratoire' ($labOk -and (Test-Path -LiteralPath $LabRoot -PathType Container)) ([string]$LabRoot)

$runnerPython = [Environment]::GetEnvironmentVariable('ALINA_PYTHON_EXE', 'Machine')
$pythonPathOk = -not [string]::IsNullOrWhiteSpace($runnerPython)
if ($pythonPathOk) {
    try { $runnerPython = [System.IO.Path]::GetFullPath($runnerPython) } catch { $pythonPathOk = $false }
}
if ($pythonPathOk) { $pythonPathOk = Test-Path -LiteralPath $runnerPython -PathType Leaf }
Row 'Variable ALINA_PYTHON_EXE' $pythonPathOk $(if ($runnerPython) { [string]$runnerPython } else { 'absente' })
$pythonOk = $false
$pythonDetail = 'absent ou invalide'
if ($pythonPathOk) {
    $version = (& $runnerPython -c "import sys; print('.'.join(map(str, sys.version_info[:3]))); raise SystemExit(0 if sys.version_info >= (3,11) else 2)" 2>$null | Select-Object -Last 1)
    $pythonOk = $LASTEXITCODE -eq 0
    if ($pythonOk) { $pythonDetail = "Python $version | $runnerPython" }
}
Row 'Python persistant 3.11+' $pythonOk $pythonDetail

if ($labOk -and (Test-Path -LiteralPath $LabRoot -PathType Container)) {
    foreach ($relative in @('datasets','jobs\requests','results\github','status','job_logs','checkpoints','tools','runtime','runtime\python')) {
        Row ("Sous-dossier $relative") (Test-Path -LiteralPath (Join-Path $LabRoot $relative) -PathType Container) (Join-Path $LabRoot $relative)
    }
    $expectedPython = Join-Path $LabRoot 'runtime\python\Scripts\python.exe'
    $pythonInLab = $pythonPathOk -and ([System.IO.Path]::GetFullPath($runnerPython) -ceq [System.IO.Path]::GetFullPath($expectedPython))
    Row 'Python dans ALINA_RESEARCH_HOME' $pythonInLab $expectedPython
    $root = [System.IO.Path]::GetPathRoot($LabRoot)
    $drive = Get-PSDrive -Name $root.Substring(0,1) -ErrorAction SilentlyContinue
    if ($drive) {
        $free = [Math]::Round($drive.Free / 1GB, 2)
        Row 'Réserve disque >= 25 Gio' ($free -ge 25) ("$free Gio libres")
    }
    Row 'Cockpit copié' (Test-Path -LiteralPath (Join-Path $LabRoot 'tools\ALINA_RESEARCH_COCKPIT.ps1') -PathType Leaf) (Join-Path $LabRoot 'tools\ALINA_RESEARCH_COCKPIT.ps1')
}

$serviceInfo = @(Get-RunnerServiceInfo -Root $RunnerRoot)
$serviceRequired = -not ($AllowPrepared -and $preparedOnly)
$serviceFound = ($serviceInfo.Count -eq 1)
Row 'Service actions.runner.* ciblé' ($serviceFound -or -not $serviceRequired) $(if ($serviceFound) { [string]$serviceInfo[0].Name } else { 'enregistrement restant' })
if ($serviceFound) {
    $service = Get-Service -Name $serviceInfo[0].Name -ErrorAction SilentlyContinue
    Row 'Chemin service sous RunnerRoot' ([string]$serviceInfo[0].PathName -match [Regex]::Escape($RunnerRoot)) ([string]$serviceInfo[0].PathName)
    Row 'Service configuré automatique' ([string]$serviceInfo[0].StartMode -ceq 'Auto') ([string]$serviceInfo[0].StartMode)
    Row 'Runner en cours d execution' ($service -and $service.Status -eq 'Running') $(if ($service) { [string]$service.Status } else { 'absent' })
    Row 'Configuration .runner présente' (Test-Path -LiteralPath (Join-Path $RunnerRoot '.runner') -PathType Leaf) (Join-Path $RunnerRoot '.runner')
}

$labelsOk = $false
$labelsDetail = 'non vérifiés avant enregistrement'
if ($serviceFound -and $manifest) {
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if ($gh) {
        $runnerList = & $gh.Source api "repos/Rapt0r06300/hyperliquid-smart-wallet-observer/actions/runners" 2>$null
        if ($LASTEXITCODE -eq 0 -and $runnerList) {
            try {
                $payload = $runnerList | ConvertFrom-Json
                $online = @($payload.runners | Where-Object { [string]$_.name -ceq [string]$manifest.runner_name } | Select-Object -First 1)
                if ($online.Count -eq 1) {
                    $labels = @($online[0].labels | ForEach-Object { [string]$_.name })
                    $required = @('self-hosted','Windows','X64',$RequiredLabel)
                    $missing = @($required | Where-Object { $_ -notin $labels })
                    $labelsOk = ($missing.Count -eq 0)
                    $labelsDetail = if ($labelsOk) { $labels -join ', ' } else { 'manquants: ' + ($missing -join ', ') }
                }
            } catch { $labelsDetail = 'réponse GitHub invalide' }
        } else { $labelsDetail = 'gh non authentifié ou API indisponible' }
    } else { $labelsDetail = 'gh.exe absent' }
}
Row 'Labels GitHub du runner' ($labelsOk -or -not $serviceRequired) $labelsDetail

Write-Host ''
Write-Host 'Sécurité fixe : mainnet=0 | testnet execution=0 | PAPER/READ-ONLY | aucun shell libre.' -ForegroundColor Green
if ($failures.Count -eq 0) {
    if ($preparedOnly) {
        Write-Host 'DIAGNOSTIC FINAL : RUNNER PRÉPARÉ - ENREGISTREMENT REQUIS' -ForegroundColor Yellow
    } else {
        Write-Host 'DIAGNOSTIC FINAL : RUNNER PRÊT' -ForegroundColor Green
    }
    exit 0
}
Write-Host ('DIAGNOSTIC FINAL : ' + $failures.Count + ' point(s) à corriger') -ForegroundColor Red
$failures | ForEach-Object { Write-Host (' - ' + $_) -ForegroundColor Red }
exit 2
