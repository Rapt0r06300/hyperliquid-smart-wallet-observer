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

function Write-Step([string]$Text) {
    Write-Host ''
    Write-Host ('=' * 86) -ForegroundColor Cyan
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ('=' * 86) -ForegroundColor Cyan
}

function Assert-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'L installateur doit être lancé dans Windows PowerShell en administrateur.'
    }
}

function Get-BestFixedDrive {
    $drives = @(Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" |
        Where-Object { $_.FreeSpace -gt 0 } |
        Sort-Object FreeSpace -Descending)
    if ($drives.Count -eq 0) { throw 'Aucun disque local fixe détecté.' }
    return $drives[0]
}

function Assert-Command([string]$Name, [string]$HelpText) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name est introuvable. $HelpText"
    }
}

function Assert-Python311 {
    Assert-Command 'py' 'Installe Python 3.11 ou plus avec le Python Launcher puis relance ce script.'
    & py -3.11 -c "import sys; assert sys.version_info >= (3,11); print(sys.version)"
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ est obligatoire pour le laboratoire.' }
}

function Get-RegistrationToken([string]$Repo, [string]$ExplicitToken) {
    if (-not [string]::IsNullOrWhiteSpace($ExplicitToken)) {
        return $ExplicitToken.Trim()
    }

    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if ($gh) {
        try {
            $value = (& gh api --method POST "repos/$Repo/actions/runners/registration-token" --jq '.token' 2>$null)
            if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($value)) {
                Write-Host 'Jeton temporaire de runner obtenu via GitHub CLI.' -ForegroundColor Green
                return ([string]$value).Trim()
            }
        } catch {}
    }

    Write-Host ''
    Write-Host 'GitHub CLI ne fournit pas de jeton de runner automatiquement.' -ForegroundColor Yellow
    Write-Host 'Entre un token GitHub ayant le droit Administration/Actions sur ce dépôt.' -ForegroundColor Yellow
    Write-Host 'Il est saisi masqué, utilisé uniquement pour demander un jeton temporaire de runner puis oublié.' -ForegroundColor DarkGray
    $secure = Read-Host 'Token GitHub' -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $pat = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        if ([string]::IsNullOrWhiteSpace($pat)) { throw 'Token GitHub vide.' }
        $headers = @{
            Authorization = "Bearer $pat"
            Accept = 'application/vnd.github+json'
            'X-GitHub-Api-Version' = '2022-11-28'
            'User-Agent' = 'HyperSmart-Alina-Runner-Installer'
        }
        $uri = "https://api.github.com/repos/$Repo/actions/runners/registration-token"
        $response = Invoke-RestMethod -Method Post -Uri $uri -Headers $headers
        if ([string]::IsNullOrWhiteSpace([string]$response.token)) {
            throw 'GitHub n a pas retourné de jeton temporaire de runner.'
        }
        return ([string]$response.token).Trim()
    } finally {
        if ($bstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
        $pat = $null
        $secure = $null
    }
}

function Download-LatestRunner([string]$TargetRoot) {
    Write-Step 'Téléchargement de la dernière version officielle du GitHub Actions Runner Windows x64'
    $headers = @{
        Accept = 'application/vnd.github+json'
        'X-GitHub-Api-Version' = '2022-11-28'
        'User-Agent' = 'HyperSmart-Alina-Runner-Installer'
    }
    $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/actions/runner/releases/latest' -Headers $headers
    $asset = @($release.assets | Where-Object { $_.name -match '^actions-runner-win-x64-[0-9.]+\.zip$' } | Select-Object -First 1)
    if ($asset.Count -ne 1) { throw 'Archive Windows x64 du GitHub Actions Runner introuvable.' }

    $zip = Join-Path $env:TEMP ([string]$asset[0].name)
    Invoke-WebRequest -Uri ([string]$asset[0].browser_download_url) -OutFile $zip -UseBasicParsing

    $digest = [string]$asset[0].digest
    if (-not [string]::IsNullOrWhiteSpace($digest) -and $digest.StartsWith('sha256:')) {
        $expected = $digest.Substring(7).ToLowerInvariant()
        $actual = (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $expected) { throw 'SHA-256 du GitHub Actions Runner invalide.' }
        Write-Host 'SHA-256 du runner : OK' -ForegroundColor Green
    } else {
        Write-Host 'Digest GitHub non fourni pour cet asset; téléchargement HTTPS officiel utilisé.' -ForegroundColor Yellow
    }

    New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null
    Expand-Archive -Path $zip -DestinationPath $TargetRoot -Force
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
}

