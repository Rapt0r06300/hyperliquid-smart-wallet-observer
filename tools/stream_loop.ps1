# HyperSmart V16 - MOTEUR TEMPS REEL: flux WebSocket Hyperliquid PERSISTANT.
# Demarre AUTOMATIQUEMENT par LANCER_HYPERSMART.cmd. Lecture seule, 0 ordre / 0 cle / 0 signature.
# S'abonne en continu aux fills des 10 MEILLEURS leaders (cap HL=10) et stocke chaque fill FRAIS
# a la seconde ou il arrive (sub-seconde) -> entrees vraiment fraiches (vs snapshot REST ~10s).
# Auto-restart si la connexion tombe. LOG en chemin ASCII (sans accent) pour eviter le probleme
# d'encodage PowerShell: le run precedent ecrivait un log VIDE dans un dossier mojibake "logs Ã envoyer".
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
$stopFile = $env:HYPERSMART_RUNTIME_STOP_FILE
if ([string]::IsNullOrWhiteSpace($stopFile)) {
    $stopFile = Join-Path $root 'runtime\data\hypersmart_runtime.stop'
}
$durationSeconds = 300
if ($env:HYPERSMART_STREAM_SEGMENT_SECONDS) { try { $durationSeconds = [Math]::Max(30, [int]$env:HYPERSMART_STREAM_SEGMENT_SECONDS) } catch { } }
$maxLeaders = 10
if ($env:HYPERSMART_STREAM_MAX_LEADERS) { try { $maxLeaders = [Math]::Min(10, [Math]::Max(1, [int]$env:HYPERSMART_STREAM_MAX_LEADERS)) } catch { } }
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

Write-StreamLog "=== HyperSmart Stream demarre $(Get-Date -Format o) ==="
while (-not (Test-StopRequested)) {
    Write-StreamLog "--- (re)connexion stream $(Get-Date -Format o), duration=${durationSeconds}s, maxLeaders=$maxLeaders ---"
    & python -m hl_observer live-user-fills-stream --network-read --duration-seconds $durationSeconds --max-leaders $maxLeaders 2>&1 |
        ForEach-Object { Write-StreamLog ([string]$_) }
    $code = $LASTEXITCODE
    if (Test-StopRequested) {
        break
    }
    Write-StreamLog "--- stream sorti (code $code), relance dans 5s si la session est encore active ---"
    for ($i = 0; $i -lt 5; $i++) {
        if (Test-StopRequested) { break }
        Start-Sleep -Seconds 1
    }
}
Write-StreamLog "=== HyperSmart Stream stop demande $(Get-Date -Format o) ==="
