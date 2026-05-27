param(
    [string]$Root,
    [int]$IntervalSeconds = 60,
    [int]$MaxLeaders = 50,
    [int]$LeadersPerPoll = 5,
    [int]$BackfillDays = 1,
    [int]$FreshWindowMinutes = 15,
    [int]$MaxPages = 1,
    [string]$PublicTradeCoins = "BTC,ETH,SOL,HYPE,DOGE,XRP,BNB,ENA,AVAX,LINK",
    [int]$PublicTradeScanSeconds = 20,
    [int]$PublicTradeMaxWallets = 1500,
    [int]$MaxRuns = 288
)

$ErrorActionPreference = "Continue"
if ([string]::IsNullOrWhiteSpace($Root)) {
    $Root = Split-Path -Parent $PSScriptRoot
}

$logDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir "hypersmart_simulation_live.log"

function Write-LoopLog {
    param([string]$Message)
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $logPath -Value "[$stamp] $Message"
}

Write-LoopLog "Simulation poll loop started. root=$Root interval=$IntervalSeconds pool=$MaxLeaders leadersPerPoll=$LeadersPerPoll"

for ($i = 1; $i -le $MaxRuns; $i++) {
    $safeLeadersPerPoll = [Math]::Max(1, [Math]::Min($LeadersPerPoll, $MaxLeaders))
    $leaderOffset = (($i - 1) * $safeLeadersPerPoll) % [Math]::Max(1, $MaxLeaders)
    Write-LoopLog "poll $i/$MaxRuns starting offset=$leaderOffset batch=$safeLeadersPerPoll pool=$MaxLeaders"
    try {
        Push-Location $Root
        $wsOutput = & python -m hl_observer live-public-scan --network-read --store --duration-seconds $PublicTradeScanSeconds --coins $PublicTradeCoins --max-wallets $PublicTradeMaxWallets --promote-top $MaxLeaders --no-report 2>&1
        foreach ($line in $wsOutput) {
            Write-LoopLog $line
        }
        $output = & python -m hl_observer copy-run --interval $IntervalSeconds --dry-run --network-read --copy-max-leaders $safeLeadersPerPoll --leader-offset $leaderOffset --backfill-days $BackfillDays --fresh-window-minutes $FreshWindowMinutes --max-pages $MaxPages --no-report 2>&1
        foreach ($line in $output) {
            Write-LoopLog $line
        }
        Pop-Location
    } catch {
        Write-LoopLog "poll failed: $($_.Exception.Message)"
        try { Pop-Location } catch {}
    }
    if ($i -lt $MaxRuns) {
        Start-Sleep -Seconds $IntervalSeconds
    }
}

Write-LoopLog "Simulation poll loop finished."
