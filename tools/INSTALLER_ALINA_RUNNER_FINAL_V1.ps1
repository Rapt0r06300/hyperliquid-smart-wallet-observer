[CmdletBinding()]
param(
    [string]$Repository = 'Rapt0r06300/hyperliquid-smart-wallet-observer',
    [string]$LabRoot = '',
    [string]$RunnerRoot = 'C:\actions-runner',
    [string]$ProjectRoot = '',
    [string]$RunnerName = '',
    [string]$RunnerToken = '',
    [string]$InstallLog = '',
    [switch]$PrepareOnly,
    [switch]$ConfirmSelfHosted,
    [switch]$Elevate
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$FinalLabel = 'hypersmart-final-v1'

if ([string]::IsNullOrWhiteSpace($InstallLog)) {
    $projectForLog = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $InstallLog = Join-Path $projectForLog 'logs\runner_install_latest.log'
}

if ([string]$env:GO_SELF_HOSTED -cne 'TRUE' -and -not $ConfirmSelfHosted) {
    Write-Host '[REFUS] GO_SELF_HOSTED=TRUE ou -ConfirmSelfHosted est obligatoire.' -ForegroundColor Red
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

function Get-BasePython311([string]$RepositoryRoot) {
    $candidates = New-Object System.Collections.Generic.List[string]
    $systemPython = Get-Command python -ErrorAction SilentlyContinue
    if ($systemPython) { $candidates.Add([string]$systemPython.Source) | Out-Null }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $value = (& py -3.11 -c "import sys; print(sys.executable)" 2>$null | Select-Object -Last 1)
            $pyExitCode = $LASTEXITCODE
            if ($pyExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace([string]$value)) {
                $candidates.Add(([string]$value).Trim()) | Out-Null
            }
        } catch {
            # Le lanceur py peut exister sans runtime 3.11. Le Python système/portable reste valide.
        } finally {
            $ErrorActionPreference = $previousPreference
        }
    }
    foreach ($relative in @('portable_runtime\python\python.exe', 'tools\python\python.exe')) {
        $candidate = Join-Path $RepositoryRoot $relative
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { $candidates.Add($candidate) | Out-Null }
    }
    foreach ($candidate in @($candidates | Select-Object -Unique)) {
        try {
            $python = [System.IO.Path]::GetFullPath($candidate)
            & $python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 2)" 2>$null
            if ($LASTEXITCODE -eq 0) { return $python }
        } catch {}
    }
    throw 'Python 3.11+ introuvable (py, python et runtimes portables HyperSmart vérifiés).'
}

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if ($Elevate -and -not (Test-Admin)) {
    $quotedScript = '"' + $PSCommandPath + '"'
    $quotedLog = '"' + $InstallLog + '"'
    $arguments = "-NoLogo -NoProfile -ExecutionPolicy Bypass -File $quotedScript -ConfirmSelfHosted -InstallLog $quotedLog"
    try {
        $process = Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $arguments -Wait -PassThru -ErrorAction Stop
        exit $process.ExitCode
    } catch {
        Write-Error $_
        exit 1223
    }
}

$installLogDirectory = Split-Path -Parent $InstallLog
New-Item -ItemType Directory -Force -Path $installLogDirectory | Out-Null
Set-Content -LiteralPath $InstallLog -Encoding UTF8 -Value @(
    ('[{0}] Début installation runner HyperSmart' -f [DateTimeOffset]::Now.ToString('o')),
    ('PowerShell={0} Admin={1} Script={2}' -f $PSVersionTable.PSVersion, (Test-Admin), $PSCommandPath)
)
try { Start-Transcript -LiteralPath $InstallLog -Append -Force | Out-Null } catch {}
trap {
    $detail = $_ | Out-String
    Write-Host ("ERREUR FATALE:`n" + $detail) -ForegroundColor Red
    Write-Error $_
    try { Stop-Transcript | Out-Null } catch {}
    exit 1
}

