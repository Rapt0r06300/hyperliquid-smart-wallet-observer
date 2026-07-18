param(
    [string]$Root,
    [int]$IntervalSeconds = 60,
    [int]$MaxLeaders = 50,
    [int]$LeadersPerPoll = 10,
    [int]$BackfillDays = 1,
    [int]$FreshWindowMinutes = 15,
    [int]$MaxPages = 1,
    [string]$PublicTradeCoins = "AUTO",
    [int]$PublicTradeMaxCoins = 40,
    [int]$PublicTradeScanSeconds = 8,
    [int]$PublicTradeMaxWallets = 10000,
    [int]$PublicTradeScanEveryPolls = 1,
    [int]$UserFillsMaxLiveAgeMs = 120000,
    [int]$MaxRuns = 5760,
    # Cadence 2026-07-07: le poll prenait ~200s au lieu de 15s parce que CHAQUE poll
    # payait ~14 demarrages python dont des etapes de diagnostic lourdes. Les plans et
    # diagnostics restent executes, mais tous les N polls (poll 1 inclus).
    [int]$PlansEveryPolls = 5,
    [int]$DiagnosticsEveryPolls = 5
)

$ErrorActionPreference = "Continue"
if ([string]::IsNullOrWhiteSpace($Root)) {
    $Root = Split-Path -Parent $PSScriptRoot
}

$logDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logsToSendDir = Join-Path $logDir ("logs " + [char]0x00E0 + " envoyer")
$runtimeDataDir = Join-Path $Root "runtime\data"
New-Item -ItemType Directory -Force -Path $runtimeDataDir | Out-Null
$logPath = Join-Path $logDir "hypersmart_simulation_live.log"
$lockPath = Join-Path $logDir "hypersmart_simulation_poll_loop.lock"
$engineStatusPath = Join-Path $runtimeDataDir "hypersmart_engine_status.json"
$v12SqlitePath = Join-Path $runtimeDataDir "hypersmart_v12_artifacts.sqlite3"
if ([string]::IsNullOrWhiteSpace($env:HYPERSMART_V12_SQLITE_PATH)) {
    $env:HYPERSMART_V12_SQLITE_PATH = $v12SqlitePath
}
if ([string]::IsNullOrWhiteSpace($env:HYPERSMART_SLTP_ENABLED)) {
    $env:HYPERSMART_SLTP_ENABLED = "1"
}
if ([string]::IsNullOrWhiteSpace($env:HYPERSMART_SLTP_TAKE_PROFIT_BPS)) {
    $env:HYPERSMART_SLTP_TAKE_PROFIT_BPS = "180"
}
if ([string]::IsNullOrWhiteSpace($env:HYPERSMART_SLTP_STOP_LOSS_BPS)) {
    $env:HYPERSMART_SLTP_STOP_LOSS_BPS = "120"
}
if ([string]::IsNullOrWhiteSpace($env:HYPERSMART_SLTP_TRAILING_BPS)) {
    $env:HYPERSMART_SLTP_TRAILING_BPS = "90"
}
if ([string]::IsNullOrWhiteSpace($env:HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS)) {
    $env:HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS = "160"
}
if ([string]::IsNullOrWhiteSpace($env:HYPERSMART_SLTP_BREAKEVEN_BUFFER_BPS)) {
    $env:HYPERSMART_SLTP_BREAKEVEN_BUFFER_BPS = "12"
}
if ([string]::IsNullOrWhiteSpace($env:HYPERSMART_SLTP_STOP_MIN_HOLD_MS)) {
    $env:HYPERSMART_SLTP_STOP_MIN_HOLD_MS = "180000"
}
if ([string]::IsNullOrWhiteSpace($env:HYPERSMART_SLTP_CATASTROPHIC_STOP_BPS)) {
    $env:HYPERSMART_SLTP_CATASTROPHIC_STOP_BPS = "220"
}
if ([string]::IsNullOrWhiteSpace($env:HYPERSMART_ADAPTIVE_PAPER_SIZING)) {
    $env:HYPERSMART_ADAPTIVE_PAPER_SIZING = "1"
}
if ([string]::IsNullOrWhiteSpace($env:HYPERSMART_MIN_REDUCE_NOTIONAL_USDT)) {
    $env:HYPERSMART_MIN_REDUCE_NOTIONAL_USDT = "0"
}
if ([string]::IsNullOrWhiteSpace($env:HYPERSMART_CARRY_HYPE_PAPER)) {
    # Decision de Flo (2026-07-14, « les 3 ») : le carry HYPE tourne en PAPER.
    # Sans inputs MESURES (runtime/data/carry_spot_inputs.json), chaque poll journalise un
    # REFUS motive -- c'est le deny-by-default voulu, pas un bug.
    $env:HYPERSMART_CARRY_HYPE_PAPER = "1"
}
if ([string]::IsNullOrWhiteSpace($env:HYPERSMART_CARRY_ETAPE2)) {
    # ETAPE 2 (18/07) : ouvrir REELLEMENT la position paper delta-neutre quand la decision est
    # viable (long spot + short perp), accruer le funding MESURE, sortir/PnL realise dans
    # runtime/data/carry_paper_ledger.jsonl. 100%% PAPER : aucun ordre reel, aucune signature.
    $env:HYPERSMART_CARRY_ETAPE2 = "1"
}
$script:EngineMetrics = @{
    runtime_venue = "Hyperliquid"
    paper_engine = "local_only"
    v12_sqlite_path = "$env:HYPERSMART_V12_SQLITE_PATH"
    sltp_enabled = "$env:HYPERSMART_SLTP_ENABLED"
    sltp_take_profit_bps = "$env:HYPERSMART_SLTP_TAKE_PROFIT_BPS"
    sltp_stop_loss_bps = "$env:HYPERSMART_SLTP_STOP_LOSS_BPS"
    sltp_trailing_bps = "$env:HYPERSMART_SLTP_TRAILING_BPS"
    sltp_trailing_activation_bps = "$env:HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS"
    sltp_breakeven_buffer_bps = "$env:HYPERSMART_SLTP_BREAKEVEN_BUFFER_BPS"
    sltp_stop_min_hold_ms = "$env:HYPERSMART_SLTP_STOP_MIN_HOLD_MS"
    sltp_catastrophic_stop_bps = "$env:HYPERSMART_SLTP_CATASTROPHIC_STOP_BPS"
    adaptive_paper_sizing = "$env:HYPERSMART_ADAPTIVE_PAPER_SIZING"
    min_reduce_notional_usdt = "$env:HYPERSMART_MIN_REDUCE_NOTIONAL_USDT"
}
$script:CurrentPoll = 0

if ($MaxRuns -le 0) {
    $MaxRuns = 5760
    $script:EngineMetrics["max_runs_guard_applied"] = "true"
}

function Write-LoopLog {
    param([string]$Message)
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$stamp] $Message"
    try {
        Add-Content -LiteralPath $logPath -Value "[$stamp] $Message" -ErrorAction Stop
    } catch {
        Write-Host "[HyperSmart][poller-log-warning] $($_.Exception.Message)"
    }
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

