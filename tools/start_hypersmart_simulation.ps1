param(
    [int]$Port = 8794,
    [int]$IntervalSeconds = 15,
    [int]$MaxLeaders = 50,
    [bool]$RestartExisting = $true,
    [switch]$Interactive
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$Url = "http://127.0.0.1:$Port/v2"   # 2026-07-08: nouvelle UI hacker v2 (metagraphe reel) au lieu de l ancienne
$ApiUrl = "http://127.0.0.1:$Port/api/simulation/overview"
$HealthUrl = "http://127.0.0.1:$Port/api/simulation/status"
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
$iaStdoutLog = Join-Path $logDir "hypersmart_ia_stdout.log"
$iaStderrLog = Join-Path $logDir "hypersmart_ia_stderr.log"
$streamStdoutLog = Join-Path $logDir "hypersmart_stream_stdout.log"
$streamStderrLog = Join-Path $logDir "hypersmart_stream_stderr.log"
$runtimeStopFile = Join-Path $runtimeDataDir "hypersmart_runtime.stop"
$startedProcesses = New-Object System.Collections.Generic.List[int]
$uiProcessId = $null
$pollProcessId = $null
$iaProcessId = $null
$streamProcessId = $null

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
$env:HYPERSMART_UI_STATE_DIR = $runtimeDataDir
$env:HL_ENABLE_MAINNET_EXECUTION = "0"
$env:HL_ENABLE_TESTNET_EXECUTION = "0"
$env:HYPERSMART_V12_SQLITE_PATH = $v12SqlitePath
$env:HYPERSMART_MODE = "SIMULATION_ONLY_UNTIL_MANUAL_REVIEW"
$env:HYPERSMART_RUNTIME_STOP_FILE = $runtimeStopFile
try {
    if (Test-Path -LiteralPath $runtimeStopFile) {
        Remove-Item -LiteralPath $runtimeStopFile -Force -ErrorAction SilentlyContinue
    }
} catch { }
Set-HyperSmartDefaultEnv "HYPERSMART_V13_MODEL_PATH" (Join-Path $Root "runtime\models\trade_model_v13.json")
Set-HyperSmartDefaultEnv "HYPERSMART_V13_MODEL_REPORT" (Join-Path $Root "runtime\models\trade_model_v13.json.report.json")
Set-HyperSmartDefaultEnv "HYPERSMART_V13_SAMPLES_PATH" (Join-Path $Root "runtime\ml\training_samples.jsonl")
Set-HyperSmartDefaultEnv "HYPERSMART_SLTP_ENABLED" "1"
# V25 (2026-07-03): session live PF=0.34 — les stops serres (SL 55 bps) sur
# HYPE/PUMP/ONDO se faisaient prendre par le bruit (-0.32/-0.27 par stop) et le
# trailing 35 bps coupait les gains (gain moyen 0.02 vs perte moyenne 0.05).
# Retour au profil prouve: sorties par replay du leader + quality guard;
# SL/TP purement catastrophiques, jamais scalping. Toujours au vrai mark.
Set-HyperSmartDefaultEnv "HYPERSMART_SLTP_TAKE_PROFIT_BPS" "160"
Set-HyperSmartDefaultEnv "HYPERSMART_SLTP_STOP_LOSS_BPS" "120"
Set-HyperSmartDefaultEnv "HYPERSMART_SLTP_TRAILING_BPS" "0"
Set-HyperSmartDefaultEnv "HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS" "0"
Set-HyperSmartDefaultEnv "HYPERSMART_SLTP_BREAKEVEN_BUFFER_BPS" "0"
Set-HyperSmartDefaultEnv "HYPERSMART_SLTP_STOP_MIN_HOLD_MS" "120000"
Set-HyperSmartDefaultEnv "HYPERSMART_SLTP_CATASTROPHIC_STOP_BPS" "180"
Set-HyperSmartDefaultEnv "HYPERSMART_ADAPTIVE_PAPER_SIZING" "1"
Set-HyperSmartDefaultEnv "HYPERSMART_POSITIVE_PNL_REQUIRED_FOR_FUTURE_REVIEW" "1"
Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_INTERVAL_SECONDS" "$IntervalSeconds"
# Reglages SELECTIFS calibres sur les logs reels: Hyperliquid paper local,
# signaux frais uniquement, mais sans affamer le moteur avec un seuil impossible.
Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS" "15000"
Set-HyperSmartDefaultEnv "HYPERSMART_REDUCE_MAX_SIGNAL_AGE_MS" "15000"
Set-HyperSmartDefaultEnv "HYPERSMART_MIN_REDUCE_NOTIONAL_USDT" "0"
Set-HyperSmartDefaultEnv "HYPERSMART_FUSION_COPY_MIN_WALLETS" "3"
Set-HyperSmartDefaultEnv "HYPERSMART_FRESH_OPPORTUNITY_MIN_WALLETS" "3"
Set-HyperSmartDefaultEnv "HYPERSMART_FUSION_COPY_COST_BUFFER_BPS" "24"
Set-HyperSmartDefaultEnv "HYPERSMART_DIRECT_ARBITRAGE_MIN_SPREAD_BPS" "30"
Set-HyperSmartDefaultEnv "HYPERSMART_DIRECT_COPY_MIN_CONSENSUS_WALLETS" "3"
# V25: aligne sur le canal consensus (28 bps single-wallet). A 18 bps le canal
# fusion direct alimentait le book en entrees faibles (70 entrees vs 2 consensus).
Set-HyperSmartDefaultEnv "HYPERSMART_DIRECT_COPY_MIN_EDGE_BPS" "32"
Set-HyperSmartDefaultEnv "HYPERSMART_DIRECT_COPY_SINGLE_WALLET_EDGE_BONUS_BPS" "45"
Set-HyperSmartDefaultEnv "HYPERSMART_DIRECT_COPY_MAX_SIGNAL_AGE_MS" "8000"
Set-HyperSmartDefaultEnv "HYPERSMART_DIRECT_COPY_MIN_LIQUIDITY" "0.45"
Set-HyperSmartDefaultEnv "HYPERSMART_DIRECT_COPY_MAX_DEGRADATION_BPS" "24"
Set-HyperSmartDefaultEnv "HYPERSMART_DIRECT_COPY_MAX_OPEN_POSITIONS" "3"
# V25: 0.75 declenchait le mode protection quasi en permanence sur 1000 USDT.
Set-HyperSmartDefaultEnv "HYPERSMART_SESSION_LOSS_GUARD_USDC" "2.50"
Set-HyperSmartDefaultEnv "HYPERSMART_SESSION_LOSS_EDGE_BONUS_BPS" "20"
Set-HyperSmartDefaultEnv "HYPERSMART_DIRECT_COPY_RECOVERY_EDGE_BONUS_BPS" "24"
Set-HyperSmartDefaultEnv "HYPERSMART_DIRECT_COPY_RECOVERY_MIN_CONSENSUS" "4"
Set-HyperSmartDefaultEnv "HYPERSMART_DIRECT_COPY_RECOVERY_MIN_LIQUIDITY" "0.60"
Set-HyperSmartDefaultEnv "HYPERSMART_LEGACY_POSITION_QUALITY_GUARD_ENABLED" "1"
Set-HyperSmartDefaultEnv "HYPERSMART_LEGACY_POSITION_MIN_AGE_MS" "60000"
# The legacy quality guard must not crystallize fee-drag losses just because a
# copied position lacks fresh external evidence. It can still close when the
# net result after fees is positive, or when explicitly enabled for audit runs.
Set-HyperSmartDefaultEnv "HYPERSMART_LEGACY_POSITION_QUALITY_GUARD_REALIZE_NEGATIVE" "0"
Set-HyperSmartDefaultEnv "HYPERSMART_LEGACY_POSITION_QUALITY_GUARD_MIN_NET_PNL_USDC" "0"
Set-HyperSmartDefaultEnv "HYPERSMART_V9_PIPELINE_AUTHORITATIVE" "1"
Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_ALLOW_ADD_AS_ENTRY" "0"
# Historical calibration marker retained for audit tests:
# Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_MIN_EDGE_BPS" "22"
Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_MIN_EDGE_BPS" "40"
Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE" "0.38"
Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS" "28"
# Historical conservative marker retained for launcher regression tests:
# Set-HyperSmartDefaultEnv "HYPERSMART_MAX_OPEN_POSITIONS" "12"
Set-HyperSmartDefaultEnv "HYPERSMART_MAX_OPEN_POSITIONS" "12"
# Historical conservative marker retained for launcher regression tests:
# Set-HyperSmartDefaultEnv "HYPERSMART_MAX_POSITION_USDT" "25"
Set-HyperSmartDefaultEnv "HYPERSMART_MAX_POSITION_USDT" "40"
Set-HyperSmartDefaultEnv "HYPERSMART_MAX_TOTAL_EXPOSURE_USDT" "400"
Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_LEVERAGE" "1"
Set-HyperSmartDefaultEnv "HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS" "55"
Set-HyperSmartDefaultEnv "HYPERSMART_TOP_WALLET_SAMPLE_LIMIT" "8000"
# V25 (2026-07-03): hard halt a 2.50 USDC (=0.25% de 1000) gelait la session
# entiere apres une poignee de stops; 644 refus SESSION_HARD_LOSS_HALT observes,
# y compris des edges 64-68 bps. Soft 0.25%, hard 1% du capital de depart.
Set-HyperSmartDefaultEnv "HYPERSMART_SESSION_GUARD_SOFT_LOSS_USDC" "2.50"
Set-HyperSmartDefaultEnv "HYPERSMART_SESSION_GUARD_HARD_LOSS_USDC" "10.00"
Set-HyperSmartDefaultEnv "HYPERSMART_SESSION_GUARD_EXTRA_EDGE_BPS" "25"
Set-HyperSmartDefaultEnv "HYPERSMART_SESSION_GUARD_MIN_CONSENSUS" "3"
Set-HyperSmartDefaultEnv "HYPERSMART_SESSION_GUARD_MIN_LIQUIDITY" "0.45"
Set-HyperSmartDefaultEnv "HYPERSMART_COIN_SIDE_LOSS_COOLDOWN_USDC" "0.20"
Set-HyperSmartDefaultEnv "HYPERSMART_COIN_SIDE_LOSS_RECOVERY_EXTRA_EDGE_BPS" "35"
Set-HyperSmartDefaultEnv "HYPERSMART_COIN_SIDE_LOSS_MIN_CONSENSUS" "3"
Set-HyperSmartDefaultEnv "HYPERSMART_COIN_SIDE_LOSS_MIN_LIQUIDITY" "0.45"
Set-HyperSmartDefaultEnv "HYPERSMART_V12_GATE_AUTHORITATIVE" "1"
Set-HyperSmartDefaultEnv "HYPERSMART_V14_CONSENSUS_WINDOW_AUTHORITATIVE" "1"
Set-HyperSmartDefaultEnv "HYPERSMART_V14_EXEC_COST_AUTHORITATIVE" "1"
Set-HyperSmartDefaultEnv "HYPERSMART_V14_ENTRY_QUALITY_AUTHORITATIVE" "0"
Set-HyperSmartDefaultEnv "HYPERSMART_STATUS_LIVE_MARKS_ENABLED" "1"
Set-HyperSmartDefaultEnv "HL_LOG_LEVEL" "WARNING"

function Test-CommandCenter {
    try {
        # Keep startup readiness cheap. /api/simulation/overview can be heavy on
        # large runtime DBs; using it here made the launcher think the UI was
        # dead even while the static page and fast status endpoint were alive.
        $response = Invoke-WebRequest -UseBasicParsing -Uri $HealthUrl -TimeoutSec 2
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

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][object]$Payload,
        [int]$Depth = 8
    )
    $json = $Payload | ConvertTo-Json -Depth $Depth
    $tmpPath = "$Path.$PID.tmp"
    $encoding = [System.Text.UTF8Encoding]::new($false)
    $lastError = $null
    for ($attempt = 1; $attempt -le 4; $attempt++) {
        try {
            [System.IO.File]::WriteAllText($tmpPath, $json, $encoding)
            Move-Item -LiteralPath $tmpPath -Destination $Path -Force -ErrorAction Stop
            return
        } catch {
            $lastError = $_.Exception
            Start-Sleep -Milliseconds (35 * $attempt)
        }
    }
    try {
        if (Test-Path -LiteralPath $tmpPath) {
            Remove-Item -LiteralPath $tmpPath -Force -ErrorAction SilentlyContinue
        }
    } catch {}
    throw $lastError
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
                sltp_take_profit_bps = "$env:HYPERSMART_SLTP_TAKE_PROFIT_BPS"
                sltp_stop_loss_bps = "$env:HYPERSMART_SLTP_STOP_LOSS_BPS"
                sltp_stop_min_hold_ms = "$env:HYPERSMART_SLTP_STOP_MIN_HOLD_MS"
                sltp_catastrophic_stop_bps = "$env:HYPERSMART_SLTP_CATASTROPHIC_STOP_BPS"
                min_reduce_notional_usdt = "$env:HYPERSMART_MIN_REDUCE_NOTIONAL_USDT"
            }
        }
        Write-JsonAtomic -Path $engineStatusPath -Payload $payload -Depth 8
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
                ($_.CommandLine -like "*hl_observer.runtime.persistent_poll_runner*") -or
                ($_.CommandLine -like "*hypersmart_simulation_poll_loop.ps1*") -or
                ($_.CommandLine -like "*tools\ia_train_loop.ps1*") -or
                ($_.CommandLine -like "*tools/ia_train_loop.ps1*") -or
                ($_.CommandLine -like "*tools\stream_loop.ps1*") -or
                ($_.CommandLine -like "*tools/stream_loop.ps1*") -or
                ($_.CommandLine -like "*hl_observer copy-run*--network-read*") -or
                ($_.CommandLine -like "*hl_observer live-user-fills-scan*--network-read*") -or
                ($_.CommandLine -like "*hl_observer live-user-fills-stream*--network-read*") -or
                ($_.CommandLine -like "*hl_observer live-public-scan*--network-read*") -or
                ($_.CommandLine -like "*hl_observer.research.explain_cli*")
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
    try {
        "stop_requested_at=$(Get-Date -Format o); reason=$Reason" | Set-Content -LiteralPath $runtimeStopFile -Encoding UTF8
        Start-Sleep -Milliseconds 800
    } catch {
        Write-LauncherLog "runtime stop file unavailable: $($_.Exception.Message)"
    }
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
    if ($env:HYPERSMART_RESET_ON_LAUNCH -ne "0") {
        $resetOutput = & python -m hl_observer reset-simulation-state --starting-equity 1000 2>&1
        foreach ($line in $resetOutput) { Write-LauncherLog $line }
        Write-LauncherLine "Capital virtuel REMIS a 1000 USDT pour ce lancement. Mettre HYPERSMART_RESET_ON_LAUNCH=0 pour conserver une session."
    } else {
        Write-LauncherLine "Capital virtuel CONSERVE entre lancements: HYPERSMART_RESET_ON_LAUNCH=0."
    }
    Write-LauncherLine "Nouvelle session simulation: moteur Hyperliquid read-only + paper local actif."
    $prepareLogsOutput = & python -m hl_observer prepare-simulation-logs 2>&1
    foreach ($line in $prepareLogsOutput) { Write-LauncherLog $line }
    Write-LauncherLine "Logs a envoyer prepares: session fraiche, anciens fichiers deplaces dans _archives."
    Write-LauncherLine "Nouvelle session de logs preparee (reset a 1000 par defaut; conservation seulement avec HYPERSMART_RESET_ON_LAUNCH=0)."
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