function Initialize-Lab([string]$Root, [string]$RepositoryRoot) {
    Write-Step 'Création du stockage persistant ALINA_RESEARCH_HOME'
    foreach ($dir in @(
        '', 'datasets', 'datasets\assets', 'datasets\metadata', 'datasets\materialized',
        'datasets\workspaces', 'jobs', 'jobs\requests', 'results', 'results\github',
        'job_logs', 'status', 'checkpoints', 'tools'
    )) {
        $path = if ([string]::IsNullOrWhiteSpace($dir)) { $Root } else { Join-Path $Root $dir }
        New-Item -ItemType Directory -Force -Path $path | Out-Null
    }

    [Environment]::SetEnvironmentVariable('ALINA_RESEARCH_HOME', $Root, 'Machine')
    $env:ALINA_RESEARCH_HOME = $Root

    # Le service runner Windows utilise normalement NETWORK SERVICE. Le SID évite les problèmes de langue Windows.
    & icacls $Root /grant '*S-1-5-20:(OI)(CI)M' /T /C | Out-Null

    $cockpitSource = Join-Path $RepositoryRoot 'tools\ALINA_RESEARCH_COCKPIT.ps1'
    if (Test-Path $cockpitSource -PathType Leaf) {
        Copy-Item $cockpitSource (Join-Path $Root 'tools\ALINA_RESEARCH_COCKPIT.ps1') -Force
    }

    $launcher = Join-Path $Root 'LANCER_COCKPIT_ALINA.cmd'
    @(
        '@echo off',
        'title ALINA SMARTFLOW - Cockpit',
        'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ALINA_RESEARCH_HOME%\tools\ALINA_RESEARCH_COCKPIT.ps1" -LabRoot "%ALINA_RESEARCH_HOME%" -RefreshSeconds 1',
        'if errorlevel 1 pause'
    ) | Set-Content -Path $launcher -Encoding ASCII

    $status = [ordered]@{
        schema = 'alina.autonomous_live_status.v1'
        heartbeat_unix = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0
        job_id = $null
        suite = $null
        mode = $null
        state = 'WAITING'
        action_fr = 'En attente'
        message_fr = 'Le runner attend un nouveau gros job envoyé par GitHub.'
        paper_only = $true
        real_execution = $false
        live_collection = $false
    }
    $status | ConvertTo-Json -Depth 5 | Set-Content -Path (Join-Path $Root 'status\CURRENT_STATUS.json') -Encoding UTF8
}

Assert-Admin
Assert-Python311
Assert-Command 'git' 'Installe Git for Windows puis relance ce script.'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$best = Get-BestFixedDrive
if ([string]::IsNullOrWhiteSpace($LabRoot)) { $LabRoot = Join-Path ([string]$best.DeviceID + '\') 'ALINA_RESEARCH_HOME' }
if ([string]::IsNullOrWhiteSpace($RunnerRoot)) { $RunnerRoot = Join-Path ([string]$best.DeviceID + '\') 'ALINA_RUNNER_HYPERSMART' }
if ([string]::IsNullOrWhiteSpace($RunnerName)) { $RunnerName = 'HyperSmart-' + $env:COMPUTERNAME }
$LabRoot = [System.IO.Path]::GetFullPath($LabRoot)
$RunnerRoot = [System.IO.Path]::GetFullPath($RunnerRoot)

Write-Step 'Préflight du PC HyperSmart'
Write-Host "Dépôt               : $Repository"
Write-Host "Nom du runner        : $RunnerName"
Write-Host "Laboratoire persistant: $LabRoot"
Write-Host "Runner               : $RunnerRoot"
Write-Host ("Disque choisi         : {0} | libre {1:N2} Gio" -f $best.DeviceID, ([double]$best.FreeSpace / 1GB))
Write-Host 'Trading réel          : BLOQUÉ' -ForegroundColor Green
Write-Host 'Testnet execution      : BLOQUÉE' -ForegroundColor Green

Initialize-Lab -Root $LabRoot -RepositoryRoot $repoRoot

$existingConfigured = Test-Path (Join-Path $RunnerRoot '.runner') -PathType Leaf
if (-not $existingConfigured) {
    if (-not (Test-Path (Join-Path $RunnerRoot 'config.cmd') -PathType Leaf)) {
        Download-LatestRunner -TargetRoot $RunnerRoot
    }

    Write-Step 'Enregistrement sécurisé du PC comme runner self-hosted HyperSmart'
    $temporaryRunnerToken = Get-RegistrationToken -Repo $Repository -ExplicitToken $RunnerToken
    try {
        Push-Location $RunnerRoot
        & .\config.cmd --unattended `
            --url "https://github.com/$Repository" `
            --token $temporaryRunnerToken `
            --name $RunnerName `
            --labels 'hypersmart,alina' `
            --work '_work' `
            --runasservice `
            --replace
        if ($LASTEXITCODE -ne 0) { throw "config.cmd a échoué avec le code $LASTEXITCODE." }
    } finally {
        Pop-Location
        $temporaryRunnerToken = $null
        $RunnerToken = $null
    }
} else {
    Write-Host 'Runner déjà configuré dans ce dossier : aucune réinscription destructive.' -ForegroundColor Green
}

Write-Step 'Vérification du service GitHub Actions Runner'
$service = Get-Service -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like 'actions.runner.*' -or $_.DisplayName -like '*GitHub Actions Runner*' } |
    Select-Object -First 1
if (-not $service) { throw 'Service GitHub Actions Runner non détecté après configuration.' }
if ($service.Status -ne 'Running') {
    Start-Service -Name $service.Name
    $service = Get-Service -Name $service.Name
}
if ($service.Status -ne 'Running') { throw "Service runner non démarré: $($service.Status)" }

Write-Host ''
Write-Host 'INSTALLATION ALINA SELF-HOSTED : OK' -ForegroundColor Green
Write-Host "Service              : $($service.Name) / $($service.Status)" -ForegroundColor Green
Write-Host "ALINA_RESEARCH_HOME  : $LabRoot" -ForegroundColor Green
Write-Host "Cockpit              : $LabRoot\LANCER_COCKPIT_ALINA.cmd" -ForegroundColor Cyan
Write-Host 'Labels               : self-hosted, Windows, X64, hypersmart, alina' -ForegroundColor Cyan
Write-Host ''
Write-Host 'Le PC peut maintenant recevoir les gros jobs HyperSmart depuis GitHub.' -ForegroundColor Green
Write-Host 'Fermer le cockpit ne coupe pas le runner ni les calculs.' -ForegroundColor DarkGray