function Get-ExactMainSha([string]$RepositoryRoot) {
    $branch = (& git -C $RepositoryRoot branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0 -or $branch -ne 'main') { throw "Le dépôt local doit être sur main. Branche actuelle: $branch" }
    $dirty = @(& git -C $RepositoryRoot status --porcelain)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) { throw 'Le dépôt local doit être propre avant préparation du runner.' }
    & git -C $RepositoryRoot fetch origin main --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Impossible de vérifier le SHA exact de origin/main.' }
    $head = (& git -C $RepositoryRoot rev-parse HEAD).Trim().ToLowerInvariant()
    $remote = (& git -C $RepositoryRoot rev-parse origin/main).Trim().ToLowerInvariant()
    if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') { throw 'SHA local main invalide.' }
    if ($head -ne $remote) { throw "SHA_REFUSED: HEAD=$head origin/main=$remote. Le runner exige le main exact publié." }
    return $head
}

function Set-PaperOnlyMachineGuards {
    $values = [ordered]@{
        HL_ENABLE_MAINNET_EXECUTION = '0'
        HL_ENABLE_TESTNET_EXECUTION = '0'
        REAL_MAINNET_TRADING = 'false'
        TESTNET_EXECUTION_ENABLED = 'false'
        HYPERSMART_ENABLE_REAL_ORDERS = '0'
        ENABLE_REAL_ORDERS = '0'
        HYPERSMART_ANALYSIS_LOCAL_ONLY = '1'
    }
    foreach ($entry in $values.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable([string]$entry.Key, [string]$entry.Value, 'Machine')
        Set-Item -Path ("Env:" + [string]$entry.Key) -Value ([string]$entry.Value)
    }
}

