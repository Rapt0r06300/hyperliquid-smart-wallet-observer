param(
    [int]$Port = 8794,
    [int]$IntervalSeconds = 15,
    [int]$MaxLeaders = 50,
    [bool]$RestartExisting = $true,
    [switch]$Interactive
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$Url = "http://127.0.0.1:$Port/static/simulation_v2.html?v=stable-screen-20260619b"
$ApiUrl = "http://127.0.0.1:$Port/api/simulation/overview"
$logDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$runtimeDataDir = Join-Path $Root "runtime\data"
New-Item -ItemType Directory -Force -Path $runtimeDataDir | Out-Null
$sessionDbPath = Join-Path $runtimeDataDir "hypersmart_simulation_session.sqlite3"
$sessionDbUrl = "sqlite:///" + ($sessionDbPath -replace "\\", "/")
$engineStatusPath = Join-Path $runtimeDataDir "hypersmart_engine_status.json"
$v12SqlitePath = Join-Path $runtimeDataDir "hypersmart_v12_artifacts.sqlite3"
$logsToSendDir = Join-Path $logDir ("logs " + [char]0x00E0 + " envoyer")
New-Item -ItemType Directory -Force -Path $logsToSendDir | Out-Null
$launcherLog = Join-Path $logDir "hypersmart_launcher.log"
$uiStdoutLog = Join-Path $logDir "hypersmart_ui_stdout.log"
$uiStderrLog = Join-Path $logDir "hypersmart_ui_stderr.log"
$pollerStdoutLog = Join-Path $logDir "hypersmart_poller_stdout.log"
$pollerStderrLog = Join-Path $logDir "hypersmart_poller_stderr.log"
$startedProcesses = New-Object System.Collections.Generic.List[int]
$uiProcessId = $null
$pollProcessId = $null

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

function Set-HyperSmartDefaultEnv {
    param(
        [string]$Name,
        [string]$Value
    )
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($Name, "Process"))) {
        [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
    }
}

$env:PYTHONPATH = (Join-Path $Root "src") + ";" + $env:PYTHONPATH
$env:HL_ENV = "paper"
$env:HL_DATABASE_URL = $sessionDbUrl
$env:HL_ENABLE_MAINNET_EXECUTION = "0"
$env:HL_ENABLE_TESTNET_EXECUTION = "0"
$env:HYPERSMART_V12_SQLITE_PATH = $v12SqlitePath
$env:HYPERSMART_MODE = "SIMULATION_ONLY_UNTIL_MANUAL_REVIEW"
Set-HyperSmartDefaultEnv "HYPERSMART_V13_MODEL_PATH" (Join-Path $Root "runtime\models\trade_model_v13.json")
Set-HyperSmartDefaultEnv "HYPERSMART_V13_MODEL_REPORT" (Join-Path $Root "runtime\models\trade_model_v13.json.report.json")
Set-HyperSmartDefaultEnv "HYPERSMART_V13_SAMPLES_PATH" (Join-Path $Root "runtime\ml\training_samples.jsonl")
Set-HyperSmartDefaultEnv "HYPERSMART_SLTP_ENABLED" "1"
Set-HyperSmartDefaultEnv "HYPERSMART_SLTP_TAKE_PROFIT_BPS" "85"
Set-HyperSmartDefaultEnv "HYPERSMART_SLTP_STOP_LOSS_BPS" "30"
Set-HyperSmartDefaultEnv "HYPERSMART_SLTP_TRAILING_BPS" "30"
Set-HyperSmartDefaultEnv "HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS" "55"
Set-HyperSmartDefaultEnv "HYPERSMART_SLTP_BREAKEVEN_BUFFER_BPS" "8"
Set-HyperSmartDefaultEnv "HYPERSMART_ADAPTIVE_PAPER_SIZING" "1"
Set-HyperSmartDefaultEnv "HYPERSMART_POSITIVE_PNL_REQUIRED_FOR_FUTURE_REVIEW" "1"
Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_INTERVAL_SECONDS" "$IntervalSeconds"
# Reglages SELECTIFS calibres sur les logs reels: Hyperliquid paper local,
# signaux frais uniquement, mais sans affamer le moteur avec un seuil impossible.
Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS" "15000"
Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_ALLOW_ADD_AS_ENTRY" "1"
Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_MIN_EDGE_BPS" "15"
Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE" "0.22"
Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS" "40"
Set-HyperSmartDefaultEnv "HYPERSMART_MAX_OPEN_POSITIONS" "60"
Set-HyperSmartDefaultEnv "HYPERSMART_MAX_POSITION_USDT" "40"
Set-HyperSmartDefaultEnv "HYPERSMART_MAX_TOTAL_EXPOSURE_USDT" "1200"
Set-HyperSmartDefaultEnv "HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS" "28"
Set-HyperSmartDefaultEnv "HYPERSMART_V12_GATE_AUTHORITATIVE" "1"
Set-HyperSmartDefaultEnv "HYPERSMART_V14_CONSENSUS_WINDOW_AUTHORITATIVE" "1"
Set-HyperSmartDefaultEnv "HYPERSMART_V14_EXEC_COST_AUTHORITATIVE" "1"
Set-HyperSmartDefaultEnv "HYPERSMART_V14_ENTRY_QUALITY_AUTHORITATIVE" "0"
Set-HyperSmartDefaultEnv "HYPERSMART_STATUS_LIVE_MARKS_ENABLED" "1"
Set-HyperSmartDefaultEnv "HL_LOG_LEVEL" "WARNING"

