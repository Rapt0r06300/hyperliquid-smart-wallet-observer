param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$OutputDir = "",
    [switch]$WithSubmodules,
    [switch]$ForceRefresh
)

$ErrorActionPreference = "Stop"

function Invoke-GitCapture {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [string]$WorkingDirectory = ""
    )

    $oldPreference = $ErrorActionPreference
    $oldLocation = (Get-Location).Path
    try {
        $ErrorActionPreference = "Continue"
        if ($WorkingDirectory) {
            Set-Location -LiteralPath $WorkingDirectory
        }
        $output = (& git @Arguments 2>&1 | Out-String).Trim()
        $exitCode = $LASTEXITCODE
        return [pscustomobject]@{
            ExitCode = $exitCode
            Output = $output
        }
    } finally {
        Set-Location -LiteralPath $oldLocation
        $ErrorActionPreference = $oldPreference
    }
}

if (-not $OutputDir) {
    $OutputDir = Join-Path $ProjectRoot "runtime\research\github_repos_v24"
}

$resolvedProject = (Resolve-Path $ProjectRoot).Path
$outputPath = [System.IO.Path]::GetFullPath($OutputDir)

if (-not $outputPath.StartsWith($resolvedProject, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDir must stay inside the project for this local research install: $outputPath"
}

$repos = @(
    @{ id = "01_cloddsbot"; url = "https://github.com/alsk1992/CloddsBot" },
    @{ id = "02_harrier_prediction_markets_toolkits"; url = "https://github.com/HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits" },
    @{ id = "03_mrfadiai_polymarket_bot"; url = "https://github.com/MrFadiAi/Polymarket-bot" },
    @{ id = "04_polymarket_lp_tool"; url = "https://github.com/lihanyu81/polymarket_lp_tool" },
    @{ id = "05_polyweather"; url = "https://github.com/yangyuan-zhen/PolyWeather" },
    @{ id = "06_composio_polymarket_kalshi_arbitrage_bot"; url = "https://github.com/Composio-HQ/polymarket-kalshi-arbitrage-bot" },
    @{ id = "07_awesome_prediction_market_tools"; url = "https://github.com/aarora4/Awesome-Prediction-Market-Tools" },
    @{ id = "08_polyterm"; url = "https://github.com/NYTEMODEONLY/polyterm" },
    @{ id = "09_mlmodelpoly"; url = "https://github.com/txbabaxyz/mlmodelpoly" },
    @{ id = "10_polyrec"; url = "https://github.com/txbabaxyz/polyrec" },
    @{ id = "11_prediction_market_backtesting"; url = "https://github.com/evan-kolberg/prediction-market-backtesting" },
    @{ id = "12_polybot"; url = "https://github.com/ent0n29/polybot" },
    @{ id = "13_polymarket_agents"; url = "https://github.com/Polymarket/agents" },
    @{ id = "14_tradingview_lightweight_charts"; url = "https://github.com/tradingview/lightweight-charts" },
    @{ id = "15_chaininsighter_solana_copy_trading_bot"; url = "https://github.com/ChainInsighter/Solana-Copy-trading-bot" },
    @{ id = "16_immutal0_solana_copytrading_bot"; url = "https://github.com/Immutal0/Solana-CopyTrading-Bot" },
    @{ id = "17_rezzecup_whale_wallet_mirror_copy_trader"; url = "https://github.com/Rezzecup/whale-wallet-mirror-copy-trader" },
    @{ id = "18_neron888_polymarket_copy_trading_bot"; url = "https://github.com/Neron888/Polymarket-copy-trading-bot" },
    @{ id = "19_terauss_polymarket_copy_trading_bot"; url = "https://github.com/terauss/Polymarket-Copy-Trading-Bot" },
    @{ id = "20_warp_id_solana_trading_bot"; url = "https://github.com/warp-id/solana-trading-bot" },
    @{ id = "21_tony_42069_trader_tony_v4"; url = "https://github.com/tony-42069/trader-tony-v4" },
    @{ id = "22_freqtrade"; url = "https://github.com/freqtrade/freqtrade" },
    @{ id = "23_octobot"; url = "https://github.com/drakkar-software/octobot" },
    @{ id = "24_jlowo_gengar_polymarket_bot"; url = "https://github.com/JLowo/gengar_polymarket_bot" },
    @{ id = "25_djienne_polymarket_bot"; url = "https://github.com/djienne/Polymarket-bot" },
    @{ id = "26_jonmaa_btc_polymarket_bot"; url = "https://github.com/Jonmaa/btc-polymarket-bot" },
    @{ id = "27_carlosibcu_polymarket_kalshi_btc_arbitrage_bot"; url = "https://github.com/CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot" },
    @{ id = "28_jackhuang166_hyberliquid_arbitrage_bot"; url = "https://github.com/Jackhuang166/hyberliquid-arbitrage-bot" },
    @{ id = "29_jackhuang166_hyberliquid_arbitrage"; url = "https://github.com/Jackhuang166/hyberliquid-arbitrage" },
    @{ id = "30_rustjesty_hyperliquid_drift_arbitrage_bot"; url = "https://github.com/rustjesty/hyperliquid-drift-arbitrage-bot" },
    @{ id = "31_notlelouch_arbibot"; url = "https://github.com/notlelouch/ArbiBot" },
    @{ id = "32_gajesh2007_funding_arb_bot"; url = "https://github.com/gajesh2007/funding-arb-bot" },
    @{ id = "33_hummingbot"; url = "https://github.com/hummingbot/hummingbot" },
    @{ id = "34_drakkar_triangular_arbitrage"; url = "https://github.com/Drakkar-Software/Triangular-Arbitrage" },
    @{ id = "35_enarjord_passivbot"; url = "https://github.com/enarjord/passivbot" },
    @{ id = "36_pydevtop_interexchange_arbitrage_bot"; url = "https://github.com/pydevtop/interexchange-arbitrage-bot" },
    @{ id = "37_ramilexe_crypto_arbitrage_bot"; url = "https://github.com/ramilexe/crypto-arbitrage-bot" }
)

New-Item -ItemType Directory -Force -Path $outputPath | Out-Null

$manifest = [System.Collections.Generic.List[object]]::new()
$cloneArgsBase = @("clone", "--depth", "1")
if ($WithSubmodules) {
    $cloneArgsBase += @("--recurse-submodules", "--shallow-submodules")
}

foreach ($repo in $repos) {
    $target = Join-Path $outputPath $repo.id
    $status = "UNKNOWN"
    $message = ""
    $branch = $null
    $commit = $null
    $licenseFiles = @()
    $fileCount = 0
    $sizeBytes = 0

    try {
        if (Test-Path $target) {
            if (Test-Path (Join-Path $target ".git")) {
                if ($ForceRefresh) {
                    $fetch = Invoke-GitCapture -Arguments @("-C", $target, "fetch", "--depth", "1", "origin")
                    if ($fetch.ExitCode -eq 0) {
                        $status = "UPDATED_FETCHED"
                    } else {
                        $status = "FETCH_FAILED"
                        $message = $fetch.Output
                    }
                } else {
                    $status = "ALREADY_PRESENT"
                }
            } else {
                $children = @(Get-ChildItem -LiteralPath $target -Force -ErrorAction SilentlyContinue)
                if ($children.Count -eq 0) {
                    Remove-Item -LiteralPath $target -Force
                    $cloneArgs = @($cloneArgsBase + @($repo.url, $target))
                    $clone = Invoke-GitCapture -Arguments $cloneArgs
                    if ($clone.ExitCode -eq 0) {
                        $status = "CLONED"
                    } else {
                        $status = "FAILED"
                        $message = $clone.Output
                    }
                } else {
                    $status = "TARGET_EXISTS_NOT_GIT"
                    $message = "Target exists but is not a git checkout; left untouched."
                }
            }
        } else {
            $cloneArgs = @($cloneArgsBase + @($repo.url, $target))
            $clone = Invoke-GitCapture -Arguments $cloneArgs
            if ($clone.ExitCode -eq 0) {
                $status = "CLONED"
            } else {
                $status = "FAILED"
                $message = $clone.Output
            }
        }

        if (Test-Path (Join-Path $target ".git")) {
            $branchResult = Invoke-GitCapture -Arguments @("-C", $target, "rev-parse", "--abbrev-ref", "HEAD")
            $commitResult = Invoke-GitCapture -Arguments @("-C", $target, "rev-parse", "--short", "HEAD")
            if ($branchResult.ExitCode -eq 0) { $branch = $branchResult.Output }
            if ($commitResult.ExitCode -eq 0) { $commit = $commitResult.Output }
            $licenseFiles = @(Get-ChildItem -LiteralPath $target -File -Force -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -match '^(LICENSE|LICENCE|COPYING|NOTICE)(\..*)?$' } |
                Select-Object -ExpandProperty Name)
            $files = @(Get-ChildItem -LiteralPath $target -Recurse -File -Force -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -notmatch '\\\.git\\' })
            $fileCount = $files.Count
            $sizeBytes = [int64](($files | Measure-Object -Property Length -Sum).Sum)
        }
    } catch {
        $status = "FAILED"
        $message = $_.Exception.Message
    }

    $manifest.Add([pscustomobject]@{
        id = $repo.id
        url = $repo.url
        target = $target
        status = $status
        message = $message
        branch = $branch
        commit = $commit
        license_files = $licenseFiles
        file_count = $fileCount
        size_bytes = $sizeBytes
        installed_at = (Get-Date).ToString("o")
    }) | Out-Null

    Write-Host ("[{0}] {1} -> {2}" -f $status, $repo.id, $target)
    if ($message) { Write-Host ("  {0}" -f $message) }
}

