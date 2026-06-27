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
function Write-StreamLog {
    param([string]$Message)
    try {
        $Message | Out-File -FilePath $log -Encoding utf8 -Append
    } catch { }
}

Write-StreamLog "=== HyperSmart Stream demarre $(Get-Date -Format o) ==="
while ($true) {
    Write-StreamLog "--- (re)connexion stream $(Get-Date -Format o) ---"
    & python -m hl_observer live-user-fills-stream --network-read --duration-seconds 0 --max-leaders 10 2>&1 |
        ForEach-Object { Write-StreamLog ([string]$_) }
    $code = $LASTEXITCODE
    Write-StreamLog "--- stream sorti (code $code), relance dans 5s ---"
    Start-Sleep -Seconds 5
}