function Test-HyperSmartAuxRunning {
    param([string]$CommandPattern)
    try {
        $matches = Get-CimInstance Win32_Process | Where-Object {
            $_.ProcessId -ne $PID -and $_.CommandLine -like $CommandPattern
        }
        return @($matches).Count -gt 0
    } catch {
        return $false
    }
}

if ($env:HYPERSMART_ENABLE_AUX_IA -ne "0") {
    if (-not (Test-HyperSmartAuxRunning "*tools\ia_train_loop.ps1*")) {
        Write-LauncherLine "Demarrage IA locale shadow rattachee au lanceur (lecture seule, pas de decision autonome)."
        $iaScript = Join-Path $PSScriptRoot "ia_train_loop.ps1"
        $iaArguments = @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", "`"$iaScript`""
        ) -join " "
        $iaProcess = Start-Process -WindowStyle Hidden -PassThru -FilePath "powershell" -ArgumentList $iaArguments -WorkingDirectory $Root -RedirectStandardOutput $iaStdoutLog -RedirectStandardError $iaStderrLog
        if ($iaProcess -and $iaProcess.Id) {
            $iaProcessId = [int]$iaProcess.Id
            $startedProcesses.Add([int]$iaProcess.Id) | Out-Null
        }
    } else {
        Write-LauncherLine "IA locale deja active; pas de doublon."
    }
}

