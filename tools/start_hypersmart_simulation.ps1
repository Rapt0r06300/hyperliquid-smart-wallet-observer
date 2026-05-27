param(
    [int]$Port = 8792,
    [int]$IntervalSeconds = 60,
    [int]$MaxLeaders = 50,
    [bool]$RestartExisting = $true,
    [switch]$Interactive
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$Url = "http://127.0.0.1:$Port/#simulationPanel"
$ApiUrl = "http://127.0.0.1:$Port/api/simulation/overview"
$logDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$launcherLog = Join-Path $logDir "hypersmart_launcher.log"
$startedProcesses = New-Object System.Collections.Generic.List[int]

function Write-LauncherLog {
    param([string]$Message)
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $launcherLog -Value "[$stamp] $Message"
}

$env:PYTHONPATH = (Join-Path $Root "src") + ";" + $env:PYTHONPATH
$env:HL_ENV = "paper"
$env:HL_ENABLE_MAINNET_EXECUTION = "0"
$env:HL_ENABLE_TESTNET_EXECUTION = "0"
$env:HYPERSMART_MODE = "SIMULATION_ONLY_UNTIL_MANUAL_REVIEW"
$env:HYPERSMART_POSITIVE_PNL_REQUIRED_FOR_FUTURE_REVIEW = "1"

function Test-CommandCenter {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $ApiUrl -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Write-LauncherLine {
    param([string]$Message)
    Write-Host "[HyperSmart] $Message"
    Write-LauncherLog $Message
}

function Get-HyperSmartRuntimeProcesses {
    try {
        $ownPid = $PID
        return Get-CimInstance Win32_Process | Where-Object {
            $_.ProcessId -ne $ownPid -and (
                ($_.CommandLine -like "*python* -m hl_observer ui*") -or
                ($_.CommandLine -like "*hypersmart_simulation_poll_loop.ps1*") -or
                ($_.CommandLine -like "*hl_observer copy-run*--network-read*") -or
                ($_.CommandLine -like "*hl_observer live-public-scan*--network-read*")
            )
        }
    } catch {
        Write-LauncherLog "runtime process lookup skipped: $($_.Exception.Message)"
        return @()
    }
}

function Stop-HyperSmartRuntime {
    param([string]$Reason = "manual_stop")
    Write-LauncherLine "Arret local demande ($Reason). Fermeture du serveur UI et du poller read-only..."
    $runtimeProcesses = @(Get-HyperSmartRuntimeProcesses)
    foreach ($process in $runtimeProcesses) {
        try {
            Write-LauncherLog "Stopping HyperSmart runtime pid=$($process.ProcessId)"
            Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        } catch {
            Write-LauncherLog "Stop skipped for pid=$($process.ProcessId): $($_.Exception.Message)"
        }
    }
}

Write-LauncherLine "Lanceur visible actif. port=$Port interval=$IntervalSeconds maxLeaders=$MaxLeaders mode=SIMULATION_ONLY"
Write-Host "Dashboard: $Url"
Write-Host "Logs: $launcherLog"
Write-Host "Aucun ordre reel. Aucun mainnet. Testnet verrouille."

if ($RestartExisting) {
    try {
        $stale = @(Get-HyperSmartRuntimeProcesses)
        foreach ($process in $stale) {
            Write-LauncherLine "Arret ancien processus HyperSmart pid=$($process.ProcessId)"
            Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        }
    } catch {
        Write-LauncherLog "stale process cleanup skipped: $($_.Exception.Message)"
    }
}

try {
    Push-Location $Root
    $initOutput = & python -m hl_observer init-db 2>&1
    foreach ($line in $initOutput) { Write-LauncherLog $line }
    Pop-Location
} catch {
    Write-LauncherLog "init-db failed: $($_.Exception.Message)"
    try { Pop-Location } catch {}
}

if (-not (Test-CommandCenter)) {
    Write-LauncherLine "Demarrage du serveur UI local sur $Url"
    $uiProcess = Start-Process -NoNewWindow -PassThru -FilePath "python" -ArgumentList @(
        "-m", "hl_observer", "ui",
        "--host", "127.0.0.1",
        "--port", "$Port"
    ) -WorkingDirectory $Root
    if ($uiProcess -and $uiProcess.Id) {
        $startedProcesses.Add([int]$uiProcess.Id) | Out-Null
    }
}

$pollerAlreadyRunning = $false
try {
    $pollers = Get-CimInstance Win32_Process | Where-Object {
        ($_.CommandLine -like "*hypersmart_simulation_poll_loop.ps1*") -or
        ($_.CommandLine -like "*hl_observer copy-run*--network-read*")
    }
    $pollerAlreadyRunning = @($pollers).Count -gt 0
} catch {
    $pollerAlreadyRunning = $false
}

if (-not $pollerAlreadyRunning) {
    Write-LauncherLine "Demarrage du poller simulation read-only. Rotation leaders en lots bornes."
    $pollScript = Join-Path $PSScriptRoot "hypersmart_simulation_poll_loop.ps1"
    $pollArguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$pollScript`"",
        "-Root", "`"$Root`"",
        "-IntervalSeconds", "$IntervalSeconds",
        "-MaxLeaders", "$MaxLeaders",
        "-LeadersPerPoll", "5",
        "-BackfillDays", "1",
        "-FreshWindowMinutes", "15",
        "-MaxPages", "1",
        "-PublicTradeScanSeconds", "20",
        "-PublicTradeMaxWallets", "1500"
    ) -join " "
    $pollProcess = Start-Process -NoNewWindow -PassThru -FilePath "powershell" -ArgumentList $pollArguments -WorkingDirectory $Root
    if ($pollProcess -and $pollProcess.Id) {
        $startedProcesses.Add([int]$pollProcess.Id) | Out-Null
    }
} else {
    Write-LauncherLine "Un poller simulation tourne deja; pas de doublon."
}

for ($i = 0; $i -lt 20; $i++) {
    if (Test-CommandCenter) {
        break
    }
    Start-Sleep -Milliseconds 500
}

Write-LauncherLine "Ouverture du dashboard $Url"
Start-Process $Url

if ($Interactive) {
    Write-Host ""
    Write-Host "HyperSmart tourne en simulation locale."
    Write-Host "- Appuie sur Q puis Entree pour arreter proprement."
    Write-Host "- Appuie sur R puis Entree pour afficher un statut rapide."
    Write-Host "- Evite de fermer par la croix si tu veux arreter les processus proprement."
    Write-Host ""
    try {
        while ($true) {
            $choice = Read-Host "Commande [R=status, Q=stop]"
            if ($choice -match "^[Qq]") {
                break
            }
            if ($choice -match "^[Rr]") {
                try {
                    $overview = Invoke-RestMethod -Uri $ApiUrl -TimeoutSec 5
                    Write-Host ("PNL={0} USDT Equity={1} Bougies={2} Ledger={3} Entries={4} Exits={5} Refus={6}" -f `
                        $overview.equity.current_pnl_usdc, `
                        $overview.equity.current_equity_usdt, `
                        $overview.equity_candles.Count, `
                        $overview.simulation_ledger_events_count, `
                        $overview.counts.reproduced_entries, `
                        $overview.counts.reproduced_exits, `
                        $overview.counts.bot_refused)
                } catch {
                    Write-Host "Status indisponible: $($_.Exception.Message)"
                }
            }
        }
    } finally {
        Stop-HyperSmartRuntime -Reason "launcher_exit"
        Write-Host "Arret termine. Tu peux fermer cette fenetre."
        Start-Sleep -Seconds 2
    }
}
