[CmdletBinding()]
param(
    [string]$Repository = 'Rapt0r06300/hyperliquid-smart-wallet-observer',
    [string]$LabRoot = '',
    [string]$RunnerRoot = '',
    [string]$RunnerName = '',
    [string]$RunnerToken = ''
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$FinalLabel = 'hypersmart-final-v1'

if ([string]$env:GO_SELF_HOSTED -cne 'TRUE') {
    Write-Host '[REFUS] GO_SELF_HOSTED=TRUE est obligatoire.' -ForegroundColor Red
    Write-Host 'Aucun runner final ne sera installé ou démarré.' -ForegroundColor Yellow
    exit 9
}

function Write-Step([string]$Text) {
    Write-Host ''
    Write-Host ('=' * 88) -ForegroundColor Cyan
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ('=' * 88) -ForegroundColor Cyan
}

function Assert-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'L installateur final doit être lancé dans Windows PowerShell en administrateur.'
    }
}

function Get-BestFixedDrive {
    $drives = @(Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" |
        Where-Object { $_.FreeSpace -gt 0 } |
        Sort-Object FreeSpace -Descending)
    if ($drives.Count -eq 0) { throw 'Aucun disque local fixe détecté.' }
    return $drives[0]
}

function Get-BasePython311 {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw 'Python Launcher introuvable. Installer Python 3.11+ puis relancer.'
    }
    $value = (& py -3.11 -c "import sys; print(sys.executable)" 2>$null | Select-Object -Last 1)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace([string]$value)) {
        throw 'Python 3.11+ est obligatoire.'
    }
    $python = [System.IO.Path]::GetFullPath(([string]$value).Trim())
    & $python -c "import sys; assert sys.version_info >= (3,11)" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ invalide.' }
    return $python
}

function Get-RegistrationToken([string]$Repo, [string]$ExplicitToken) {
    if (-not [string]::IsNullOrWhiteSpace($ExplicitToken)) { return $ExplicitToken.Trim() }
    if (Get-Command gh -ErrorAction SilentlyContinue) {
        try {
            $value = (& gh api --method POST "repos/$Repo/actions/runners/registration-token" --jq '.token' 2>$null)
            if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace([string]$value)) {
                return ([string]$value).Trim()
            }
        } catch {}
    }
    Write-Host 'Un token GitHub Administration/Actions est nécessaire uniquement pour obtenir le jeton temporaire du runner.' -ForegroundColor Yellow
    $secure = Read-Host 'Token GitHub' -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $pat = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        if ([string]::IsNullOrWhiteSpace($pat)) { throw 'Token GitHub vide.' }
        $headers = @{
            Authorization = "Bearer $pat"
            Accept = 'application/vnd.github+json'
            'X-GitHub-Api-Version' = '2022-11-28'
            'User-Agent' = 'HyperSmart-FinalV1-Installer'
        }
        $response = Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/$Repo/actions/runners/registration-token" -Headers $headers
        if ([string]::IsNullOrWhiteSpace([string]$response.token)) { throw 'Jeton temporaire runner absent.' }
        return ([string]$response.token).Trim()
    } finally {
        if ($bstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
        $pat = $null
        $secure = $null
    }
}

function Download-LatestRunner([string]$TargetRoot) {
    Write-Step 'Téléchargement du GitHub Actions Runner officiel Windows x64'
    $headers = @{
        Accept = 'application/vnd.github+json'
        'X-GitHub-Api-Version' = '2022-11-28'
        'User-Agent' = 'HyperSmart-FinalV1-Installer'
    }
    $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/actions/runner/releases/latest' -Headers $headers
    $asset = @($release.assets | Where-Object { $_.name -match '^actions-runner-win-x64-[0-9.]+\.zip$' } | Select-Object -First 1)
    if ($asset.Count -ne 1) { throw 'Archive officielle runner Windows x64 introuvable.' }
    $zip = Join-Path $env:TEMP ([string]$asset[0].name)
    Invoke-WebRequest -Uri ([string]$asset[0].browser_download_url) -OutFile $zip -UseBasicParsing
    $digest = [string]$asset[0].digest
    if (-not [string]::IsNullOrWhiteSpace($digest) -and $digest.StartsWith('sha256:')) {
        $expected = $digest.Substring(7).ToLowerInvariant()
        $actual = (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $expected) { throw 'SHA-256 du runner invalide.' }
    }
    New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null
    Expand-Archive -Path $zip -DestinationPath $TargetRoot -Force
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
}