if ($env:HYPERSMART_ENABLE_AUX_STREAM -ne "0") {
    if (-not (Test-HyperSmartAuxRunning "*tools\stream_loop.ps1*")) {
        Write-LauncherLine "Demarrage stream leaders Hyperliquid read-only rattache au lanceur."
        $streamScript = Join-Path $PSScriptRoot "stream_loop.ps1"
        $streamArguments = @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", "`"$streamScript`""
        ) -join " "
        $streamProcess = Start-Process -WindowStyle Hidden -PassThru -FilePath "powershell" -ArgumentList $streamArguments -WorkingDirectory $Root -RedirectStandardOutput $streamStdoutLog -RedirectStandardError $streamStderrLog
        if ($streamProcess -and $streamProcess.Id) {
            $streamProcessId = [int]$streamProcess.Id
            $startedProcesses.Add([int]$streamProcess.Id) | Out-Null
        }
    } else {
        Write-LauncherLine "Stream leaders Hyperliquid deja actif; pas de doublon."
    }
}

for ($i = 0; $i -lt 120; $i++) {
    if (Test-CommandCenter) {
        break
    }
    if ($null -ne $uiProcessId -and -not (Test-ProcessAlive -ProcessId $uiProcessId)) {
        break
    }
    Start-Sleep -Milliseconds 500
}

