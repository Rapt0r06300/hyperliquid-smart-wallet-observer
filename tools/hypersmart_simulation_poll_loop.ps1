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
    [int]$MaxRuns = 5760
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
    $env:HYPERSMART_SLTP_TAKE_PROFIT_BPS = "85"
}
if ([string]::IsNullOrWhiteSpace($env:HYPERSMART_SLTP_STOP_LOSS_BPS)) {
    $env:HYPERSMART_SLTP_STOP_LOSS_BPS = "30"
}
if ([string]::IsNullOrWhiteSpace($env:HYPERSMART_SLTP_TRAILING_BPS)) {
    $env:HYPERSMART_SLTP_TRAILING_BPS = "30"
}
if ([string]::IsNullOrWhiteSpace($env:HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS)) {
    $env:HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS = "55"
}
if ([string]::IsNullOrWhiteSpace($env:HYPERSMART_SLTP_BREAKEVEN_BUFFER_BPS)) {
    $env:HYPERSMART_SLTP_BREAKEVEN_BUFFER_BPS = "8"
}
if ([string]::IsNullOrWhiteSpace($env:HYPERSMART_ADAPTIVE_PAPER_SIZING)) {
    $env:HYPERSMART_ADAPTIVE_PAPER_SIZING = "1"
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
    adaptive_paper_sizing = "$env:HYPERSMART_ADAPTIVE_PAPER_SIZING"
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

function Write-EngineStatus {
    param(
        [string]$Phase,
        [string]$Message
    )
    try {
        $script:EngineMetrics["runtime_venue"] = "Hyperliquid"
        $script:EngineMetrics["paper_engine"] = "local_only"
        $script:EngineMetrics["v12_sqlite_path"] = "$env:HYPERSMART_V12_SQLITE_PATH"
        $script:EngineMetrics["sltp_enabled"] = "$env:HYPERSMART_SLTP_ENABLED"
        $script:EngineMetrics["sltp_take_profit_bps"] = "$env:HYPERSMART_SLTP_TAKE_PROFIT_BPS"
        $script:EngineMetrics["sltp_stop_loss_bps"] = "$env:HYPERSMART_SLTP_STOP_LOSS_BPS"
        $script:EngineMetrics["sltp_trailing_bps"] = "$env:HYPERSMART_SLTP_TRAILING_BPS"
        $script:EngineMetrics["sltp_trailing_activation_bps"] = "$env:HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS"
        $script:EngineMetrics["sltp_breakeven_buffer_bps"] = "$env:HYPERSMART_SLTP_BREAKEVEN_BUFFER_BPS"
        $script:EngineMetrics["adaptive_paper_sizing"] = "$env:HYPERSMART_ADAPTIVE_PAPER_SIZING"
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
        $payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $engineStatusPath -Encoding UTF8
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
        Write-LoopLog $text
    }
    if ($suppressedHttpOk -gt 0) {
        Write-LoopLog "${Label}: suppressed $suppressedHttpOk successful /info HTTP 200 log lines"
    }
}

try {
    $script:PollerLockStream = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
} catch {
    Write-LoopLog "Another simulation poll loop already owns the runtime lock. Exiting without duplicate scanner."
    exit 0
}

Write-LoopLog "Simulation poll loop started. root=$Root interval=$IntervalSeconds pool=$MaxLeaders leadersPerPoll=$LeadersPerPoll maxRuns=$MaxRuns maxLiveFillAgeMs=$UserFillsMaxLiveAgeMs"
Write-EngineStatus "starting" "Poller simulation Hyperliquid en demarrage."

for ($i = 1; $i -le $MaxRuns; $i++) {
    $script:CurrentPoll = $i
    $safeLeadersPerPoll = [Math]::Max(1, [Math]::Min($LeadersPerPoll, [Math]::Min($MaxLeaders, 10)))
    $leaderOffset = (($i - 1) * $safeLeadersPerPoll) % [Math]::Max(1, $MaxLeaders)
    Write-LoopLog "poll $i/$MaxRuns starting offset=$leaderOffset batch=$safeLeadersPerPoll pool=$MaxLeaders"
    Write-EngineStatus "poll_start" "Poll $i/${MaxRuns}: offset=$leaderOffset batch=$safeLeadersPerPoll pool=$MaxLeaders."
    try {
        Push-Location $Root
        Write-EngineStatus "throughput_plan" "Verification des budgets de scan read-only."
        $planOutput = & python -m hl_observer throughput-plan --network-read --ws --requested-wallets $MaxLeaders --max-leaders-per-run $safeLeadersPerPoll --public-trade-wallets $PublicTradeMaxWallets 2>&1
        Write-CommandOutput -Lines $planOutput -Label "throughput-plan"
        Write-EngineStatus "fresh_scan_plan" "Planification de la rotation des wallets frais."
        $freshPlanOutput = & python -m hl_observer fresh-scan-plan --network-read --requested-wallets 50000 --cycle-seconds $IntervalSeconds --leaders-per-stream $safeLeadersPerPoll --public-trade-wallets $PublicTradeMaxWallets 2>&1
        Write-CommandOutput -Lines $freshPlanOutput -Label "fresh-scan-plan"
        Write-EngineStatus "fresh_data_plan" "Selection des coins et sources temps reel."
        $freshDataOutput = & python -m hl_observer fresh-data-plan --network-read --requested-wallets 50000 --coins $PublicTradeCoins --max-coins $PublicTradeMaxCoins --max-hot-wallets $safeLeadersPerPoll --gap-recovery 2>&1
        Write-CommandOutput -Lines $freshDataOutput -Label "fresh-data-plan"
        Write-LoopLog "Refreshing Hyperliquid allMids market marks for paper mark-to-market..."
        Write-EngineStatus "market_marks_refresh" "Rafraichissement allMids Hyperliquid read-only pour le PnL latent paper."
        $marketMarksOutput = & python -m hl_observer discover-markets --store --max-coins $PublicTradeMaxCoins 2>&1
        Write-CommandOutput -Lines $marketMarksOutput -Label "discover-markets"
        $marketScanOutput = & python -m hl_observer scan-markets --all --store --max-coins $PublicTradeMaxCoins --l2book --candles 2>&1
        Write-CommandOutput -Lines $marketScanOutput -Label "scan-markets"
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
            $wsOutput = & python -m hl_observer live-public-scan --network-read --store --duration-seconds $PublicTradeScanSeconds --coins $PublicTradeCoins --max-coins $PublicTradeMaxCoins --max-wallets $PublicTradeMaxWallets --promote-top $MaxLeaders --no-report 2>&1
            Write-CommandOutput -Lines $wsOutput -Label "live-public-scan"
        } else {
            Write-LoopLog "Skipping live-public-scan to maximize copying frequency..."
            Write-EngineStatus "live_public_scan_skipped" "Scan public saute pour privilegier la frequence de copie paper."
        }
        Write-LoopLog "Running shortlist userFills WebSocket monitor for fresh bounded deltas..."
        Write-EngineStatus "live_user_fills_scan" "Lecture WebSocket userFills read-only sur shortlist bornee."
        $userFillsOutput = & python -m hl_observer live-user-fills-scan --network-read --store --duration-seconds 10 --max-users $safeLeadersPerPoll --leader-offset $leaderOffset --max-live-fill-age-ms $UserFillsMaxLiveAgeMs 2>&1
        Write-CommandOutput -Lines $userFillsOutput -Label "live-user-fills-scan"
        $syncInterval = 20
        $forceNetworkRead = ($i -eq 1) -or (($i % $syncInterval) -eq 0)
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
        Write-EngineStatus "opportunity_report" "Analyse des opportunites et consensus recents."
        $opportunityOutput = & python -m hl_observer opportunity-report --active-window-seconds 120 --consensus-window-seconds 4 --min-wallets 2 --max-deltas 5000 --max-opportunities 10 2>&1
        Write-CommandOutput -Lines $opportunityOutput -Label "opportunity-report"
        Write-EngineStatus "simulation_readiness" "Diagnostic de fraicheur et raisons de refus."
        $readinessOutput = & python -m hl_observer simulation-readiness --from-logs "$logsToSendDir" --fresh-window-seconds 120 2>&1
        Write-CommandOutput -Lines $readinessOutput -Label "simulation-readiness"
        Write-EngineStatus "warehouse_report" "Synthese warehouse local: wallets, deltas, decisions paper."
        $warehouseOutput = & python -m hl_observer warehouse-report --fresh-window-seconds 120 2>&1
        Write-CommandOutput -Lines $warehouseOutput -Label "warehouse-report"
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
