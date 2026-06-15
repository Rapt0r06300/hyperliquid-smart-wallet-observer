param(
    [int]$Port = 8794,
    [int]$IntervalSeconds = 15,
    [int]$MaxLeaders = 50,
    [bool]$RestartExisting = $true,
    [switch]$Interactive
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$Url = "http://127.0.0.1:$Port/static/simulation_v2.html?v=scan5"
$ApiUrl = "http://127.0.0.1:$Port/api/simulation/overview"
$logDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$runtimeDataDir = Join-Path $Root "runtime\data"
New-Item -ItemType Directory -Force -Path $runtimeDataDir | Out-Null
$sessionDbPath = Join-Path $runtimeDataDir "hypersmart_simulation_session.sqlite3"
$sessionDbUrl = "sqlite:///" + ($sessionDbPath -replace "\\", "/")
$logsToSendDir = Join-Path $logDir "logs à envoyer"
New-Item -ItemType Directory -Force -Path $logsToSendDir | Out-Null
$launcherLog = Join-Path $logDir "hypersmart_launcher.log"
$uiStdoutLog = Join-Path $logDir "hypersmart_ui_stdout.log"
$uiStderrLog = Join-Path $logDir "hypersmart_ui_stderr.log"
$pollerStdoutLog = Join-Path $logDir "hypersmart_poller_stdout.log"
$pollerStderrLog = Join-Path $logDir "hypersmart_poller_stderr.log"
$startedProcesses = New-Object System.Collections.Generic.List[int]

function Write-LauncherLog {
    param([string]$Message)
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    try {
        Add-Content -LiteralPath $launcherLog -Value "[$stamp] $Message" -ErrorAction Stop
    } catch {
        Write-Host "[HyperSmart][log-warning] launcher log unavailable: $($_.Exception.Message)"
    }
}

function Test-DirectoryWritable {
    param([string]$Path)
    try {
        New-Item -ItemType Directory -Force -Path $Path -ErrorAction Stop | Out-Null
        $probe = Join-Path $Path (".hypersmart_launcher_probe_" + [guid]::NewGuid().ToString("N") + ".tmp")
        Set-Content -LiteralPath $probe -Value "probe" -Encoding UTF8 -ErrorAction Stop
        Remove-Item -LiteralPath $probe -Force -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

$env:PYTHONPATH = (Join-Path $Root "src") + ";" + $env:PYTHONPATH
$env:HL_ENV = "paper"
$env:HL_DATABASE_URL = $sessionDbUrl
$env:HL_ENABLE_MAINNET_EXECUTION = "0"
$env:HL_ENABLE_TESTNET_EXECUTION = "0"
$env:HYPERSMART_MODE = "SIMULATION_ONLY_UNTIL_MANUAL_REVIEW"
$env:HYPERSMART_POSITIVE_PNL_REQUIRED_FOR_FUTURE_REVIEW = "1"
$env:HYPERSMART_SIMULATION_INTERVAL_SECONDS = "$IntervalSeconds"
# Reglages SELECTIFS (2026-06-12): stopper les trades perdants par construction.
# Edge net minimum > cout aller-retour (~17 bps), fraicheur stricte, pas d'ADD
# comme entree, marches liquides seulement. Objectif: moins de trades, plus propres.
$env:HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS = "6000"
$env:HYPERSMART_SIMULATION_ALLOW_ADD_AS_ENTRY = "0"
$env:HYPERSMART_SIMULATION_MIN_EDGE_BPS = "35"
$env:HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE = "0.5"
$env:HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS = "12"
$env:HL_LOG_LEVEL = "WARNING"

# Dependance du flux temps reel (WebSocket public dYdX). Installee une fois,
# silencieusement, pour que le scan temps reel des wallets fonctionne.
try { python -m pip install --quiet websocket-client 2>$null | Out-Null } catch {}

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
                ($_.CommandLine -like "*hl_observer live-user-fills-scan*--network-read*") -or
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
Write-Host "DB session simulation: $sessionDbPath"
Write-Host "Logs à envoyer: $logsToSendDir"
Write-Host "UI logs: $uiStdoutLog / $uiStderrLog"
Write-Host "Poller logs: $pollerStdoutLog / $pollerStderrLog"
Write-Host "Aucun ordre reel. Aucun mainnet. Testnet verrouille."
Write-LauncherLine "DB session simulation active: $sessionDbPath"

$logsToSendWritable = Test-DirectoryWritable -Path $logsToSendDir
if (-not $logsToSendWritable) {
    Write-LauncherLine "ALERTE: logs à envoyer non inscriptible. Le PnL/metagraphe peut rester fige tant que ce dossier ou ses fichiers sont verrouilles."
    Write-Host "Action propre: fermer les anciennes fenetres HyperSmart, puis relancer ce lanceur. Aucun processus n'est tue pour resoudre ce verrou."
} else {
    Write-LauncherLine "Diagnostic runtime: logs à envoyer inscriptible."
}

try {
    Push-Location $Root
    $writeCheckOutput = & python -m hl_observer runtime-write-check --from-logs "$logsToSendDir" --stale-after-seconds 60 2>&1
    foreach ($line in $writeCheckOutput) { Write-LauncherLog $line }
    $readinessOutput = & python -m hl_observer simulation-readiness --from-logs "$logsToSendDir" --fresh-window-seconds 120 2>&1
    foreach ($line in $readinessOutput) { Write-LauncherLog $line }
    Pop-Location
} catch {
    Write-LauncherLog "runtime diagnostics failed: $($_.Exception.Message)"
    try { Pop-Location } catch {}
}

if ($RestartExisting) {
    try {
        $stale = @(Get-HyperSmartRuntimeProcesses)
        foreach ($process in $stale) {
            Write-LauncherLine "Arret ancien processus HyperSmart pid=$($process.ProcessId)"
            Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        }
        for ($wait = 0; $wait -lt 30; $wait++) {
            $remaining = @(Get-HyperSmartRuntimeProcesses)
            if ($remaining.Count -eq 0) {
                break
            }
            Write-LauncherLog "Waiting for old HyperSmart runtime processes to exit: $($remaining.Count) remaining"
            Start-Sleep -Milliseconds 500
        }
    } catch {
        Write-LauncherLog "stale process cleanup skipped: $($_.Exception.Message)"
    }
}

try {
    Push-Location $Root
    $initOutput = & python -m hl_observer init-db 2>&1
    foreach ($line in $initOutput) { Write-LauncherLog $line }
    $resetOutput = & python -m hl_observer reset-simulation-state --starting-equity 1000 2>&1
    foreach ($line in $resetOutput) { Write-LauncherLog $line }
    # Archiver les anciens journaux de decisions (runs precedents) -> tableau propre,
    # plus de -112.89 historique qui tracte. Recherche recursive (evite l'accent du dossier).
    try {
        $patterns = @("*decisions_append_only.jsonl", "*decisions_latest.jsonl", "*log_summary_cache.json")
        foreach ($pat in $patterns) {
            $olds = Get-ChildItem -Path (Join-Path $Root "logs") -Recurse -Filter $pat -ErrorAction SilentlyContinue
            foreach ($jf in $olds) {
                $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
                Move-Item -Path $jf.FullName -Destination (Join-Path $jf.DirectoryName ("archive_" + $stamp + "_" + $jf.Name)) -ErrorAction SilentlyContinue
            }
        }
        Write-LauncherLine "Anciens journaux de decisions archives: depart propre pour ce lancement."
    } catch { }
    Write-LauncherLine "Nouvelle session simulation: capital virtuel remis a 1000 USDT pour ce lancement."
    Write-LauncherLine "Decouverte read-only des marches Hyperliquid pour scanner davantage de coins."
    $marketsOutput = & python -m hl_observer discover-markets --store --max-coins 80 2>&1
    foreach ($line in $marketsOutput) { Write-LauncherLog $line }
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
    ) -WorkingDirectory $Root -RedirectStandardOutput $uiStdoutLog -RedirectStandardError $uiStderrLog
    if ($uiProcess -and $uiProcess.Id) {
        $startedProcesses.Add([int]$uiProcess.Id) | Out-Null
    }
}

$pollerAlreadyRunning = $false
try {
    $pollers = Get-CimInstance Win32_Process | Where-Object {
        ($_.CommandLine -like "*hypersmart_simulation_poll_loop.ps1*") -or
        ($_.CommandLine -like "*hl_observer copy-run*--network-read*") -or
        ($_.CommandLine -like "*hl_observer live-user-fills-scan*--network-read*")
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
        "-LeadersPerPoll", "10",
        "-BackfillDays", "1",
        "-FreshWindowMinutes", "1",
        "-MaxPages", "1",
        "-PublicTradeCoins", "AUTO",
        "-PublicTradeMaxCoins", "40",
        "-PublicTradeScanSeconds", "10",
        "-PublicTradeMaxWallets", "10000",
        "-PublicTradeScanEveryPolls", "1",
        "-UserFillsMaxLiveAgeMs", "120000"
    ) -join " "
    $pollProcess = Start-Process -NoNewWindow -PassThru -FilePath "powershell" -ArgumentList $pollArguments -WorkingDirectory $Root -RedirectStandardOutput $pollerStdoutLog -RedirectStandardError $pollerStderrLog
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