function Initialize-Lab([string]$Root, [string]$RepositoryRoot) {
    Write-Step 'Préparation du laboratoire persistant final'
    foreach ($dir in @('', 'datasets', 'datasets\assets', 'datasets\metadata', 'datasets\materialized', 'datasets\workspaces', 'jobs', 'jobs\requests', 'results', 'results\jobs', 'job_logs', 'status', 'checkpoints', 'tools', 'runtime')) {
        $path = if ([string]::IsNullOrWhiteSpace($dir)) { $Root } else { Join-Path $Root $dir }
        New-Item -ItemType Directory -Force -Path $path | Out-Null
    }
    [Environment]::SetEnvironmentVariable('ALINA_RESEARCH_HOME', $Root, 'Machine')
    $env:ALINA_RESEARCH_HOME = $Root
    & icacls $Root /grant '*S-1-5-20:(OI)(CI)M' /T /C | Out-Null
    $cockpit = Join-Path $RepositoryRoot 'tools\ALINA_RESEARCH_COCKPIT.ps1'
    if (Test-Path $cockpit -PathType Leaf) {
        Copy-Item $cockpit (Join-Path $Root 'tools\ALINA_RESEARCH_COCKPIT.ps1') -Force
    }
}

function Initialize-RunnerPython([string]$Root, [string]$BasePython, [string]$RepositoryRoot) {
    Write-Step 'Création du Python persistant du runner final'
    $venvRoot = Join-Path $Root 'runtime\python'
    $python = Join-Path $venvRoot 'Scripts\python.exe'
    if (-not (Test-Path $python -PathType Leaf)) {
        & $BasePython -m venv $venvRoot
        if ($LASTEXITCODE -ne 0) { throw 'Création du virtualenv persistant impossible.' }
    }
    & $python -m pip install --disable-pip-version-check -e $RepositoryRoot
    if ($LASTEXITCODE -ne 0) { throw 'Installation du projet dans le Python persistant impossible.' }
    & $python -c "import sys; assert sys.version_info >= (3,11); import hl_observer; print(sys.executable)"
    if ($LASTEXITCODE -ne 0) { throw 'Runtime Python final invalide.' }
    [Environment]::SetEnvironmentVariable('ALINA_PYTHON_EXE', $python, 'Machine')
    $env:ALINA_PYTHON_EXE = $python
    return $python
}

function Get-ConfiguredService([string]$Root, [string]$ExpectedRunnerName) {
    $serviceFile = Join-Path $Root '.service'
    if (Test-Path $serviceFile -PathType Leaf) {
        $serviceName = (Get-Content $serviceFile -Raw -Encoding UTF8).Trim()
        if (-not [string]::IsNullOrWhiteSpace($serviceName)) {
            $service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
            if ($service) { return $service }
        }
    }
    return Get-Service -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like 'actions.runner.*' -and ($_.Name -like "*$ExpectedRunnerName*" -or $_.DisplayName -like "*$ExpectedRunnerName*") } |
        Select-Object -First 1
}

function Configure-ServiceRecovery([System.ServiceProcess.ServiceController]$Service) {
    Set-Service -Name $Service.Name -StartupType Automatic
    & sc.exe failure $Service.Name 'reset=' 86400 'actions=' 'restart/60000/restart/60000/restart/300000' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Configuration de reprise du service impossible.' }
    & sc.exe failureflag $Service.Name 1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Activation failureflag impossible.' }
}

