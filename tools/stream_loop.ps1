# HyperSmart V16 - MOTEUR TEMPS REEL: flux WebSocket Hyperliquid PERSISTANT.
# Demarre AUTOMATIQUEMENT par LANCER_HYPERSMART.cmd. Lecture seule, 0 ordre / 0 cle / 0 signature.
# S'abonne en continu aux fills des 10 MEILLEURS leaders (cap HL=10) et stocke chaque fill FRAIS
# a la seconde ou il arrive (sub-seconde) -> entrees vraiment fraiches (vs snapshot REST ~10s).
# Auto-restart si la connexion tombe. LOG en chemin ASCII (sans accent) pour eviter le probleme
# d'encodage PowerShell: un run precedent ecrivait un log VIDE dans un dossier mojibake.
#
# WATCHDOG (regression 2026-07-07): le python du stream s'etait fige DES LE DEMARRAGE
# (connect WebSocket/DNS sans timeout) et n'est JAMAIS sorti de son segment de 300s ->
# zero fill temps reel pendant toute la session, silencieusement. Le python a maintenant
# un timeout de connexion (user_fills_live.py), et CE script ne fait plus confiance au
# python pour sortir: si un segment depasse duration + grace, le process est tue et relance.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONPATH = (Join-Path $root 'src') + ';' + $env:PYTHONPATH
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
} catch { }
$log = Join-Path $root 'logs\hypersmart_stream.log'   # ASCII uniquement -> pas de mojibake, log visible
$segOut = Join-Path $root 'logs\hypersmart_stream_segment.out.tmp'
$segErr = Join-Path $root 'logs\hypersmart_stream_segment.err.tmp'
$stopFile = $env:HYPERSMART_RUNTIME_STOP_FILE
if ([string]::IsNullOrWhiteSpace($stopFile)) {
    $stopFile = Join-Path $root 'runtime\data\hypersmart_runtime.stop'
}
$durationSeconds = 300
if ($env:HYPERSMART_STREAM_SEGMENT_SECONDS) { try { $durationSeconds = [Math]::Max(30, [int]$env:HYPERSMART_STREAM_SEGMENT_SECONDS) } catch { } }
$maxLeaders = 10
if ($env:HYPERSMART_STREAM_MAX_LEADERS) { try { $maxLeaders = [Math]::Min(10, [Math]::Max(1, [int]$env:HYPERSMART_STREAM_MAX_LEADERS)) } catch { } }
$graceSeconds = 120
if ($env:HYPERSMART_STREAM_WATCHDOG_GRACE_SECONDS) { try { $graceSeconds = [Math]::Max(30, [int]$env:HYPERSMART_STREAM_WATCHDOG_GRACE_SECONDS) } catch { } }
function Write-StreamLog {
    param([string]$Message)
    try {
        $Message | Out-File -FilePath $log -Encoding utf8 -Append
    } catch { }
}
function Test-StopRequested {
    try {
        return (Test-Path -LiteralPath $stopFile)
    } catch {
        return $false
    }
}
function Copy-SegmentOutputToLog {
    foreach ($f in @($segOut, $segErr)) {
        try {
            if (Test-Path -LiteralPath $f) {
                Get-Content -LiteralPath $f -ErrorAction SilentlyContinue | ForEach-Object { Write-StreamLog ([string]$_) }
                Remove-Item -LiteralPath $f -ErrorAction SilentlyContinue
            }
        } catch { }
    }
}

Write-StreamLog "=== HyperSmart Stream demarre $(Get-Date -Format o) ==="
while (-not (Test-StopRequested)) {
    $budgetSeconds = $durationSeconds + $graceSeconds
    Write-StreamLog "--- (re)connexion stream $(Get-Date -Format o), duration=${durationSeconds}s, maxLeaders=$maxLeaders, watchdog=${budgetSeconds}s ---"
    Remove-Item -LiteralPath $segOut -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $segErr -ErrorAction SilentlyContinue
    # -u = sortie non bufferisee: on voit la vie du stream meme en cours de segment.
    $pyArgs = "-u -m hl_observer live-user-fills-stream --network-read --duration-seconds $durationSeconds --max-leaders $maxLeaders"
    $p = $null
    try {
        $p = Start-Process -NoNewWindow -PassThru -FilePath "python" -ArgumentList $pyArgs -WorkingDirectory $root -RedirectStandardOutput $segOut -RedirectStandardError $segErr
    } catch {
        Write-StreamLog "ERREUR: impossible de demarrer python ($($_.Exception.Message)); nouvelle tentative dans 10s."
        for ($i = 0; $i -lt 10; $i++) { if (Test-StopRequested) { break }; Start-Sleep -Seconds 1 }
        continue
    }
    $deadline = (Get-Date).AddSeconds($budgetSeconds)
    while ($p -and -not $p.HasExited -and (Get-Date) -lt $deadline -and -not (Test-StopRequested)) {
        Start-Sleep -Seconds 5
    }
    $killed = $false
    if ($p -and -not $p.HasExited) {
        if (Test-StopRequested) {
            Write-StreamLog "Stop demande: arret du python du stream."
        } else {
            Write-StreamLog "WATCHDOG: segment stream depasse ${budgetSeconds}s sans sortir (connect/recv fige?) -> kill + relance."
        }
        try { $p.Kill() } catch { }
        try { $p.WaitForExit(10000) | Out-Null } catch { }
        $killed = $true
    }
    $code = $null
    try { $code = $p.ExitCode } catch { $code = $null }
    Copy-SegmentOutputToLog
    if (Test-StopRequested) {
        break
    }
    if ($killed) {
        Write-StreamLog "--- stream tue par watchdog, relance dans 5s ---"
    } else {
        Write-StreamLog "--- stream sorti (code $code), relance dans 5s si la session est encore active ---"
    }
    for ($i = 0; $i -lt 5; $i++) {
        if (Test-StopRequested) { break }
        Start-Sleep -Seconds 1
    }
}
Write-StreamLog "=== HyperSmart Stream stop demande $(Get-Date -Format o) ==="