$manifestPath = Join-Path $outputPath "EXTERNAL_REPOS_MANIFEST.json"
$manifestJson = $manifest | ConvertTo-Json -Depth 6
$manifestWrittenPath = $manifestPath
try {
    $manifestJson | Set-Content -LiteralPath $manifestPath -Encoding UTF8 -ErrorAction Stop
} catch {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $manifestWrittenPath = Join-Path $outputPath ("EXTERNAL_REPOS_MANIFEST_$stamp.json")
    $manifestJson | Set-Content -LiteralPath $manifestWrittenPath -Encoding UTF8 -ErrorAction Stop
    Write-Host ("[WARN] canonical manifest locked, wrote fallback manifest: {0}" -f $manifestWrittenPath)
}

$reportPath = Join-Path $ProjectRoot "docs\research\HYPERSMART_EXTERNAL_REPOS_INSTALL.md"
$okCount = @($manifest | Where-Object { $_.status -in @("CLONED", "ALREADY_PRESENT", "UPDATED_FETCHED") }).Count
$failedCount = @($manifest | Where-Object { $_.status -eq "FAILED" }).Count
$report = @(
    "# HyperSmart - installation locale des GitHub externes",
    "",
    "Date: $(Get-Date -Format o)",
    "",
    ("Dossier local: ``{0}``" -f $outputPath),
    "",
    "Ces depots sont installes comme bibliotheque locale de recherche/portage. Le runtime HyperSmart lit ce manifest via `external_github_bridge` et les expose en profils paper prioritaires dans la simulation; le code upstream est preserve et n'est pas execute directement.",
    "",
    "- depots demandes: $($repos.Count)",
    "- installes/presents: $okCount",
    "- echecs: $failedCount",
    "- submodules: $([bool]$WithSubmodules)",
    ("- manifest: ``{0}``" -f $manifestWrittenPath),
    "",
    "| Repo | Statut | Branche | Commit | Fichiers | Taille MB | Chemin |",
    "|---|---|---|---|---:|---:|---|"
)

foreach ($row in $manifest) {
    $sizeMb = [math]::Round(($row.size_bytes / 1MB), 2)
    $report += ("| [{0}]({1}) | {2} | {3} | {4} | {5} | {6} | ``{7}`` |" -f $row.id, $row.url, $row.status, $row.branch, $row.commit, $row.file_count, $sizeMb, $row.target)
}

$report += @(
    "",
    "## Garde-fous",
    "",
    "- Aucun dependency install global n'a ete lance.",
    "- Le branchement runtime passe par des adaptateurs paper-only; le code upstream n'est pas execute/importé directement dans `src/hl_observer`.",
    "- Les licences devront etre respectees avant copie directe dans HyperSmart.",
    "- Toute logique de trading reel reste interdite dans le runtime: portage en simulation paper/read-only seulement.",
    "- Le dossier est ignore par Git via `.gitignore`."
)

$report | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host ""
Write-Host "manifest=$manifestWrittenPath"
Write-Host "report=$reportPath"
Write-Host "installed_or_present=$okCount failed=$failedCount total=$($repos.Count)"

if ($failedCount -gt 0) {
    exit 2
}
