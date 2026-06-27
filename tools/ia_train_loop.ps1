# HyperSmart - boucle d'entrainement IA locale (V13).
# Demarree AUTOMATIQUEMENT par LANCER_HYPERSMART.cmd (rien a lancer separement).
# Paper-only, lecture seule, 0 ordre / 0 cle / 0 signature.
# Toutes les ~60 s (ajustable HYPERSMART_V13_TRAIN_INTERVAL_SEC): ingere les trades clotures du
# snapshot live, accumule les exemples, reentraine le modele et met a jour le panneau "Modele IA".
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONPATH = (Join-Path $root 'src') + ';' + $env:PYTHONPATH
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
} catch { }

$samples = Join-Path $root 'runtime\ml\training_samples.jsonl'
$model   = Join-Path $root 'runtime\models\trade_model_v13.json'
$explout = Join-Path $root 'runtime\ml\explanations_latest.json'
$logdir = Join-Path $root ("logs\logs " + [char]0x00E0 + " envoyer")
if (-not (Test-Path $logdir)) { New-Item -ItemType Directory -Force -Path $logdir | Out-Null }
$trainlog = Join-Path $logdir 'hypersmart_ia_train.log'

function Write-IaTrainLog {
    param([string]$Message)
    try {
        $Message | Out-File -FilePath $trainlog -Encoding utf8 -Append
    } catch { }
}

# Cadence d'apprentissage (secondes). Defaut 60 s ; ajustable via HYPERSMART_V13_TRAIN_INTERVAL_SEC.
$interval = 60
if ($env:HYPERSMART_V13_TRAIN_INTERVAL_SEC) { try { $interval = [int]$env:HYPERSMART_V13_TRAIN_INTERVAL_SEC } catch { } }

# RESET DES LOGS IA A CHAQUE LANCEMENT (demande utilisateur: logs frais a chaque ouverture,
# sans degrader l'intelligence). Le modele entraine et runtime\ml\training_samples.jsonl restent intacts.
try {
    if (Test-Path $trainlog) { Clear-Content -Path $trainlog -ErrorAction SilentlyContinue }
    foreach ($n in @('hypersmart_ia_history.jsonl','hypersmart_ia_report.json','hypersmart_ia_explanations.json')) {
        $p = Join-Path $logdir $n
        if (Test-Path $p) { Remove-Item $p -Force -ErrorAction SilentlyContinue }
    }
} catch { }

while ($true) {
    $snap = Get-ChildItem -Path (Join-Path $root 'logs') -Recurse -Filter 'simulation_snapshot_latest.json' -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($snap) {
        try {
            Write-IaTrainLog ("--- train $(Get-Date -Format o) snapshot=$($snap.FullName) ---")
            & python -m hl_observer.ml.train_cli --ingest-snapshot $snap.FullName --samples $samples --out $model --context ALL 2>&1 |
                ForEach-Object { Write-IaTrainLog ([string]$_) }
        } catch { }
        try {
            # Explications des decisions (Ollama si actif, sinon regles) -> cache lu par le dashboard.
            & python -m hl_observer.research.explain_cli --snapshot $snap.FullName --out $explout 2>&1 |
                ForEach-Object { Write-IaTrainLog ([string]$_) }
        } catch { }
        try {
            # Copier l'historique d'apprentissage + dernier rapport + explications dans logs a envoyer
            # (ils restent aussi dans runtime\ pour le dashboard). Ainsi ton zip contient l'activite IA.
            if (Test-Path ($model + '.history.jsonl')) { Copy-Item ($model + '.history.jsonl') (Join-Path $logdir 'hypersmart_ia_history.jsonl') -Force }
            if (Test-Path ($model + '.report.json'))   { Copy-Item ($model + '.report.json')   (Join-Path $logdir 'hypersmart_ia_report.json')   -Force }
            if (Test-Path $explout)                     { Copy-Item $explout                     (Join-Path $logdir 'hypersmart_ia_explanations.json') -Force }
        } catch { }
    }
    Start-Sleep -Seconds $interval
}
