param(
    [int]$Port = 8794,
    [int]$IntervalSeconds = 5,
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
# 2026-07-08 (demande Flo "reproduire les methodes gagnantes + maths"): barrieres
# CALIBREES A LA VOLATILITE (triple-barrier hummingbot). Le moteur multiplie ces bps de
# BASE par clamp(range_coin/ref, 0.5, 2.5) -> ETH SL~30bps, KAITO~150bps. ref=30 = mediane
# empirique (barrier_calibration.py sur marks reels). SL 60/TP 120 = R:R 2:1, breakeven
# ~40% WR. Follow-leader reste la sortie PRIMAIRE; ces barrieres = filet + trailing.
# NB: ces defauts ps1 sont AUTORITAIRES (le python est lance ici); ils ECRASAIENT les
# valeurs du .cmd (Set...DefaultEnv ne pose que si non-defini) -> c'etait la cause du
# "PnL en centimes / SL trop serre". Alignes desormais sur la calibration.
# FORCE (comme le levier, ces defauts se "collaient" -> pas garantis actifs). Reponse a la
# question de Flo: le SL/TP est en bps de PRIX -> INDEPENDANT du notional (fire au meme % de
# prix que la position fasse 40 ou 1000). Mais a 10x l'impact MARGE est x10, donc on calibre:
# SL 60 base x vol(0.5-2.5)=30-150 bps prix = 3-15% de marge; TP 120 (laisse courir + trailing);
# catastrophe 180 bps (=18% de marge a 10x, backstop au-dessus du SL max 150); min-hold 45s
# (le SL protege plus vite a 10x). Liquidation ~10% de move -> la catastrophe (1.8%) coupe avant.
[Environment]::SetEnvironmentVariable("HYPERSMART_SLTP_ENABLED", "1", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_V26_VOL_BARRIERS", "1", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_V26_VOL_REF_RANGE_BPS", "30", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_V26_VOL_FACTOR_MIN", "0.8", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_V26_VOL_FACTOR_MAX", "1.5", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_V26_TP_FLOOR_BPS", "45", "Process")
# TIMEOUT DE POSITION (autopsie PnL 2026-07-11) : le bot DECIDE sur quelques minutes mais TENAIT
# ses positions 1,3 h en mediane (jusqu'a 8,4 h). L'edge du signal est mesure NUL des 5 minutes :
# au-dela, ce n'est plus une position de copie, c'est une exposition nue au marche.
[Environment]::SetEnvironmentVariable("HYPERSMART_SLTP_POSITION_TIMEOUT_MS", "1800000", "Process")

# ---------------------------------------------------------------------------------------------
# LE GRINDER (funding-arb delta-neutre) -- 2026-07-11.
# INCOHERENCE CORRIGEE : ces flags n'existaient QUE dans LANCER_HYPERSMART.cmd. Or ce .ps1 est
# l'AUTORITE de configuration. Lance directement (sans passer par le .cmd), le Grinder etait
# purement et simplement ETEINT -- et personne ne le voyait. Meme famille de bug que la double
# source de verite deja corrigee : le .cmd propose, le .ps1 dispose.
# Le funding-arb est la SEULE strategie dont l'esperance ne repose sur AUCUNE prediction.
[Environment]::SetEnvironmentVariable("HYPERSMART_FUNDING_ARB_PAPER", "1", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_V26_FUNDING_POLLER", "1", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_V26_FUNDING_POLL_INTERVAL_S", "120", "Process")
# ATTENTION -- SEUIL NON MESURE. `min_entry_edge_bps_per_hour = 2.5` exige un funding horaire
# tres au-dessus du taux de base Hyperliquid. C'est peut-etre un VERROU MORT (0 trade garanti),
# exactement comme le plafond de degradation a 12 bps sous un cout plancher de 14,2.
# NE PAS le baisser a l'aveugle : d'abord MESURER -> `python tools\measure_funding_gate.py`.
# On laisse donc la valeur du code telle quelle, et on enregistre le funding pour trancher.
[Environment]::SetEnvironmentVariable("HYPERSMART_RECORD_MICROSTRUCTURE", "1", "Process")

# ---------------------------------------------------------------------------------------------
# LE CARNET REEL -- 2026-07-11. LE MEME BUG QUE LE GRINDER : LA CAPACITE EXISTE, L'INTERRUPTEUR
# EST ETEINT.
#
# `l2_snapshot_cache` sait interroger le carnet L2 et en tirer le VRAI spread et le VRAI slippage.
# Mais AUCUN des deux flags n'etait pose :
#   * HYPERSMART_V26_BOOK_POLLER      -> le carnet n'etait JAMAIS collecte ;
#   * HYPERSMART_V26_LIVE_BOOK_COSTS  -> et jamais consomme.
#
# Resultat : TOUS les gates de liquidite et de cout tournaient sur des CONSTANTES
# (spread 6 bps, slippage 6 bps, profondeur 50 000 $) -- les memes pour BTC que pour un meme coin
# illiquide. Un gate de liquidite qui valide contre un carnet imaginaire ne protege de rien.
[Environment]::SetEnvironmentVariable("HYPERSMART_V26_BOOK_POLLER", "1", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_V26_LIVE_BOOK_COSTS", "1", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_V26_BOOK_POLL_INTERVAL_S", "10", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_V26_BOOK_POLL_MAX_COINS", "30", "Process")
# Fraicheur : au-dela, le carnet est PERIME et on retombe sur les constantes (marquees comme telles).
[Environment]::SetEnvironmentVariable("HYPERSMART_V26_BOOK_FRESH_S", "90", "Process")

# ---------------------------------------------------------------------------------------------
# GH-01 -- 2026-07-13. LA PILE V26 ENTIERE ETAIT ETEINTE. LA 7e FOIS.
#
# Le carnet L2 (ci-dessus, repare le 11/07) etait le MEME bug. Puis la jambe de funding (08/07).
# Puis le garde-fou lookahead. Puis le verrou du copy-follow. Puis `delta_neutral_carry`. Puis le
# bus GitHub (allume par defaut, jamais eteint). Et maintenant : **CINQ interrupteurs V26, codes,
# testes, BRANCHES -- et aucun n'etait pose dans un lanceur.**
#
# Pire : TROIS pierres tombales de `risk/tombstones.py` justifient l'enterrement d'anciens modules
# (kill_switch, circuit_breaker, loss_halts) par « remplace par protections_v26 / graded_halt
# (VIVANTS) ». Un remplacant ETEINT n'est pas un remplacant : on avait donc enterre les anciens
# garde-fous au profit de garde-fous qui ne s'executaient jamais.
#
# LA REGLE QU'ON S'APPLIQUE (et qui est de l'arithmetique, pas de la prudence) :
#   * un interrupteur qui ne fait que REFUSER -> ON L'ALLUME. Le pire qu'il puisse faire est de
#     refuser un trade ; or Q1 et Q3 ont MESURE qu'il n'y a pas d'edge a capturer. Le cout d'un
#     refus de trop est nul, le cout d'une perte evitee est reel. L'asymetrie est ecrasante.
#   * un interrupteur qui change la TAILLE ou le SENS -> il change le PnL, on le MESURE d'abord.
#     (C'est pourquoi HYPERSMART_V26_KELLY_LEADER reste ETEINT : voir risk/interrupteurs.py.)
#
# L'invariant est desormais TESTE : `tests/test_interrupteurs.py` echoue si un MASTER_FLAG du
# code n'est ni allume ici, ni declare eteint AVEC SON MOTIF. Un inventaire se fait une fois et
# se trompe ; un invariant se verifie a chaque execution.
[Environment]::SetEnvironmentVariable("HYPERSMART_V26_PROTECTIONS", "1", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_V26_GRADED_HALT", "1", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_V26_MARKET_QUALITY", "1", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_V26_ENTRY_VETOS_AUTHORITATIVE", "1", "Process")
# HYPERSMART_V26_KELLY_LEADER : VOLONTAIREMENT ABSENT (il change la TAILLE -> voir interrupteurs.py)

# GH-01 : `stop_per_pair` (freqtrade). Le StoplossGuard peut halter GLOBALEMENT ou PAR MARCHE.
# Par marche = 1 : un marche qui enchaine les stops est mis au coin, les autres continuent.
# C'est exactement `global_stop` + `stop_per_pair` -- reimplemente, pas copie (freqtrade est GPL).
[Environment]::SetEnvironmentVariable("HYPERSMART_V26_SG_PER_MARKET", "1", "Process")

# --------------------------------------------------------------------------------------------
# G2 -- LE NOYAU UNIQUE (2026-07-13). Un seul endroit decide, et il POSSEDE l'edge.
#
# Avant : `LocalDecisionEngine` construisait son RiskContext avec l'edge TEL QUE L'APPELANT LE
# DONNAIT. Le RiskEngine notait ce nombre avec une arithmetique impeccable... sans jamais
# questionner sa PROVENANCE. C'est exactement ainsi que TROIS edges FABRIQUES (fresh_opportunity,
# wallet_mirror_runtime, ws_price_discrepancy) ont pu vivre des mois dans le code.
#
# Allume, `noyau_unique.decider()` garde toute ENTREE : famille du signal (Q3, zones mortes
# PROUVEES), edge issu de la table MESUREE (Q1, jamais d'une formule), prix EXECUTABLES (Q2,
# jamais le mid), edge net apres couts reels. Il ne garde JAMAIS les sorties.
[Environment]::SetEnvironmentVariable("HYPERSMART_NOYAU_AUTORITAIRE", "1", "Process")

# --------------------------------------------------------------------------------------------
# COLLECTE DU CARNET -- 2026-07-11. LE POLLER SONDAIT UNE LISTE VIDE, EN SILENCE.
#
# Aucun `l2_book.jsonl` n'a JAMAIS ete ecrit : le poller ne sondait qu'une seule liste de coins,
# et un `if coins:` eteignait la collecte des qu'elle etait vide -- sans un log, sans une alerte.
# Ce socle garantit qu'il y a TOUJOURS quelque chose a sonder. Collecter des octets n'est pas
# ouvrir une position : le deny-by-default protege les ORDRES, pas les DONNEES.
#
# C'est la seule piste restante qui ne parie sur AUCUNE prediction : encaisser le spread au lieu
# de le payer. Le copy-trading, lui, est mesure sans edge (courbe edge/horizon plate).
# --------------------------------------------------------------------------------------------
[Environment]::SetEnvironmentVariable("HYPERSMART_V26_BOOK_DEFAULT_COINS", "BTC,ETH,SOL,HYPE,DOGE,XRP,SUI,AVAX,LINK,LTC", "Process")

# BALAYAGE COMPLET DU CARNET (2026-07-12).
# Premiere mesure reelle : spread median 0,30 bps (BTC 0,16 - SOL 0,13) contre 3,0 bps de frais
# maker aller-retour. Sur les majors, le market making est arithmetiquement mort.
# Les seuls spreads > frais vus sont sur des marches FINS. Pour savoir s'il EXISTE un marche
# assez large, il faut voir les ~230, pas les 8 majors. Rotation : 30 coins / cycle -> couverture
# complete en ~1,5 min, sans une seule requete de plus.
[Environment]::SetEnvironmentVariable("HYPERSMART_V26_BOOK_SWEEP_ALL", "1", "Process")

# ---------------------------------------------------------------------------------------------
# BUS GITHUB : ETEINT (decision de Flo, 2026-07-12).
# Il avait deja ete juge et ecarte (PF net 0,61), mais le DEFAUT DU CODE etait "priority" -- donc
# il tournait toujours, sans etre nulle part dans le launcher. Personne ne l'avait rallume : il
# n'avait jamais ete eteint.
# Ce qu'il faisait, verifie : ~810 evaluations de profils externes pour 21 entrees reelles, et des
# evenements "PAPER_ORDER_ACCEPTED" qui ne sont PAS des ordres (notionnel 0, sens NONE, PnL None).
# Ils ne corrompent PAS la comptabilite (prouve : 171 evaluations + 1 close -> closed_trades = 1),
# mais ils polluent le vocabulaire, l'ecran, et surtout le hot path.
# Les clones sous runtime/research/github_repos_v24/ restent intacts : bibliotheque, pas moteur.
# ---------------------------------------------------------------------------------------------
[Environment]::SetEnvironmentVariable("HYPERSMART_EXTERNAL_PROFILES_SCOPE", "off", "Process")

# --------------------------------------------------------------------------------------------
# EDGE EMPIRIQUE -- le bot n'ouvre plus sur un chiffre invente (2026-07-11).
#
# L'ancienne formule etait `dominance * 45 + bonus` : un "edge" en bps qui n'avait JAMAIS touche
# un prix. Le bot exige desormais une table MESUREE (runtime/calibration/empirical_edge.json,
# construite par tools/construire_calibration_edge.py sur 15 571 signaux reels).
#
# Cette table dit, aujourd'hui : edge median NEGATIF a toutes les fraicheurs mesurees
# (-2,17 / -0,56 / -0,23 bps) pour un cout de 13 bps.
# => Le bot va REFUSER d'ouvrir en copy. **Ce n'est pas une panne : c'est le bon comportement.**
#    Chaque position qu'il n'ouvre pas est de l'argent qu'il ne perd pas.
# --------------------------------------------------------------------------------------------
[Environment]::SetEnvironmentVariable("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "1", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_EDGE_CALIBRATION_PATH", "runtime/calibration/empirical_edge.json", "Process")

# ---------------------------------------------------------------------------------------------
# BUDGET DE RISQUE **PAR MOTEUR** -- 2026-07-11.
# Le garde-fou de session ne connaissait qu'UN SEUL PnL : si le Sniper perdait 40 $, le Grinder
# etait puni aussi (alors que le funding delta-neutre n'a rien a voir avec la cause). Et un
# Grinder gagnant MASQUAIT un Sniper qui saigne. Chaque moteur repond desormais de SES pertes.
# En % du capital : un budget en dur ne suit pas la taille du compte.
[Environment]::SetEnvironmentVariable("HYPERSMART_ENGINE_SOFT_LOSS_PCT", "4", "Process")    # 40 $ sur 1000
[Environment]::SetEnvironmentVariable("HYPERSMART_ENGINE_HARD_LOSS_PCT", "15", "Process")   # 150 $ sur 1000

# EXPOSITION DIRECTIONNELLE (2026-07-11) — LE GARDE-FOU QUI MANQUAIT.
# Observe en LIVE : 9 positions ouvertes, presque toutes SHORT, ~4 500 $ de notionnel sur 1 000 $
# de capital = 250 % du capital dans UN SEUL sens. Le gate de portefeuille ne regardait que
# l'exposition BRUTE (une somme d'abs()) : pour lui, 6 shorts et 1 long etaient "diversifies".
# Sur le run precedent, 97 % de la perte venait des shorts. Ce n'est pas un portefeuille :
# c'est le meme pari repete 9 fois.
[Environment]::SetEnvironmentVariable("HYPERSMART_MAX_NET_DIRECTIONAL_PCT", "100", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_MAX_COIN_NOTIONAL_PCT", "60", "Process")
# === CALIBRAGE #1 (candidat OOS-positif du replay 1.4M, 2026-07-09) : TP serre / SL large / trailing large ===
[Environment]::SetEnvironmentVariable("HYPERSMART_SLTP_TAKE_PROFIT_BPS", "110", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_SLTP_STOP_LOSS_BPS", "60", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_SLTP_TRAILING_BPS", "45", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS", "65", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_SLTP_BREAKEVEN_BUFFER_BPS", "10", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_SLTP_STOP_MIN_HOLD_MS", "45000", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_SLTP_CATASTROPHIC_STOP_BPS", "110", "Process")
Set-HyperSmartDefaultEnv "HYPERSMART_ADAPTIVE_PAPER_SIZING" "1"
Set-HyperSmartDefaultEnv "HYPERSMART_POSITIVE_PNL_REQUIRED_FOR_FUTURE_REVIEW" "1"
Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_INTERVAL_SECONDS" "$IntervalSeconds"
# Reglages SELECTIFS calibres sur les logs reels: Hyperliquid paper local,
# signaux frais uniquement, mais sans affamer le moteur avec un seuil impossible.
# 2026-07-10 (analyse replay): 30s -> 10s. La fraicheur est LE levier (degradation de copie plus
# faible => edge net qui survit aux couts). NB: on garde min_edge a 16 (pas 40) pour NE PAS rejeter
# les bons signaux frais type LIT +30bps / XYZ:META +36bps qu'on vient justement de debloquer.
[Environment]::SetEnvironmentVariable("HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS", "10000", "Process")
Set-HyperSmartDefaultEnv "HYPERSMART_REDUCE_MAX_SIGNAL_AGE_MS" "10000"
# 2026-07-10 (Flo) FIX-MID-COVERAGE : de bons signaux TRES frais a edge positif (ex LIT +30bps@0.8s)
# etaient rejetes CURRENT_MID_REQUIRED faute de mid allMids sur coins exotiques. On autorise le prix
# de reference du leader comme mid d'entree UNIQUEMENT si le signal est <= cette limite (la degradation
# de copie reste facturee en cout, le gate liquidite filtre encore l'illiquide). 0 = OFF (historique).
[Environment]::SetEnvironmentVariable("HYPERSMART_LEADER_MID_FALLBACK_MAX_AGE_MS", "5000", "Process")
Set-HyperSmartDefaultEnv "HYPERSMART_MIN_REDUCE_NOTIONAL_USDT" "0"
# FORCE (demande Flo: ouvrir beaucoup plus, mode grinder). Consensus 3->2 wallets.
# CALIBRAGE #1 : consensus >= 3 wallets (qualite du signal)
[Environment]::SetEnvironmentVariable("HYPERSMART_FUSION_COPY_MIN_WALLETS", "2", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_FRESH_OPPORTUNITY_MIN_WALLETS", "2", "Process")
Set-HyperSmartDefaultEnv "HYPERSMART_FUSION_COPY_COST_BUFFER_BPS" "24"
Set-HyperSmartDefaultEnv "HYPERSMART_DIRECT_ARBITRAGE_MIN_SPREAD_BPS" "30"
[Environment]::SetEnvironmentVariable("HYPERSMART_DIRECT_COPY_MIN_CONSENSUS_WALLETS", "1", "Process")
# V25: aligne sur le canal consensus (28 bps single-wallet). A 18 bps le canal
# fusion direct alimentait le book en entrees faibles (70 entrees vs 2 consensus).
Set-HyperSmartDefaultEnv "HYPERSMART_DIRECT_COPY_MIN_EDGE_BPS" "32"
Set-HyperSmartDefaultEnv "HYPERSMART_DIRECT_COPY_SINGLE_WALLET_EDGE_BONUS_BPS" "45"
# FORCE (bug sniper trouvé: 8s < latence WS réelle ~11s -> le sniper n'ouvrait JAMAIS).
# 2026-07-10 (analyse replay): 20s -> 10s (fraicheur sur le canal direct-copy aussi)
[Environment]::SetEnvironmentVariable("HYPERSMART_DIRECT_COPY_MAX_SIGNAL_AGE_MS", "10000", "Process")
Set-HyperSmartDefaultEnv "HYPERSMART_DIRECT_COPY_MIN_LIQUIDITY" "0.55"
Set-HyperSmartDefaultEnv "HYPERSMART_DIRECT_COPY_MAX_DEGRADATION_BPS" "24"
Set-HyperSmartDefaultEnv "HYPERSMART_DIRECT_COPY_MAX_OPEN_POSITIONS" "8"
# V25: 0.75 declenchait le mode protection quasi en permanence sur 1000 USDT.
Set-HyperSmartDefaultEnv "HYPERSMART_SESSION_LOSS_GUARD_USDC" "40.00"
Set-HyperSmartDefaultEnv "HYPERSMART_SESSION_LOSS_EDGE_BONUS_BPS" "10"
Set-HyperSmartDefaultEnv "HYPERSMART_DIRECT_COPY_RECOVERY_EDGE_BONUS_BPS" "12"
Set-HyperSmartDefaultEnv "HYPERSMART_DIRECT_COPY_RECOVERY_MIN_CONSENSUS" "2"
Set-HyperSmartDefaultEnv "HYPERSMART_DIRECT_COPY_RECOVERY_MIN_LIQUIDITY" "0.55"
# 2026-07-08 (demande Flo "laisser courir"): quality-guard OFF. Il fermait les positions
# a ~0.15% (non-evidencees) avant qu'elles atteignent leur SL/TP -> on capturait du bruit.
# Desormais SL/TP vol-ajustes + sortie du leader gouvernent (capture le vrai mouvement).
Set-HyperSmartDefaultEnv "HYPERSMART_LEGACY_POSITION_QUALITY_GUARD_ENABLED" "0"
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
# FORCE (demande Flo: le bot ouvrait trop peu). Plancher edge 40->22: atteignable mais
# toujours POSITIF apres couts. ~7%% des candidats passent (vs 0.4%% a 40) -> bien plus de trades.
# CALIBRAGE #1 : edge net >=16 bps, liquidite >=0.80, degradation copie <=12 bps (filtres qualite stricts)
[Environment]::SetEnvironmentVariable("HYPERSMART_SIMULATION_MIN_EDGE_BPS", "16", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE", "0.55", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS", "24", "Process")
# Historical conservative marker retained for launcher regression tests:
# Set-HyperSmartDefaultEnv "HYPERSMART_MAX_OPEN_POSITIONS" "12"
Set-HyperSmartDefaultEnv "HYPERSMART_MAX_OPEN_POSITIONS" "12"
# Historical conservative marker retained for launcher regression tests:
# Set-HyperSmartDefaultEnv "HYPERSMART_MAX_POSITION_USDT" "25"
Set-HyperSmartDefaultEnv "HYPERSMART_MAX_POSITION_USDT" "40"
Set-HyperSmartDefaultEnv "HYPERSMART_MAX_TOTAL_EXPOSURE_USDT" "400"
# 2026-07-08 (demande Flo "pas que des centimes"): levier perp realiste 5x. C'etait la
# CAUSE du PnL en centimes -> ce defaut ps1 (1) ecrasait le 5 du .cmd (Set...DefaultEnv
# ne pose que si non-defini, et le python etait lance par la ps1). notional = marge x 5.
# FORCE (pas "default"): une valeur "1" restee collee dans l'environnement (run precedent)
# faisait que Set-HyperSmartDefaultEnv sautait -> levier 1 au runtime -> notional 40 = centimes.
# On ECRASE explicitement pour garantir le levier. C'etait LA cause finale du PnL en centimes.
[Environment]::SetEnvironmentVariable("HYPERSMART_SIMULATION_LEVERAGE", "10", "Process")
# V27: firehose userFills MULTIPLEXE always-on -> jusqu'a 4x10=40 leaders suivis en
# temps reel (sub-seconde) au lieu du seul top-10 -> un MAXIMUM de signaux frais.
# Read-only / paper-only ; borne dure a 8 connexions (anti-ban) cote code.
[Environment]::SetEnvironmentVariable("HYPERSMART_FILLS_MULTIPLEX", "1", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_FILLS_MULTIPLEX_CONNECTIONS", "4", "Process")
# 2026-07-10 (levier A fraicheur) WS-FIRST: les canaux pousses en WS (allMids, userFills) ne
# consomment plus le budget REST -> plus de coins frais couverts par cycle ET des mids allMids
# plus frais (renforce le fix mid-coverage). Opt-in, no-op si OFF, lecture seule, teste.
[Environment]::SetEnvironmentVariable("HYPERSMART_WS_FIRST_COLLECT", "1", "Process")
# SIZING REEL (Flo, prouve a l'ecran: notional $50 -> PnL -0.12 centimes). Le $50 est la MARGE
# par position ; x levier 10 = notional $500 -> PnL = 500 x Dprix = DES DOLLARS. Solde 1000 /
# marge 50 = 20 positions. FORCE (ecrase le 12/40/400 set-if-unset + l'env colle Windows).
[Environment]::SetEnvironmentVariable("HYPERSMART_MAX_POSITION_USDT", "50", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_MAX_OPEN_POSITIONS", "20", "Process")
[Environment]::SetEnvironmentVariable("HYPERSMART_MAX_TOTAL_EXPOSURE_USDT", "1000", "Process")
# 2026-07-18 - mode sniper mono-wallet DECLARE FERME (sentinelle >= 1000). Voir le meme
# commentaire dans LANCER_HYPERSMART.cmd : edge de copie mesure a -7,97 bps hors echantillon,
# leader CONTRARIEN. Le plancher de 30 laissait croire que le mode vivait alors que rien ne
# pouvait le franchir. Aucune ouverture perdue : il etait deja infranchissable. Reversible.
Set-HyperSmartDefaultEnv "HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS" "9999"
Set-HyperSmartDefaultEnv "HYPERSMART_TOP_WALLET_SAMPLE_LIMIT" "8000"
# V25 (2026-07-03): hard halt a 2.50 USDC (=0.25% de 1000) gelait la session
# entiere apres une poignee de stops; 644 refus SESSION_HARD_LOSS_HALT observes,
# y compris des edges 64-68 bps. Soft 0.25%, hard 1% du capital de depart.
Set-HyperSmartDefaultEnv "HYPERSMART_SESSION_GUARD_SOFT_LOSS_USDC" "40.00"
Set-HyperSmartDefaultEnv "HYPERSMART_SESSION_GUARD_HARD_LOSS_USDC" "150.00"
Set-HyperSmartDefaultEnv "HYPERSMART_SESSION_GUARD_EXTRA_EDGE_BPS" "10"
Set-HyperSmartDefaultEnv "HYPERSMART_SESSION_GUARD_MIN_CONSENSUS" "2"
Set-HyperSmartDefaultEnv "HYPERSMART_SESSION_GUARD_MIN_LIQUIDITY" "0.50"
Set-HyperSmartDefaultEnv "HYPERSMART_COIN_SIDE_LOSS_COOLDOWN_USDC" "12.00"
# Cliquets coin / leader (audit calibrage 2026-07-11) : etaient EN DUR a 0.50 $ / 0.35 $ dans
# routes.py -> un coin etait BANNI pour toute la session des -2.00 $ et un leader des -1.40 $,
# soit UNE seule perte normale (notional 500 $). Desormais configurables et a l'echelle reelle.
# Bannissement definitif = 4x ces valeurs (coin -60 $, leader -48 $) = un vrai probleme, pas du bruit.
Set-HyperSmartDefaultEnv "HYPERSMART_COIN_SESSION_LOSS_COOLDOWN_USDC" "15.00"
Set-HyperSmartDefaultEnv "HYPERSMART_LEADER_SESSION_LOSS_COOLDOWN_USDC" "12.00"
Set-HyperSmartDefaultEnv "HYPERSMART_COIN_SIDE_LOSS_RECOVERY_EXTRA_EDGE_BPS" "12"
Set-HyperSmartDefaultEnv "HYPERSMART_COIN_SIDE_LOSS_MIN_CONSENSUS" "2"
Set-HyperSmartDefaultEnv "HYPERSMART_COIN_SIDE_LOSS_MIN_LIQUIDITY" "0.50"
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
                ($_.CommandLine -like "*hl_observer.research.explain_cli*") -or
                ($_.CommandLine -like "*python*hl_observer*") -or
                ($_.CommandLine -like "*-m hl_observer*")
            )
        }
    } catch {
        Write-LauncherLog "runtime process lookup skipped: $($_.Exception.Message)"
        return @()
    }
}

function Stop-HyperSmartProcessTree {
    param([int]$ProcId)
    if (-not $ProcId -or $ProcId -eq $PID) { return }
    # /T tue TOUT l'arbre (enfants: workers multiprocessing du poller, connexions firehose,
    # interface.py de l'IA lancee par ia_train_loop.ps1). Sans /T, Stop-Process ne tuait que
    # le parent -> les enfants survivaient en orphelins (bug "Q ne ferme pas tout", Flo 2026-07-10).
    try { & taskkill.exe /PID $ProcId /T /F *> $null }
    catch { try { Stop-Process -Id $ProcId -Force -ErrorAction SilentlyContinue } catch {} }
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
            Write-LauncherLog "Stopping HyperSmart runtime tree pid=$($process.ProcessId)"
            Stop-HyperSmartProcessTree -ProcId $process.ProcessId
        } catch {
            Write-LauncherLog "Stop skipped for pid=$($process.ProcessId): $($_.Exception.Message)"
        }
    }
    # 21/07 (Flo : « Q doit correctement terminer la session ») : les 6 BOUCLES DE
    # COLLECTEURS (start /b depuis LANCER) n'etaient ni dans $startedProcesses ni matchees
    # par les motifs runtime -> elles survivaient a Q en ORPHELINES puis se doublaient a la
    # relance. On les tue par leur ligne de commande, en arbre (cmd + python enfant).
    try {
        $collectorLoops = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match 'boucle_collecteur' })
        foreach ($loopProc in $collectorLoops) {
            Write-LauncherLog "Stopping collector loop tree pid=$($loopProc.ProcessId)"
            try { Stop-HyperSmartProcessTree -ProcId $loopProc.ProcessId } catch {}
        }
    } catch { Write-LauncherLog "collector loops stop skipped: $($_.Exception.Message)" }
    # Tuer aussi ce qui SQUATTE le port UI 8794 -> sinon la relance recharge l'ancien
    # serveur (ancien code, positions a 40) et le neuf ne peut pas se lancer (demande Flo:
    # "c'est a toi de gerer que Q ferme tout").
    try {
        $portPids = @(Get-NetTCPConnection -LocalPort 8794 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
        foreach ($pp in $portPids) {
            if ($pp -and $pp -ne $PID) {
                Write-LauncherLog "Freeing UI port 8794 pid=$pp"
                Stop-HyperSmartProcessTree -ProcId $pp
            }
        }
    } catch { Write-LauncherLog "port 8794 free skipped: $($_.Exception.Message)" }
    # FILET DE SECURITE (audit 2026-07-11) : tuer AUSSI les PID que CE lanceur a demarres
    # (UI, poller, IA shadow, stream). Avant, $startedProcesses etait rempli mais JAMAIS utilise :
    # l'arret reposait uniquement sur la correspondance de ligne de commande. Un processus dont la
    # ligne de commande ne matchait aucun motif survivait a "Q". Ici on tue par PID connu, en arbre.
    foreach ($startedPid in @($script:startedProcesses)) {
        try {
            Write-LauncherLog "Stopping launcher-started tree pid=$startedPid"
            Stop-HyperSmartProcessTree -ProcId $startedPid
        } catch {}
    }
    # 2e passe de securite: re-tuer tout ce qui reste apres 600 ms.
    Start-Sleep -Milliseconds 600
    foreach ($process in @(Get-HyperSmartRuntimeProcesses)) {
        try { Stop-HyperSmartProcessTree -ProcId $process.ProcessId } catch {}
    }
    foreach ($startedPid in @($script:startedProcesses)) {
        try { Stop-HyperSmartProcessTree -ProcId $startedPid } catch {}
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
            Write-LauncherLine "Arret ancien processus HyperSmart (arbre) pid=$($process.ProcessId)"
            Stop-HyperSmartProcessTree -ProcId $process.ProcessId
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