Assert-Admin
$basePython = Get-BasePython311
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git for Windows est obligatoire.' }
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$branch = (& git -C $repoRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $branch -ne 'main') { throw "Le dépôt local doit être sur main. Branche actuelle: $branch" }
$dirty = @(& git -C $repoRoot status --porcelain)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) { throw 'Le dépôt local doit être propre avant installation du runner final.' }
$best = Get-BestFixedDrive
if ([string]::IsNullOrWhiteSpace($LabRoot)) { $LabRoot = Join-Path ([string]$best.DeviceID + '\') 'ALINA_RESEARCH_HOME' }
if ([string]::IsNullOrWhiteSpace($RunnerRoot)) { $RunnerRoot = Join-Path ([string]$best.DeviceID + '\') 'ALINA_RUNNER_HYPERSMART_FINAL_V1' }
if ([string]::IsNullOrWhiteSpace($RunnerName)) { $RunnerName = 'HyperSmart-FinalV1-' + $env:COMPUTERNAME }
$LabRoot = [System.IO.Path]::GetFullPath($LabRoot)
$RunnerRoot = [System.IO.Path]::GetFullPath($RunnerRoot)

Write-Step 'Préflight runner final isolé des anciennes files'
Write-Host "Repository           : $Repository"
Write-Host "RunnerName           : $RunnerName"
Write-Host "RunnerRoot           : $RunnerRoot"
Write-Host "ALINA_RESEARCH_HOME  : $LabRoot"
Write-Host "Label final          : $FinalLabel"
Write-Host 'Ancien label hypersmart: volontairement ABSENT' -ForegroundColor Green
Write-Host 'Trading réel         : BLOQUÉ' -ForegroundColor Green
Write-Host ("Disque choisi        : {0} | libre {1:N2} Gio" -f $best.DeviceID, ([double]$best.FreeSpace / 1GB))
if ([double]$best.FreeSpace / 1GB -lt 25) { throw 'Moins de 25 Gio libres sur le disque choisi.' }

Initialize-Lab -Root $LabRoot -RepositoryRoot $repoRoot
$runnerPython = Initialize-RunnerPython -Root $LabRoot -BasePython $basePython -RepositoryRoot $repoRoot
$configured = Test-Path (Join-Path $RunnerRoot '.runner') -PathType Leaf
if (-not $configured) {
    if (-not (Test-Path (Join-Path $RunnerRoot 'config.cmd') -PathType Leaf)) {
        Download-LatestRunner -TargetRoot $RunnerRoot
    }
    Write-Step 'Enregistrement du runner final avec label isolé'
    $temporaryRunnerToken = Get-RegistrationToken -Repo $Repository -ExplicitToken $RunnerToken
    try {
        Push-Location $RunnerRoot
        & .\config.cmd --unattended --url "https://github.com/$Repository" --token $temporaryRunnerToken --name $RunnerName --labels "$FinalLabel,alina" --work '_work' --runasservice --replace
        if ($LASTEXITCODE -ne 0) { throw "config.cmd final a échoué avec le code $LASTEXITCODE" }
    } finally {
        Pop-Location
        $temporaryRunnerToken = $null
        $RunnerToken = $null
    }
} else {
    Write-Host 'Runner final déjà configuré dans son dossier dédié.' -ForegroundColor Green
}

$service = Get-ConfiguredService -Root $RunnerRoot -ExpectedRunnerName $RunnerName
if (-not $service) { throw 'Service du runner FINAL_V1 introuvable.' }
Configure-ServiceRecovery -Service $service
if ($service.Status -ne 'Running') {
    Start-Service -Name $service.Name
    $service = Get-Service -Name $service.Name
}
if ($service.Status -ne 'Running') { throw "Service final non démarré: $($service.Status)" }

Write-Host ''
Write-Host 'ALINA SELF-HOSTED FINAL V1 : PRÊT' -ForegroundColor Green
Write-Host "Service             : $($service.Name) / $($service.Status)" -ForegroundColor Green
Write-Host "Labels requis       : self-hosted, Windows, X64, $FinalLabel" -ForegroundColor Cyan
Write-Host "ALINA_RESEARCH_HOME : $LabRoot" -ForegroundColor Cyan
Write-Host "ALINA_PYTHON_EXE    : $runnerPython" -ForegroundColor Cyan
Write-Host 'Les anciens jobs exigeant le label hypersmart ne peuvent pas utiliser ce runner.' -ForegroundColor Yellow
Write-Host 'Le workflow final refusera aussi tout SHA qui n est plus HEAD de main.' -ForegroundColor Yellow