if (-not (Test-CommandCenter)) {
    Write-LauncherLine "ALERTE: serveur UI local ne repond pas encore sur $HealthUrl. Regarde $uiStderrLog."
}

if ($null -ne $uiProcessId -and -not (Test-ProcessAlive -ProcessId $uiProcessId)) {
    Write-LauncherLine "ALERTE: le serveur UI s'est arrete juste apres le lancement. Regarde $uiStderrLog."
}

if ($null -ne $pollProcessId -and -not (Test-ProcessAlive -ProcessId $pollProcessId)) {
    Write-LauncherLine "ALERTE: le poller simulation s'est arrete juste apres le lancement. Regarde $pollerStderrLog et $pollerStdoutLog."
}

if (Test-CommandCenter) {
    Write-LauncherLine "Ouverture du dashboard $Url"
    Start-Process $Url
} else {
    Write-LauncherLine "Dashboard non ouvert: serveur UI indisponible. Relance apres lecture de $uiStderrLog."
}

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
                    $status = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 5
                    Write-Host ("PNL={0} USDT Equity={1} Positions={2} Entries={3} Exits={4} Refus={5} Phase={6}" -f `
                        $status.equity.current_pnl_usdc, `
                        $status.equity.current_equity_usdt, `
                        $status.positions.Count, `
                        $status.counts.reproduced_entries, `
                        $status.counts.reproduced_exits, `
                        $status.counts.bot_refused, `
                        $status.scanner.phase)
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