function Write-EngineStatus {
    param(
        [string]$Phase,
        [string]$Message
    )
    try {
        $existingFusionInput = $null
        $existingFusionInputStatus = $null
        $existingFusionInputMessage = $null
        try {
            if (Test-Path -LiteralPath $engineStatusPath) {
                $existingStatus = Get-Content -LiteralPath $engineStatusPath -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($null -ne $existingStatus.fusion_runtime_input) {
                    $existingFusionInput = $existingStatus.fusion_runtime_input
                }
                if ($null -ne $existingStatus.fusion_runtime_input_status) {
                    $existingFusionInputStatus = [string]$existingStatus.fusion_runtime_input_status
                }
                if ($null -ne $existingStatus.fusion_runtime_input_message) {
                    $existingFusionInputMessage = [string]$existingStatus.fusion_runtime_input_message
                }
                if ($null -ne $existingStatus.metrics) {
                    foreach ($metricName in @(
                        "fusion_runtime_input_status",
                        "fusion_runtime_votes",
                        "fusion_runtime_price_events",
                        "fusion_runtime_coins",
                        "fusion_runtime_reasons",
                        "fusion_runtime_recent_deltas",
                        "fusion_runtime_recent_entry_deltas",
                        "fusion_runtime_latest_delta_age_ms",
                        "fusion_runtime_state_source",
                        "fusion_runtime_current_equity_usdt",
                        "fusion_runtime_peak_equity_usdt",
                        "fusion_runtime_open_exposure_usdt"
                    )) {
                        if ($existingStatus.metrics.PSObject.Properties.Name -contains $metricName) {
                            $script:EngineMetrics[$metricName] = [string]$existingStatus.metrics.$metricName
                        }
                    }
                }
            }
        } catch {
            # Heartbeat preservation is best-effort; status writing must never stop the scanner loop.
        }
        $script:EngineMetrics["runtime_venue"] = "Hyperliquid"
        $script:EngineMetrics["paper_engine"] = "local_only"
        $script:EngineMetrics["v12_sqlite_path"] = "$env:HYPERSMART_V12_SQLITE_PATH"
        $script:EngineMetrics["sltp_enabled"] = "$env:HYPERSMART_SLTP_ENABLED"
        $script:EngineMetrics["sltp_take_profit_bps"] = "$env:HYPERSMART_SLTP_TAKE_PROFIT_BPS"
        $script:EngineMetrics["sltp_stop_loss_bps"] = "$env:HYPERSMART_SLTP_STOP_LOSS_BPS"
        $script:EngineMetrics["sltp_trailing_bps"] = "$env:HYPERSMART_SLTP_TRAILING_BPS"
        $script:EngineMetrics["sltp_trailing_activation_bps"] = "$env:HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS"
        $script:EngineMetrics["sltp_breakeven_buffer_bps"] = "$env:HYPERSMART_SLTP_BREAKEVEN_BUFFER_BPS"
        $script:EngineMetrics["sltp_stop_min_hold_ms"] = "$env:HYPERSMART_SLTP_STOP_MIN_HOLD_MS"
        $script:EngineMetrics["sltp_catastrophic_stop_bps"] = "$env:HYPERSMART_SLTP_CATASTROPHIC_STOP_BPS"
        $script:EngineMetrics["adaptive_paper_sizing"] = "$env:HYPERSMART_ADAPTIVE_PAPER_SIZING"
        $script:EngineMetrics["min_reduce_notional_usdt"] = "$env:HYPERSMART_MIN_REDUCE_NOTIONAL_USDT"
        $epochMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
        $payload = [ordered]@{
            updated_at_ms = $epochMs
            phase = $Phase
            message = $Message
            poll_index = $script:CurrentPoll
            max_runs = $MaxRuns
            pool = $MaxLeaders
            leaders_per_poll = $LeadersPerPoll
            read_only = $true
            simulation_only = $true
            external_action = $false
            metrics = $script:EngineMetrics
        }
        if ($null -ne $existingFusionInput) {
            $payload["fusion_runtime_input"] = $existingFusionInput
        }
        if ($null -ne $existingFusionInputStatus) {
            $payload["fusion_runtime_input_status"] = $existingFusionInputStatus
        }
        if ($null -ne $existingFusionInputMessage) {
            $payload["fusion_runtime_input_message"] = $existingFusionInputMessage
        }
        Write-JsonAtomic -Path $engineStatusPath -Payload $payload -Depth 8
    } catch {
        Write-LoopLog "engine status write failed: $($_.Exception.Message)"
    }
}