function Write-PreparationManifest(
    [string]$Root,
    [string]$RepositoryRoot,
    [string]$ProjectSha,
    [string]$ResearchRoot,
    [string]$Label,
    [string]$Name,
    [bool]$Configured
) {
    $path = Join-Path $Root 'HYPERSMART_RUNNER_PREPARED.json'
    $tmp = "$path.$PID.tmp"
    $payload = [ordered]@{
        schema = 'hypersmart.runner_preparation.v1'
        prepared_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
        repository = $Repository
        project_root = $RepositoryRoot
        project_sha = $ProjectSha
        branch = 'main'
        runner_root = $Root
        runner_workspace = (Join-Path $Root '_work')
        runner_name = $Name
        research_root = $ResearchRoot
        required_label = $Label
        configured = $Configured
        paper_only = $true
        read_only_mainnet = $true
        real_execution = $false
        testnet_execution = $false
    }
    $payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $path -Force
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
    foreach ($dir in @('', 'datasets', 'datasets\assets', 'datasets\metadata', 'datasets\materialized', 'datasets\workspaces', 'jobs', 'jobs\requests', 'results', 'results\jobs', 'results\github', 'job_logs', 'status', 'checkpoints', 'tools', 'runtime')) {
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
    $escapedRoot = [Regex]::Escape([System.IO.Path]::GetFullPath($Root).TrimEnd('\'))
    $serviceFile = Join-Path $Root '.service'
    if (Test-Path $serviceFile -PathType Leaf) {
        $serviceName = (Get-Content $serviceFile -Raw -Encoding UTF8).Trim()
        if (-not [string]::IsNullOrWhiteSpace($serviceName)) {
            $info = Get-CimInstance Win32_Service -Filter "Name='$serviceName'" -ErrorAction SilentlyContinue
            if ($info -and [string]$info.PathName -match $escapedRoot) {
                return Get-Service -Name $serviceName -ErrorAction SilentlyContinue
            }
        }
    }
    $info = Get-CimInstance Win32_Service -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -like 'actions.runner.*' -and
            [string]$_.PathName -match $escapedRoot -and
            ($_.Name -like "*$ExpectedRunnerName*" -or $_.DisplayName -like "*$ExpectedRunnerName*")
        } |
        Select-Object -First 1
    if ($info) { return Get-Service -Name $info.Name -ErrorAction SilentlyContinue }
    return $null
}

function Configure-ServiceRecovery([System.ServiceProcess.ServiceController]$Service) {
    Set-Service -Name $Service.Name -StartupType Automatic
    & sc.exe failure $Service.Name 'reset=' 86400 'actions=' 'restart/60000/restart/60000/restart/300000' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Configuration de reprise du service impossible.' }
    & sc.exe failureflag $Service.Name 1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Activation failureflag impossible.' }
}

function Set-CanonicalNetworkServiceIdentity([System.ServiceProcess.ServiceController]$Service) {
    $info = Get-CimInstance Win32_Service -Filter "Name='$($Service.Name)'" -ErrorAction Stop
    if ([string]$info.StartName -cne 'NT AUTHORITY\NetworkService') {
        & sc.exe config $Service.Name 'obj=' 'NT AUTHORITY\NetworkService' 'password=' '' | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw 'Correction du compte NetworkService canonique impossible.'
        }
    }
}

Assert-Admin
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git for Windows est obligatoire.' }
$repoRoot = if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
} else {
    (Resolve-Path -LiteralPath $ProjectRoot).Path
}
$basePython = Get-BasePython311 -RepositoryRoot $repoRoot
$projectSha = Get-ExactMainSha -RepositoryRoot $repoRoot
if ([string]::IsNullOrWhiteSpace($LabRoot)) {
    $existingLab = [Environment]::GetEnvironmentVariable('ALINA_RESEARCH_HOME', 'Machine')
    $LabRoot = if ([string]::IsNullOrWhiteSpace($existingLab)) {
        'C:\HyperSmart-Runner-Data'
    } else { $existingLab }
}
if ([string]::IsNullOrWhiteSpace($RunnerName)) { $RunnerName = 'HyperSmart-FinalV1-' + $env:COMPUTERNAME }
$LabRoot = [System.IO.Path]::GetFullPath($LabRoot)
$RunnerRoot = [System.IO.Path]::GetFullPath($RunnerRoot)
$repoPrefix = $repoRoot.TrimEnd('\') + '\'
if ($RunnerRoot.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'RUNNER_WORKSPACE_REFUSED: le runner doit rester hors du dépôt de développement.'
}
if ($LabRoot.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'RUNNER_DATA_ROOT_REFUSED: ALINA_RESEARCH_HOME doit rester hors du dépôt de développement.'
}
$labDriveId = [System.IO.Path]::GetPathRoot($LabRoot).TrimEnd('\')
$labDrive = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$labDriveId'" -ErrorAction Stop
if (-not $labDrive -or [double]$labDrive.FreeSpace / 1GB -lt 25) {
    throw "Moins de 25 Gio libres sur le disque du laboratoire: $labDriveId"
}

Write-Step 'Préflight runner final isolé des anciennes files'
Write-Host "Repository           : $Repository"
Write-Host "RunnerName           : $RunnerName"
Write-Host "RunnerRoot           : $RunnerRoot"
Write-Host "Project SHA exact    : $projectSha"
Write-Host "ALINA_RESEARCH_HOME  : $LabRoot"
Write-Host "Label final          : $FinalLabel"
Write-Host 'Ancien label hypersmart: volontairement ABSENT' -ForegroundColor Green
Write-Host 'Trading réel         : BLOQUÉ' -ForegroundColor Green
Write-Host ("Disque laboratoire   : {0} | libre {1:N2} Gio" -f $labDrive.DeviceID, ([double]$labDrive.FreeSpace / 1GB))

Initialize-Lab -Root $LabRoot -RepositoryRoot $repoRoot
$runnerPython = Initialize-RunnerPython -Root $LabRoot -BasePython $basePython -RepositoryRoot $repoRoot
Set-PaperOnlyMachineGuards
$configured = Test-Path (Join-Path $RunnerRoot '.runner') -PathType Leaf
if (-not (Test-Path (Join-Path $RunnerRoot 'config.cmd') -PathType Leaf)) {
    Download-LatestRunner -TargetRoot $RunnerRoot
}
Write-PreparationManifest -Root $RunnerRoot -RepositoryRoot $repoRoot -ProjectSha $projectSha -ResearchRoot $LabRoot -Label $FinalLabel -Name $RunnerName -Configured $configured
if ($PrepareOnly) {
    Write-Host ''
    Write-Host 'PRÉPARATION RUNNER : OK — aucun enregistrement GitHub et aucun service démarré.' -ForegroundColor Green
    Write-Host "Runner prêt à enregistrer : $RunnerRoot" -ForegroundColor Cyan
    Write-Host "SHA main verrouillé       : $projectSha" -ForegroundColor Cyan
    exit 0
}
if (-not $configured) {
    Write-Step 'Enregistrement du runner final avec label isolé'
    $temporaryRunnerToken = Get-RegistrationToken -Repo $Repository -ExplicitToken $RunnerToken
    $configExitCode = 0
    try {
        Push-Location $RunnerRoot
        & .\config.cmd --unattended --url "https://github.com/$Repository" --token $temporaryRunnerToken --name $RunnerName --labels "$FinalLabel,alina" --work '_work' --runasservice --windowslogonaccount 'NT AUTHORITY\NetworkService' --replace
        $configExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
        $temporaryRunnerToken = $null
        $RunnerToken = $null
    }
    if ($configExitCode -ne 0) {
        $registeredService = Get-ConfiguredService -Root $RunnerRoot -ExpectedRunnerName $RunnerName
        if (-not $registeredService) {
            throw "config.cmd final a échoué avec le code $configExitCode sans enregistrer de service récupérable."
        }
        Write-Warning "config.cmd a enregistré le service mais son démarrage a échoué (code $configExitCode) ; réparation canonique en cours."
    }
} else {
    Write-Host 'Runner final déjà configuré dans son dossier dédié.' -ForegroundColor Green
}

Write-PreparationManifest -Root $RunnerRoot -RepositoryRoot $repoRoot -ProjectSha $projectSha -ResearchRoot $LabRoot -Label $FinalLabel -Name $RunnerName -Configured $true

$service = Get-ConfiguredService -Root $RunnerRoot -ExpectedRunnerName $RunnerName
if (-not $service) { throw 'Service du runner FINAL_V1 introuvable.' }
Set-CanonicalNetworkServiceIdentity -Service $service
Configure-ServiceRecovery -Service $service
if ($service.Status -ne 'Running') {
    Start-Service -Name $service.Name
    $service = Get-Service -Name $service.Name
}
if ($service.Status -ne 'Running') { throw "Service final non démarré: $($service.Status)" }

$verifier = Join-Path $repoRoot 'tools\VERIFIER_ALINA_RUNNER_WINDOWS.ps1'
if (-not (Test-Path -LiteralPath $verifier -PathType Leaf)) {
    throw "VERIFICATEUR_FINAL_ABSENT: $verifier"
}
Write-Step 'Diagnostic final fail-closed du runner enregistré'
& $verifier -LabRoot $LabRoot -RunnerRoot $RunnerRoot -ProjectRoot $repoRoot -RequiredLabel $FinalLabel
if ($LASTEXITCODE -ne 0) {
    throw "RUNNER_FINAL_NON_PRET: le diagnostic final a échoué avec le code $LASTEXITCODE"
}

Write-Host ''
Write-Host 'ALINA SELF-HOSTED FINAL V1 : PRÊT' -ForegroundColor Green
Write-Host "Service             : $($service.Name) / $($service.Status)" -ForegroundColor Green
Write-Host "Labels requis       : self-hosted, Windows, X64, $FinalLabel" -ForegroundColor Cyan
Write-Host "ALINA_RESEARCH_HOME : $LabRoot" -ForegroundColor Cyan
Write-Host "ALINA_PYTHON_EXE    : $runnerPython" -ForegroundColor Cyan
Write-Host 'Les anciens jobs exigeant le label hypersmart ne peuvent pas utiliser ce runner.' -ForegroundColor Yellow
Write-Host 'Le workflow final refusera aussi tout SHA qui n est plus HEAD de main.' -ForegroundColor Yellow