function Test-CommandCenter {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $ApiUrl -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Test-ProcessAlive {
    param([Nullable[int]]$ProcessId)
    if ($null -eq $ProcessId) {
        return $false
    }
    try {
        return $null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
    } catch {
        return $false
    }
}

function Write-LauncherLine {
    param([string]$Message)
    Write-Host "[HyperSmart] $Message"
    Write-LauncherLog $Message
}

function Write-LauncherEngineStatus {
    param(
        [string]$Phase,
        [string]$Message
    )
    try {
        $payload = [ordered]@{
            updated_at_ms = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
            phase = $Phase
            message = $Message
            poll_index = 0
            max_runs = 5760
            pool = $MaxLeaders
            leaders_per_poll = 10
            read_only = $true
            simulation_only = $true
            external_action = $false
            metrics = [ordered]@{
                launcher_visible = "true"
                ui_port = "$Port"
                startup_guard = "active"
                runtime_venue = "Hyperliquid"
                paper_engine = "local_only"
                v12_sqlite_path = "$env:HYPERSMART_V12_SQLITE_PATH"
                sltp_enabled = "$env:HYPERSMART_SLTP_ENABLED"
            }
        }
        $payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $engineStatusPath -Encoding UTF8
    } catch {
        Write-LauncherLog "launcher engine status write failed: $($_.Exception.Message)"
    }
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
Write-LauncherEngineStatus "launcher_starting" "Lanceur visible actif; serveur UI et poller en preparation."
Write-Host "Dashboard: $Url"
Write-Host "Logs: $launcherLog"
Write-Host "DB session simulation: $sessionDbPath"
Write-Host "V12 store: $v12SqlitePath"
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
    if ($env:HYPERSMART_RESET_ON_LAUNCH -eq "1") {
        $resetOutput = & python -m hl_observer reset-simulation-state --starting-equity 1000 2>&1
        foreach ($line in $resetOutput) { Write-LauncherLog $line }
        Write-LauncherLine "Capital virtuel REMIS a 1000 USDT (reset force: HYPERSMART_RESET_ON_LAUNCH=1)."
    } else {
        Write-LauncherLine "Capital virtuel CONSERVE entre lancements: l equity persiste pour voir l accumulation du PnL. Mettre HYPERSMART_RESET_ON_LAUNCH=1 pour repartir de 1000."
    }
    Write-LauncherLine "Nouvelle session simulation: moteur Hyperliquid read-only + paper local actif."
    $prepareLogsOutput = & python -m hl_observer prepare-simulation-logs 2>&1
    foreach ($line in $prepareLogsOutput) { Write-LauncherLog $line }
    Write-LauncherLine "Logs a envoyer prepares: session fraiche, anciens fichiers deplaces dans _archives."
    Write-LauncherLine "Nouvelle session de logs preparee (l equity suit HYPERSMART_RESET_ON_LAUNCH; persiste par defaut)."
    Write-LauncherLine "Decouverte read-only des marches Hyperliquid pour scanner davantage de coins."
    $marketsOutput = & python -m hl_observer discover-markets --store --max-coins 80 2>&1
    foreach ($line in $marketsOutput) { Write-LauncherLog $line }
    Write-LauncherLine "Scan L2/candles read-only des marches Hyperliquid pour les gates de liquidite."
    $marketScanOutput = & python -m hl_observer scan-markets --all --store --max-coins 80 --l2book --candles 2>&1
    foreach ($line in $marketScanOutput) { Write-LauncherLog $line }
    Write-LauncherLine "Elargissement read-only MASSIF de la shortlist de leaders (scan large = plus d'opportunites qualifiees)."
    try {
        $walletsOutput = & python -m hl_observer.collection.run_collect_all --max-coins 200 --target 6000 2>&1
        foreach ($line in $walletsOutput) { Write-LauncherLog $line }
    } catch {
        Write-LauncherLog "collect-all (elargissement wallets) non bloquant: $($_.Exception.Message)"
    }
    Write-LauncherLine "Warm scan WebSocket public Hyperliquid: detection immediate de wallets actifs avant l'ouverture de l'UI."
    Write-LauncherEngineStatus "startup_public_trade_scan" "Warm scan public read-only pour alimenter les premiers slots userFills."
    try {
        $warmPublicScanOutput = & python -m hl_observer live-public-scan --network-read --store --duration-seconds 6 --coins AUTO --max-coins 60 --max-wallets 20000 --promote-top $MaxLeaders --no-report 2>&1
        foreach ($line in $warmPublicScanOutput) { Write-LauncherLog $line }
    } catch {
        Write-LauncherLog "warm live-public-scan non bloquant: $($_.Exception.Message)"
    }
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
        $uiProcessId = [int]$uiProcess.Id
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
        "-PublicTradeMaxCoins", "60",
        "-PublicTradeScanSeconds", "8",
        "-PublicTradeMaxWallets", "10000",
        "-PublicTradeScanEveryPolls", "1",
        "-UserFillsMaxLiveAgeMs", "20000",
        "-MaxRuns", "5760"
    ) -join " "
    $pollProcess = Start-Process -NoNewWindow -PassThru -FilePath "powershell" -ArgumentList $pollArguments -WorkingDirectory $Root -RedirectStandardOutput $pollerStdoutLog -RedirectStandardError $pollerStderrLog
    if ($pollProcess -and $pollProcess.Id) {
        $pollProcessId = [int]$pollProcess.Id
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

if (-not (Test-CommandCenter)) {
    Write-LauncherLine "ALERTE: serveur UI local ne repond pas encore sur $ApiUrl. Regarde $uiStderrLog."
}

if ($null -ne $uiProcessId -and -not (Test-ProcessAlive -ProcessId $uiProcessId)) {
    Write-LauncherLine "ALERTE: le serveur UI s'est arrete juste apres le lancement. Regarde $uiStderrLog."
}

if ($null -ne $pollProcessId -and -not (Test-ProcessAlive -ProcessId $pollProcessId)) {
    Write-LauncherLine "ALERTE: le poller simulation s'est arrete juste apres le lancement. Regarde $pollerStderrLog et $pollerStdoutLog."
}

Write-LauncherLine "Ouverture du dashboard $Url"
Start-Process $Url

if ($Interactive) {
    Write-Host ""
    Write-Host "HyperSmart tourne en simulation locale."
    Write-Host "- Appuie sur Q puis Entree pour arreter proprement."
    Write-Host "- Appuie sur R puis Entree pour afficher un statut rapide."
    Write-Host "- Cette fenetre est le moteur: si elle se ferme, Chrome reste ouvert mais le scan s'arrete."
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