function Write-CommandOutput {
    param(
        [object[]]$Lines,
        [string]$Label
    )
    $suppressedHttpOk = 0
    foreach ($line in $Lines) {
        $text = [string]$line
        if ($text -like '*"logger": "httpx"*' -and $text -like '*HTTP/1.1 200 OK*') {
            $suppressedHttpOk += 1
            continue
        }
        if ([string]::IsNullOrWhiteSpace($text)) {
            continue
        }
        if ($text -match '^([A-Za-z0-9_]+)=(.*)$') {
            $script:EngineMetrics[$Matches[1]] = $Matches[2]
        }
        foreach ($match in [regex]::Matches($text, '(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9_]{1,48})=([^ \t,;]+)')) {
            try {
                $rawName = [string]$match.Groups[1].Value
                $rawValue = [string]$match.Groups[2].Value
                $safeLabel = ($Label -replace '[^A-Za-z0-9_]', '_').Trim('_')
                if (-not [string]::IsNullOrWhiteSpace($safeLabel)) {
                    $script:EngineMetrics[("${safeLabel}_" + $rawName)] = $rawValue
                }
            } catch {
                # Metric extraction is diagnostic only; never stop the scan loop.
            }
        }
        Write-LoopLog $text
    }
    if ($suppressedHttpOk -gt 0) {
        Write-LoopLog "${Label}: suppressed $suppressedHttpOk successful /info HTTP 200 log lines"
    }
}

# --- Mini-T43 (Annexe B roadmap): duree mesuree par etape, exposee dans le log poller
# ("poll N durations") ET dans l'engine status (metrics step_ms_*). MESURER d'abord,
# optimiser ensuite: c'est ce qui a revele les etapes lentes du poll de 200s. ---
$script:StepDurations = [ordered]@{}
function Get-NowMs {
    return [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
}
function Add-StepDuration {
    param([string]$Step, [long]$StartMs)
    try {
        $elapsedMs = (Get-NowMs) - $StartMs
        $key = ($Step -replace '[^A-Za-z0-9_]', '_')
        $script:StepDurations[$key] = $elapsedMs
        $script:EngineMetrics[("step_ms_" + $key)] = "$elapsedMs"
    } catch { }
}

try {
    $script:PollerLockStream = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
} catch {
    Write-LoopLog "Another simulation poll loop already owns the runtime lock. Exiting without duplicate scanner."
    exit 0
}

Write-LoopLog "Simulation poll loop started. root=$Root interval=$IntervalSeconds pool=$MaxLeaders leadersPerPoll=$LeadersPerPoll maxRuns=$MaxRuns maxLiveFillAgeMs=$UserFillsMaxLiveAgeMs"
# ===== #286: LA SESSION NAIT ICI (une par lancement du poller). Tous les enfants heritent
# de l'env; les processus freres (UI) lisent le manifeste runtime/data. =====
if ([string]::IsNullOrWhiteSpace($env:HYPERSMART_SESSION_ID)) {
    try {
        $sid = (& python -m hl_observer.runtime.session_identity --start --root "$Root" 2>$null | Select-Object -Last 1)
        if (-not [string]::IsNullOrWhiteSpace($sid)) {
            $env:HYPERSMART_SESSION_ID = "$sid".Trim()
            Write-LoopLog "Session demarree: $($env:HYPERSMART_SESSION_ID)"
        } else {
            Write-LoopLog "AVERTISSEMENT: session non demarree (sortie vide); le runner posera un filet."
        }
    } catch {
        Write-LoopLog "AVERTISSEMENT: demarrage session impossible ($($_.Exception.Message)); le runner posera un filet."
    }
} else {
    Write-LoopLog "Session heritee de l'environnement: $($env:HYPERSMART_SESSION_ID)"
}
Write-EngineStatus "starting" "Poller simulation Hyperliquid en demarrage."

# ===== T44: MODE PERSISTANT (defaut) =====
# Un SEUL process python chaud execute tout le cycle (imports chauds, ecoutes WS en
# parallele) au lieu de ~14 demarrages a froid par poll. Mesure avant/apres au log
# "poll N durations". Mettre HYPERSMART_PERSISTENT_LOOP=0 pour revenir a la boucle
# legacy ci-dessous (conservee integralement, rien de supprime).
$persistentLoop = "1"
if ($env:HYPERSMART_PERSISTENT_LOOP) { $persistentLoop = "$env:HYPERSMART_PERSISTENT_LOOP" }
if ($persistentLoop -ne "0") {
    $watchdogStaleSeconds = 600
    if ($env:HYPERSMART_PERSISTENT_WATCHDOG_STALE_SECONDS) { try { $watchdogStaleSeconds = [Math]::Max(120, [int]$env:HYPERSMART_PERSISTENT_WATCHDOG_STALE_SECONDS) } catch { } }
    $stopFilePath = Join-Path $runtimeDataDir "hypersmart_runtime.stop"
    if ($env:HYPERSMART_RUNTIME_STOP_FILE) { $stopFilePath = $env:HYPERSMART_RUNTIME_STOP_FILE }
    $persistentOut = Join-Path $logDir "hypersmart_poller_persistent.out.log"
    $persistentErr = Join-Path $logDir "hypersmart_poller_persistent.err.log"
    Write-LoopLog "Mode PERSISTANT T44 actif: un process python chaud pour tout le poll. Watchdog heartbeat=${watchdogStaleSeconds}s. (HYPERSMART_PERSISTENT_LOOP=0 => ancienne boucle)"
    while (-not (Test-Path -LiteralPath $stopFilePath)) {
        $runnerArgs = "-u -m hl_observer.runtime.persistent_poll_runner --root `"$Root`" --interval-seconds $IntervalSeconds --max-leaders $MaxLeaders --leaders-per-poll $LeadersPerPoll --backfill-days $BackfillDays --fresh-window-minutes $FreshWindowMinutes --max-pages $MaxPages --public-trade-coins $PublicTradeCoins --public-trade-max-coins $PublicTradeMaxCoins --public-trade-scan-seconds $PublicTradeScanSeconds --public-trade-max-wallets $PublicTradeMaxWallets --public-trade-scan-every-polls $PublicTradeScanEveryPolls --user-fills-max-live-age-ms $UserFillsMaxLiveAgeMs --max-runs $MaxRuns --plans-every-polls $PlansEveryPolls --diagnostics-every-polls $DiagnosticsEveryPolls"
        $rp = $null
        try {
            $rp = Start-Process -NoNewWindow -PassThru -FilePath "python" -ArgumentList $runnerArgs -WorkingDirectory $Root -RedirectStandardOutput $persistentOut -RedirectStandardError $persistentErr
        } catch {
            Write-LoopLog "ERREUR: demarrage runner persistant impossible ($($_.Exception.Message)); nouvelle tentative dans 10s."
            Start-Sleep -Seconds 10
            continue
        }
        while ($rp -and -not $rp.HasExited) {
            Start-Sleep -Seconds 15
            if (Test-Path -LiteralPath $stopFilePath) { break }
            try {
                $st = Get-Content -LiteralPath $engineStatusPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $ageMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() - [long]$st.updated_at_ms
                if ($ageMs -gt ($watchdogStaleSeconds * 1000)) {
                    Write-LoopLog "WATCHDOG: heartbeat engine status vieux de $([int]($ageMs / 1000))s (> ${watchdogStaleSeconds}s) -> kill du runner persistant + relance."
                    try { $rp.Kill() } catch { }
                    break
                }
            } catch { }
        }
        if ($rp -and -not $rp.HasExited) {
            try { $rp.Kill() } catch { }
        }
        try { $rp.WaitForExit(10000) | Out-Null } catch { }
        $rc = $null
        try { $rc = $rp.ExitCode } catch { $rc = $null }
        if (Test-Path -LiteralPath $stopFilePath) { break }
        if ($rc -eq 3) {
            Write-LoopLog "Runner persistant: rotation planifiee (exit 3), relance immediate."
        } else {
            Write-LoopLog "Runner persistant sorti (code $rc), relance dans 5s."
            Start-Sleep -Seconds 5
        }
    }
    Write-LoopLog "Simulation poll loop finished (mode persistant)."
    Write-EngineStatus "finished" "Poller simulation termine."
    exit 0
}
# ===== MODE LEGACY (HYPERSMART_PERSISTENT_LOOP=0): boucle historique inchangee =====


for ($i = 1; $i -le $MaxRuns; $i++) {
    $script:CurrentPoll = $i
    $safeLeadersPerPoll = [Math]::Max(1, [Math]::Min($LeadersPerPoll, [Math]::Min($MaxLeaders, 10)))
    $leaderOffset = (($i - 1) * $safeLeadersPerPoll) % [Math]::Max(1, $MaxLeaders)
    Write-LoopLog "poll $i/$MaxRuns starting offset=$leaderOffset batch=$safeLeadersPerPoll pool=$MaxLeaders"
    Write-EngineStatus "poll_start" "Poll $i/${MaxRuns}: offset=$leaderOffset batch=$safeLeadersPerPoll pool=$MaxLeaders."
    try {
        Push-Location $Root
        $pollStartMs = Get-NowMs
        $safePlansEvery = [Math]::Max(1, $PlansEveryPolls)
        if ($i -eq 1 -or ($i % $safePlansEvery) -eq 0) {
            $t0 = Get-NowMs
            Write-EngineStatus "throughput_plan" "Verification des budgets de scan read-only."
            $planOutput = & python -m hl_observer throughput-plan --network-read --ws --requested-wallets $MaxLeaders --max-leaders-per-run $safeLeadersPerPoll --public-trade-wallets $PublicTradeMaxWallets 2>&1
            Write-CommandOutput -Lines $planOutput -Label "throughput-plan"
            Write-EngineStatus "fresh_scan_plan" "Planification de la rotation des wallets frais."
            $freshPlanOutput = & python -m hl_observer fresh-scan-plan --network-read --requested-wallets 50000 --cycle-seconds $IntervalSeconds --leaders-per-stream $safeLeadersPerPoll --public-trade-wallets $PublicTradeMaxWallets 2>&1
            Write-CommandOutput -Lines $freshPlanOutput -Label "fresh-scan-plan"
            Write-EngineStatus "fresh_data_plan" "Selection des coins et sources temps reel (gap-recovery inclus)."
            $freshDataOutput = & python -m hl_observer fresh-data-plan --network-read --requested-wallets 50000 --coins $PublicTradeCoins --max-coins $PublicTradeMaxCoins --max-hot-wallets $safeLeadersPerPoll --gap-recovery 2>&1
            Write-CommandOutput -Lines $freshDataOutput -Label "fresh-data-plan"
            Add-StepDuration "plans" $t0
        } else {
            Write-LoopLog "Plans (throughput/fresh-scan/fresh-data) sautes ce poll (1 poll sur $safePlansEvery) pour la cadence."
        }
        Write-LoopLog "Refreshing Hyperliquid allMids market marks for paper mark-to-market..."
        Write-EngineStatus "market_marks_refresh" "Rafraichissement allMids Hyperliquid read-only pour le PnL latent paper."
        $t0 = Get-NowMs
        $marketMarksOutput = & python -m hl_observer discover-markets --store --max-coins $PublicTradeMaxCoins 2>&1
        Write-CommandOutput -Lines $marketMarksOutput -Label "discover-markets"
        Add-StepDuration "discover_markets" $t0
        $t0 = Get-NowMs
        $marketScanOutput = & python -m hl_observer scan-markets --all --store --max-coins $PublicTradeMaxCoins --l2book --candles 2>&1
        Write-CommandOutput -Lines $marketScanOutput -Label "scan-markets"
        Add-StepDuration "scan_markets" $t0
        if ($i -eq 1 -or ($i % 20) -eq 0) {
            Write-LoopLog "Refreshing collect-all shortlist supply for active wallets..."
            Write-EngineStatus "periodic_collect_all" "Refresh collect-all borne: marches, wallets, shortlist, queue."
            $collectAllOutput = & python -m hl_observer.collection.run_collect_all --max-coins $PublicTradeMaxCoins --target ([Math]::Max(500, $MaxLeaders * 10)) 2>&1
            Write-CommandOutput -Lines $collectAllOutput -Label "collect-all"
            Write-LoopLog "Refreshing bounded Hyperliquid Explorer observations for fresh wallet supply..."
            Write-EngineStatus "periodic_explorer_scrape" "Lecture Explorer Hyperliquid read-only bornee pour enrichir les wallets reels."
            $explorerOutput = & python -m hl_observer scrape-explorer --store --max-events 250 2>&1
            Write-CommandOutput -Lines $explorerOutput -Label "scrape-explorer"
            $explorerCandidatesOutput = & python -m hl_observer explorer-candidates --store 2>&1
            Write-CommandOutput -Lines $explorerCandidatesOutput -Label "explorer-candidates"
        }
        $safeScanEvery = [Math]::Max(1, $PublicTradeScanEveryPolls)
        if ($i -eq 1 -or ($i % $safeScanEvery) -eq 0) {
            Write-LoopLog "Running live-public-scan for candidate discovery..."
            Write-EngineStatus "live_public_scan" "Lecture WebSocket publique Hyperliquid pour decouvrir des wallets."
            $t0 = Get-NowMs
            $wsOutput = & python -m hl_observer live-public-scan --network-read --store --duration-seconds $PublicTradeScanSeconds --coins $PublicTradeCoins --max-coins $PublicTradeMaxCoins --max-wallets $PublicTradeMaxWallets --promote-top $MaxLeaders --no-report 2>&1
            Write-CommandOutput -Lines $wsOutput -Label "live-public-scan"
            Add-StepDuration "live_public_scan" $t0
        } else {
            Write-LoopLog "Skipping live-public-scan to maximize copying frequency..."
            Write-EngineStatus "live_public_scan_skipped" "Scan public saute pour privilegier la frequence de copie paper."
        }
        Write-LoopLog "Running shortlist userFills WebSocket monitor for fresh bounded deltas..."
        Write-EngineStatus "live_user_fills_scan" "Lecture WebSocket userFills read-only sur shortlist bornee."
        $t0 = Get-NowMs
        $userFillsOutput = & python -m hl_observer live-user-fills-scan --network-read --store --duration-seconds 10 --max-users $safeLeadersPerPoll --leader-offset $leaderOffset --max-live-fill-age-ms $UserFillsMaxLiveAgeMs 2>&1
        Write-CommandOutput -Lines $userFillsOutput -Label "live-user-fills-scan"
        Add-StepDuration "live_user_fills_scan" $t0
        $syncInterval = 20
        $forceNetworkRead = ($i -eq 1) -or (($i % $syncInterval) -eq 0)
        $t0 = Get-NowMs
        if ($forceNetworkRead) {
            Write-LoopLog "Running copy-run with network-read for gap recovery and sync..."
            Write-EngineStatus "copy_run_network_read" "Reconciliation REST /info read-only et simulation paper locale."
            $output = & python -m hl_observer copy-run --interval $IntervalSeconds --dry-run --network-read --copy-max-leaders $safeLeadersPerPoll --leader-offset $leaderOffset --backfill-days $BackfillDays --fresh-window-minutes $FreshWindowMinutes --max-pages $MaxPages --no-report 2>&1
        } else {
            Write-LoopLog "Running copy-run with local database only (real-time WebSocket updates)..."
            Write-EngineStatus "copy_run_local" "Decision paper depuis la base locale et les evenements WS recents."
            $output = & python -m hl_observer copy-run --interval $IntervalSeconds --dry-run --copy-max-leaders $safeLeadersPerPoll --leader-offset $leaderOffset --backfill-days $BackfillDays --fresh-window-minutes $FreshWindowMinutes --max-pages $MaxPages --no-report 2>&1
        }
        Write-CommandOutput -Lines $output -Label "copy-run"
        Add-StepDuration "copy_run" $t0
        Write-EngineStatus "opportunity_report" "Analyse des opportunites et consensus recents."
        $t0 = Get-NowMs
        $opportunityOutput = & python -m hl_observer opportunity-report --active-window-seconds 120 --consensus-window-seconds 4 --min-wallets 2 --max-deltas 5000 --max-opportunities 10 2>&1
        Write-CommandOutput -Lines $opportunityOutput -Label "opportunity-report"
        Add-StepDuration "opportunity_report" $t0
        Write-EngineStatus "fusion_runtime_input" "Construction input fusion paper depuis deltas locaux et prix Hyperliquid locaux."
        $t0 = Get-NowMs
        $fusionInputOutput = & python -m hl_observer fusion-heartbeat-input --fresh-window-seconds 120 --max-votes 24 --write-engine-status --no-report 2>&1
        Write-CommandOutput -Lines $fusionInputOutput -Label "fusion-heartbeat-input"
        Add-StepDuration "fusion_heartbeat_input" $t0
        $safeDiagEvery = [Math]::Max(1, $DiagnosticsEveryPolls)
        if ($i -eq 1 -or ($i % $safeDiagEvery) -eq 0) {
            Write-EngineStatus "simulation_readiness" "Diagnostic de fraicheur et raisons de refus."
            $t0 = Get-NowMs
            $readinessOutput = & python -m hl_observer simulation-readiness --from-logs "$logsToSendDir" --fresh-window-seconds 120 2>&1
            Write-CommandOutput -Lines $readinessOutput -Label "simulation-readiness"
            Add-StepDuration "simulation_readiness" $t0
            Write-EngineStatus "warehouse_report" "Synthese warehouse local: wallets, deltas, decisions paper."
            $t0 = Get-NowMs
            $warehouseOutput = & python -m hl_observer warehouse-report --fresh-window-seconds 120 2>&1
            Write-CommandOutput -Lines $warehouseOutput -Label "warehouse-report"
            Add-StepDuration "warehouse_report" $t0
        } else {
            Write-LoopLog "Diagnostics (readiness/warehouse) sautes ce poll (1 poll sur $safeDiagEvery) pour la cadence."
        }
        try {
            $pollTotalMs = (Get-NowMs) - $pollStartMs
            $script:EngineMetrics["poll_total_ms"] = "$pollTotalMs"
            $slowest = ($script:StepDurations.GetEnumerator() | Sort-Object -Property Value -Descending | Select-Object -First 8 | ForEach-Object { "$($_.Key)=$($_.Value)ms" }) -join " "
            Write-LoopLog "poll $i durations: total=${pollTotalMs}ms $slowest"
        } catch { }
        $script:StepDurations = [ordered]@{}
        Write-EngineStatus "sleeping" "Cycle termine, attente avant prochain scan."
        Pop-Location
    } catch {
        Write-LoopLog "poll failed: $($_.Exception.Message)"
        Write-EngineStatus "poll_failed" "Erreur poller: $($_.Exception.Message)"
        try { Pop-Location } catch {}
    }
    if ($i -lt $MaxRuns) {
        # Cooldown court entre cycles: le scan (WS publique + userFills + reconcile) EST la cadence.
        # On evite ~15s d'inactivite ou la WS retombe et ou rien n'est scanne -> scan quasi continu,
        # plus d'opportunites captees. Les limites restent gardees par throughput-plan/budgeter chaque cycle.
        Start-Sleep -Seconds ([Math]::Max(2, [Math]::Min(5, [int]($IntervalSeconds / 3))))
    }
}

Write-LoopLog "Simulation poll loop finished."
Write-EngineStatus "finished" "Poller simulation termine."
