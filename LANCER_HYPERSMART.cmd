@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
set "ALINA_LAUNCH_RUN_ID=%DATE%_%TIME%_%RANDOM%_%RANDOM%"
set "ALINA_LAUNCH_MODE=autopilot"
set "ALINA_LAUNCH_PYTHON=unresolved"
set "ALINA_LAUNCH_OUTPUT_LOG=runtime/logs/launchers/LANCER_HYPERSMART.log"
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" START preflight "launcher-entry" ""
cd /d "%~dp0"
set "ALINA_PROJECT_ROOT=%~dp0."
REM item 9/10 : code de sortie propage de bout en bout. Jamais un exit /b 0 systematique en cas d'echec.
set "RC=0"
REM Un double-clic est une session interactive : meme si le moteur rend la main avec
REM un code 0, la fenetre reste ouverte pour afficher le bilan au lieu de disparaitre.
set "HYPERSMART_INTERACTIVE_LAUNCH=0"
if "%~1"=="" set "HYPERSMART_INTERACTIVE_LAUNCH=1"
REM PORTABILITE : choisit en priorite le Python embarque relatif au dossier.
REM Le PATH est modifie uniquement pour cette session du lanceur et ses enfants.
call "%ALINA_PROJECT_ROOT%\tools\portable_env.cmd"
if defined HYPERSMART_PYTHON set "ALINA_LAUNCH_PYTHON=%HYPERSMART_PYTHON%"
if errorlevel 1 (
  echo   HyperSmart ne peut pas demarrer sans runtime Python valide.
  set "RC=30"
  goto :fin
)
if not defined HYPERSMART_PYTHON (
  echo   HYPERSMART_PYTHON non defini par portable_env. Abandon.
  set "RC=31"
  goto :fin
)
REM ENG-033 : verifier Python 3.11+ (requis pour tomllib, TaskGroup, ExceptionGroup).
"%HYPERSMART_PYTHON%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>nul
if errorlevel 1 (
  echo   [ERREUR] Python 3.11+ requis. Version detectee :
  "%HYPERSMART_PYTHON%" --version
  echo   Installez Python 3.11+ ou mettez a jour tools\portable_env.cmd.
  set "RC=32"
  goto :fin
)
REM ENG-086 / ENG-034 : prevol PowerShell — requis pour launcher_pids.json et le simulateur.
REM Degradation douce : le moteur fonctionne sans, mais status/PID/dashboard seront limites.
where powershell >nul 2>nul
if errorlevel 1 (
  echo   [ATTENTION] PowerShell introuvable. Les fonctions status/PID/dashboard seront degradees.
  echo   Le moteur de collecte et le paper trading fonctionnent normalement sans PowerShell.
)
REM ENG-088 : verifier les dependances critiques (websockets requis pour BBO/userFills/lab).
"%HYPERSMART_PYTHON%" -c "import websockets" 2>nul
if errorlevel 1 (
  echo   [ATTENTION] Le module Python 'websockets' est absent. Les collecteurs WS seront morts.
  echo   Installez : pip install websockets
)
REM ============================================================================
REM  LANCER_HYPERSMART.cmd  --  LANCEUR RUNTIME OFFICIEL (2026-11-06)
REM ----------------------------------------------------------------------------
REM  Double-clic SANS argument = RUNTIME CORE : prevol securite/paper-only,
REM  verrou d'instance unique, moteur + dashboard + poller + stream leaders,
REM  allMids, BBO et userFills read-only. Les backtests/replays/recherches restent hors du hot path.
REM
REM  Sous-commandes (LANCER_HYPERSMART.cmd <cmd>) :
REM    status stop restart restart-userfills collectors report test audit
REM    replay moisson verify-oos github-push menu self-test
REM  Avances : audit-moissonneur premier-raw kill-userfills verif-l2 sonde notif-test
REM
REM  Les anciens .cmd de la racine sont ABSORBES ici (archives en .cmd.txt dans
REM  docs\archive\legacy_cmd\). Le seul second lanceur officiel est
REM  ANALYSER_BACKTESTS_REPLAYS.cmd, reserve aux analyses hors runtime.
REM  Securite : lecture seule marche. 0 ordre reel, 0 argent, 0 cle, 0 signature.
REM ============================================================================
if not "%~1"=="" set "ALINA_LAUNCH_MODE=command"
if not "%~1"=="" goto :dispatch

:autopilot
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ---- PREVOL : verrou d'instance unique (evite tout double lancement) ----
REM ENG-029 : port variabilise (une seule definition au lieu de ~6 hardcodes).
set "HYPERSMART_PORT=8794"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
REM ENG-039 : prevol unique — creation de TOUS les dossiers runtime.
if not exist "runtime\data" mkdir "runtime\data" >nul 2>&1
if not exist "runtime\logs" mkdir "runtime\logs" >nul 2>&1
if not exist "runtime\logs\launcher" mkdir "runtime\logs\launcher" >nul 2>&1
if not exist "runtime\reports\legacy\moisson" mkdir "runtime\reports\legacy\moisson" >nul 2>&1
if not exist "runtime\rapports\checkpoint_oos_shadow" mkdir "runtime\rapports\checkpoint_oos_shadow" >nul 2>&1
"%HYPERSMART_PYTHON%" "%~dp0tools\cmd_progress.py" start > "%TEMP%\alina_cmd_start.tmp" 2>nul
set /p ALINA_CMD_START=<"%TEMP%\alina_cmd_start.tmp"
REM ENG-032 : prevol joignabilite reseau HL avant lancement (evite de consommer un restart).
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" STEP autopilot "network-preflight" ""
"%HYPERSMART_PYTHON%" "%~dp0tools\cmd_progress.py" phase "Prevol reseau HL" 1 7
"%HYPERSMART_PYTHON%" -c "from hl_observer.ops.network_health import assert_hl_reachable; assert_hl_reachable()"
set "NETWORK_RC=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" RESULT autopilot "network-preflight" "%NETWORK_RC%"
if not "%NETWORK_RC%"=="0" (
  echo.
  echo   [ERREUR] API Hyperliquid NON JOIGNABLE. Verifiez la connexion Internet.
  echo   Le moteur ne demarre pas pour eviter un crash immediat.
  echo.
  set "RC=5"
  goto :fin
)
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" STEP autopilot "port-owner-check" ""
"%HYPERSMART_PYTHON%" "%~dp0tools\cmd_progress.py" phase "Verification port" 2 7
"%HYPERSMART_PYTHON%" -m hl_observer.ops.port_owner --root "%~dp0." --port %HYPERSMART_PORT%
set "PORT_OWNER_RC=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" RESULT autopilot "port-owner-check" "%PORT_OWNER_RC%"
REM ENG-062 : "deja lance" = code dedie 8 (pas 0) pour distinguer de "demarre OK".
if "%PORT_OWNER_RC%"=="2" (
  echo.
  echo   HyperSmart tourne DEJA ^(proprietaire du port %HYPERSMART_PORT% verifie^).
  echo   Pour redemarrer proprement : LANCER_HYPERSMART.cmd restart
  echo.
  set "RC=8"
  goto :fin
)
if not "%PORT_OWNER_RC%"=="0" (
  echo.
  echo   [PORT %HYPERSMART_PORT% REFUSE] Un processus etranger occupe le port, ou son proprietaire est inverifiable.
  echo   HyperSmart ne le tue pas et ne demarre pas. Ferme ce processus manuellement puis relance.
  echo.
  set "RC=32"
  goto :fin
)
REM === PORTABILITE INTRINSEQUE ===
REM Ce prevol s'execute AVANT la creation du verrou/PID du lancement courant. Il ne purge
REM l'etat machine qu'au tout premier demarrage ou apres un vrai changement de PC/chemin.
REM Sur un demarrage ordinaire au meme endroit il est strictement non destructif.
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" STEP autopilot "portable-runtime-and-state-preparation" ""
"%HYPERSMART_PYTHON%" "%~dp0tools\cmd_progress.py" phase "Premier lancement / portabilite" 3 7
"%HYPERSMART_PYTHON%" -m hl_observer.ops.premier_lancement --racine "%~dp0."
set "PORTABLE_PREP_RC=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" RESULT autopilot "portable-runtime-and-state-preparation" "%PORTABLE_PREP_RC%"
if not "%PORTABLE_PREP_RC%"=="0" (
  echo.
  echo   [PREVOL] Environnement NO_GO : droits, runtime ou securite a corriger.
  echo   Aucun verrou, PID ou collecteur du nouveau lancement n'a ete cree.
  echo.
  set "RC=7"
  goto :fin
)
REM === ITEM 11 : VERROU d'instance ATOMIQUE (le seul controle du port ne suffit PAS pendant le warmup,
REM   avant que l'UI ne lie 8794). Deux double-clics simultanes ne lancent JAMAIS deux recoltes.
if not exist "runtime\data" mkdir "runtime\data" >nul 2>&1
"%HYPERSMART_PYTHON%" -m hl_observer.ops.verrou_lanceur acquerir "%~dp0."
set "LAUNCH_LOCK_RC=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" RESULT autopilot "exclusive-launch-lock" "%LAUNCH_LOCK_RC%"
if not "%LAUNCH_LOCK_RC%"=="0" (
  echo.
  echo   HyperSmart demarre DEJA ^(warmup en cours, verrou d'instance present^). Un seul lancement a la fois.
  echo   Pour redemarrer proprement : LANCER_HYPERSMART.cmd restart
  echo.
  set "RC=3"
  goto :fin
)
REM ---- PREVOL : registre PID/run_id + dossier logs du lanceur ----
if not exist "runtime\data" mkdir "runtime\data" >nul 2>&1
if not exist "runtime\logs\launcher" mkdir "runtime\logs\launcher" >nul 2>&1
REM ENG-063 : registre PID avec detection d'echec (plus silencieux).
powershell -NoProfile -Command "$git=Join-Path '%~dp0' 'tools\git\cmd\git.exe'; $commit=if(Test-Path $git){& $git -C '%~dp0.' rev-parse --short HEAD 2>$null}else{''}; $o=[ordered]@{ role='launcher_autopilot'; note='pid_reels_dans_lanceur_pids.json'; run_id=([guid]::NewGuid().ToString('N').Substring(0,12)); port=$env:HYPERSMART_PORT; demarre=(Get-Date).ToString('s'); commit=$commit }; ($o | ConvertTo-Json -Compress) | Set-Content -Encoding UTF8 (Join-Path '%~dp0' 'runtime\data\launcher_pids.json')" 2>nul
if errorlevel 1 (
  echo   [ATTENTION] Ecriture de launcher_pids.json echouee ^(PowerShell absent ?^).
  echo   Le moteur fonctionne, mais status/stop ne verront pas ce run.
)
REM Le verificateur OOS planifie est strictement opt-in.
REM Utiliser "LANCER_HYPERSMART.cmd verify-oos install" pour l'activer explicitement.
set "HL_ENV=paper"
set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
set "HYPERSMART_MODE=SIMULATION_ONLY_UNTIL_MANUAL_REVIEW"
REM ENG-070 : assert paper-only fail-closed — refuse de demarrer si un flag mainnet/testnet vaut 1.
"%HYPERSMART_PYTHON%" -c "from hl_observer.security.paper_assert import assert_paper_only; assert_paper_only()"
if errorlevel 1 (
  echo.
  echo   [SECURITE CRITIQUE] Un flag mainnet/testnet est actif. Demarrage REFUSE.
  echo.
  set "RC=7"
  goto :fin
)
REM ENG-071 / OPS-7 : journaliser les invariants securite + config au demarrage.
"%HYPERSMART_PYTHON%" -c "from hl_observer.ops.config_dump import dump_config; dump_config(r'%~dp0.')"
set "HYPERSMART_STARTUP_PROFILE=harvest"
set "HYPERSMART_V12_SQLITE_PATH=%~dp0runtime\data\hypersmart_v12_artifacts.sqlite3"
rem ANTI-BLOAT: coupe le stockage brut (payloads L2/leaderboard/fills) qui a fait
rem gonfler la DB a 29 Go puis crasher. Le PnL/ledger n en depend pas. Mettre a 0
rem seulement si tu veux le replay brut (avec cap manuel).
set "HYPERSMART_DISABLE_RAW_STORAGE=1"
rem Item 11 : le brut SQL reste coupe (anti-bloat), mais on ACTIVE un stockage brut FICHIER BORNE
rem (shards gzip + quota + retention, aucune suppression silencieuse). 10 Go de plafond hot.
set "HYPERSMART_RAW_STORAGE_QUOTA_GO=10"
REM REPLAY: enregistre candidates.jsonl + marks.jsonl pour l'A/B replay apres le run.
REM Ecriture CAPEE (60 Mo marks / 20 Mo candidates, rotation last-N) -> jamais de
REM re-bloat comme les 29 Go. Sans ce flag, le run 48h ne produit AUCUNE donnee replay.
set "HYPERSMART_V26_RECORD_CANDIDATES=1"
set "HYPERSMART_V26_RECORD_PATH=%~dp0runtime\replay"
set "HYPERSMART_UI_STATE_DIR=%~dp0runtime\data"
REM ENG-014 VARIABLE MORTE : jamais lue par Python. Conservee comme intention documentee.
set "HYPERSMART_POSITIVE_PNL_REQUIRED_FOR_FUTURE_REVIEW=1"
REM Reglages SELECTIFS Hyperliquid: runtime principal = Hyperliquid read-only + paper local.
REM Aucun moteur secondaire n'est lance par defaut.
REM CALIBRATION 2026-06-19 (basee sur l'analyse de 9154 decisions reelles du ledger):
REM   - les leaders font surtout ADD/REDUCE (9 OPEN sur 9154) -> ADD doit pouvoir entrer.
REM   - latence reelle public-WS: age median ~11 s -> 6000 ms etait inatteignable; 60000 ms (protocole
REM     11/2026) reste selectif et rejette les fills retardes de plusieurs heures (backfill).
REM   - edge net observe rarement >=35 bps -> seuil ramene a un niveau atteignable mais POSITIF apres couts.
REM Toujours paper-only / read-only / deny-by-default. Aucune promesse de PnL: c'est un test honnete.
REM CORRECTIF WINRATE 2026-06-24 (analyse run perdant 24/06: 721 trades / 12.5%% WR / -20.61$ vs
REM session SAINE 21/06: 79 trades / 53.2%% WR / +0.80$). Cause: fenetre 45 s = on entre TROP TARD
REM (on chasse un move deja parti), le prix revient et le SL synthetique coupe -> pertes en serie.
REM Le snapshot le dit: "les entrees arrivent trop tard; consensus tres chaud vise 4 s". On resserre
REM a 15000 ms (fresh): admet la latence WS mediane ~11 s, rejette le chasing. Reversible.
REM AUDIT ENG-009 : ouverture=10s, reduction=15s (L152), direct_copy=10s (L409). Asymetrie voulue:
REM les reductions tolerent plus de latence que les ouvertures (15s vs 10s). Pas de doublon.
set "HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS=10000"
REM 06/11 — CAPITAL PAPER CANONIQUE Copy-Vault : 350 USDT, aligne sur le contrat de replay/labo.
REM Ce montant est une base de simulation, jamais un solde exchange et jamais une autorisation d'ordre.
set "HYPERSMART_SIMULATION_INITIAL_EQUITY_USDT=350"
REM Legacy ARBITRAGE DE DISLOCATION paper v1 : QUARANTAINE DEFINITIVE.
REM Le cross-venue actif est EXPERIMENTAL_PAPER v2 (deux jambes, couts complets, ledger isole).
REM Re-activer ce flag recreerait un second chemin economique ambigu : contrat runtime = 0.
set "HYPERSMART_ARB_DISLOCATION_PAPER=0"
REM 23/07 — VOIE EXPERIMENTAL_PAPER (decision Flo) : ouvre de VRAIES positions SIMULEES tout de suite
REM (cross-venue survivants geles / lead-lag / copy-vaults) SANS attendre la preuve OOS. Ledger, budget
REM et limites ISOLES du livre live (experimental_paper_ledger.jsonl). Admission = frais + executable +
REM edge net > 0 apres couts. L'allocateur strict de promotion et le no-real-trade restent intacts.
REM ENG-024 AUDIT : ledger isole dans experimental_paper_*_ledger.jsonl — PnL canonique non pollue.
set "HYPERSMART_EXPERIMENTAL_PAPER=1"
REM 23/07 (rectif Flo) — COHORTE EXPLORATORY_PAPER : apprend MAINTENANT sans attendre l'OOS complet.
REM Ouvre sur mouvement LIVE d'un vault retenu + edge PRELIMINAIRE positif (copy_prelim_edge.json) +
REM L2<1s + VWAP + couts complets + sortie definie. Budget $300, max 3, pertes plafonnees. Isole. 0 reel.
REM ENG-024 AUDIT : ledger isole dans exploratory_paper_ledger.jsonl — PnL canonique non pollue.
set "HYPERSMART_EXPLORATORY_PAPER=1"
REM 11/2026 — CROSS-VENUE GELE : seul Copy-Vault est le scope actif (OBJECTIF.md).
REM Le cross-venue experimental (dislocation, lead-lag) est GELE. Remettre a 0 = re-litiger.
set "HYPERSMART_EXPERIMENTAL_CROSS_VENUE_GELE=1"
set "HYPERSMART_REDUCE_MAX_SIGNAL_AGE_MS=15000"
REM Les reductions leader sont proportionnelles a NOTRE position paper. Sur un compte
REM de simulation 350 USDT, une vraie sortie partielle peut valoir moins de 10 USDT:
REM elle doit rester visible dans le ledger et le PnL au lieu d'etre ignoree.
set "HYPERSMART_MIN_REDUCE_NOTIONAL_USDT=0"
REM ENG-011 CONSENSUS UNIFIE : les 3 variables ci-dessous + DIRECT_COPY_MIN_CONSENSUS_WALLETS (L472)
REM designent le MEME concept (minimum de wallets leaders concordants). Toutes fixees a 2.
REM Un wallet solo doit fournir +45 bps de bonus edge (SINGLE_WALLET_EDGE_BONUS_BPS).
set "HYPERSMART_FUSION_COPY_MIN_WALLETS=2"
set "HYPERSMART_FRESH_OPPORTUNITY_MIN_WALLETS=2"
set "HYPERSMART_FUSION_COPY_COST_BUFFER_BPS=24"
set "HYPERSMART_DIRECT_ARBITRAGE_MIN_SPREAD_BPS=30"
set "HYPERSMART_V9_PIPELINE_AUTHORITATIVE=1"
set "HYPERSMART_SIMULATION_ALLOW_ADD_AS_ENTRY=0"
REM PREUVE D'ENTREE PAR PALIERS (demande user: positions 1-2 wallets "pas assez prouvees",
REM mais NE PAS bloquer): 2+ wallets d'accord = preuve par le CONSENSUS -> edge net >=10 suffit.
REM 1 seul wallet = il faut une preuve par la FORCE du signal -> edge net >=22 exige (15->22).
REM Un wallet solo fort passe quand meme (pas de blocage); le consensus reste la voie facile.
REM CORRECTIF 2026-06-24: edge net releve (10->15, solo 22->28) pour exiger une marge claire APRES
REM les couts (cost_model ~12 bps). "Moins de trades, plus propres": on ne prend que les signaux a
REM edge net franchement positif. Aucun fake, aucun edge negatif jamais accepte.
REM 2026-07-08: plancher edge copy releve 28->40 (replay causal: la selectivite passe le PnL net positif,
REM les 2 gros perdants venaient des trades a edge marginal). Reversible.
REM ── VARIABLE MORTE RETIREE (11/2026) : CARRY_MAX_BREAK_EVEN_H n'etait lu par aucun
REM    module Python. Le carry est DESACTIVE (HYPERSMART_CARRY_DISABLED=1 ci-dessous).
REM ENG-004 AUDIT : MIN_EDGE_BPS=16 bps est la valeur active (plancher d'entree).
REM Les commentaires perimés evoquant 28 ou 40 bps ont ete purges. 16 bps > cout
REM round-trip 9 bps (taker/taker) → edge positif exige PAR CONSTRUCTION.
set "HYPERSMART_SIMULATION_MIN_EDGE_BPS=16"
set "HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE=0.55"
set "HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS=24"
REM 2026-07-18 — MODE SNIPER MONO-WALLET DECLARE FERME (sentinelle >= 1000), pas desactive en
REM douce : un plancher de 55 (ou 30) laissait croire que le mode vivait, alors que RIEN ne
REM pouvait le franchir. Nos mesures : edge de copie -7,97 bps sur 24 133 signaux hors
REM echantillon, leader CONTRARIEN. Copier un seul wallet, c'est payer pour perdre.
REM ⚠️ Ca ne retire AUCUNE ouverture aujourd'hui (le mode etait deja infranchissable de fait).
REM REVERSIBLE : le jour ou on mesure un edge de copie POSITIF, on remet un vrai plancher.
set "HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS=9999"
REM GATE V12 AUTORITATIF (2026-06-24): le gate unifie (source/quotes/fraicheur/liquidite/edge net)
REM devient CONTRAIGNANT en intersection plus stricte: un candidat ne passe que si le score ET le
REM gate V12 acceptent. Ne peut QUE reduire les trades (plus propres), jamais en creer. Mettre 0
REM pour repasser en shadow (observation seule). Sans effet sur la securite: 0 ordre reel.
set "HYPERSMART_V12_GATE_AUTHORITATIVE=1"
REM MODELE IA V13 (gratuit, local): chemins partages serveur <-> entraineur. Le serveur lit
REM le modele si present et affiche le panneau "Modele IA". Le modele reste en SHADOW
REM (observation, ne decide pas) tant que HYPERSMART_V13_MODEL_AUTHORITATIVE=0. Quand le
REM panneau montre qu'il bat la baseline (Brier), passe-le a 1 pour qu'il FILTRE les trades.
REM Entrainement: lance ENTRAINER_IA_AUTO.cmd a cote (apprend des trades clotures).
set "HYPERSMART_V13_MODEL_PATH=%~dp0runtime\models\trade_model_v13.json"
set "HYPERSMART_V13_MODEL_REPORT=%~dp0runtime\models\trade_model_v13.json.report.json"
set "HYPERSMART_V13_SAMPLES_PATH=%~dp0runtime\ml\training_samples.jsonl"
set "HYPERSMART_V13_MODEL_MIN_P=0.5"
set "HYPERSMART_V13_MODEL_AUTHORITATIVE=0"
REM ENG-014 VARIABLE MORTE : V13_TRAIN_INTERVAL_SEC jamais lue par Python (V13 non-authoritative).
REM Cadence d'apprentissage IA en secondes — reprendra effet quand V13_MODEL_AUTHORITATIVE=1.
set "HYPERSMART_V13_TRAIN_INTERVAL_SEC=60"
REM IA EXPLICATIVE LOCALE (Ollama) toujours active avec le serveur. Si Ollama est installe sur
REM ta machine (gratuit, https://ollama.com) + un modele tire (ex: "ollama pull llama3.2"),
REM les explications seront formulees par l'IA ; sinon repli automatique sur des phrases-regles
REM (toujours claires, gratuites). Aucune API payante, tout reste local.
set "HYPERSMART_V13_OLLAMA_ENABLED=1"
set "HYPERSMART_V13_OLLAMA_HOST=http://127.0.0.1:11434"
set "OLLAMA_BASE_URL=http://127.0.0.1:11434"
set "HYPERSMART_V13_OLLAMA_MODEL=llama3.2"
set "OLLAMA_MODEL=llama3.2"
set "HYPERSMART_V13_OLLAMA_API_STYLE=auto"
set "HYPERSMART_V13_OLLAMA_UI_TIMEOUT_SEC=2"
set "HYPERSMART_V13_OLLAMA_TIMEOUT_SEC=12"
set "HYPERSMART_V13_OLLAMA_TEMPERATURE=0.1"
set "HYPERSMART_V13_OLLAMA_NUM_PREDICT=700"
REM IA V14 signal-rater: score/confiance de recherche sur candidats deja calcules.
REM Ne peut jamais creer une entree; peut seulement recommander un veto conservateur dans les logs.
set "HYPERSMART_V14_OLLAMA_MIN_AI_SCORE=0.62"
set "HYPERSMART_V14_OLLAMA_MIN_CONFIDENCE=0.55"
set "HYPERSMART_V13_EXPL_PATH=%~dp0runtime\ml\explanations_latest.json"
REM --- V14 (2026-06-25) PROMOTIONS OPT-IN (shadow par defaut = 0, n'agissent jamais seules) ---
REM #168 SIGNAL PRIMAIRE BALEINE: quand =1, une entree que le score accepterait est REFUSEE
REM   s'il n'y a PAS de fill de baleine frais et significatif derriere (shadow_whale_primary).
REM   Intersection plus stricte: ne peut QUE reduire les trades (plus propres), jamais en creer.
REM   Si le signal est inconnu (None) -> ne bloque pas. 0 = observation seule.
set "HYPERSMART_V14_WHALE_PRIMARY_AUTHORITATIVE=0"
REM #170 GARDE DE WARMUP: quand =1, pas de decision tant que le contexte (bars HTF/features) n'est
REM   pas pret. Inactif (no-op) tant que les bars ne sont pas cables dans le hot-path -> sans danger.
set "HYPERSMART_V14_WARMUP_AUTHORITATIVE=0"
REM #175 FENETRE DE CONSENSUS CHAUDE (~4 s chaud / 15 s max): quand =1, refuse une entree dont le
REM   signal est deja HORS fenetre fraiche (calcule depuis l'age du signal). Ne peut QUE reduire
REM   les trades. 0 = observation seule. (Anti-"course-poursuite" sur des moves deja partis.)
REM ACTIVE 2026-06-25: n'entrer QUE dans la fenetre fraiche (anti-chasing). Les logs montraient
REM beaucoup d'entrees STALE/retardees -> on les refuse desormais (ne peut que reduire les trades).
set "HYPERSMART_V14_CONSENSUS_WINDOW_AUTHORITATIVE=1"
REM #182 COUT D'EXECUTION dans le NET EDGE (LE PLUS GROS LEVIER "moins de trades, plus propres"):
REM   quand =1, refuse une entree dont la marge NETTE apres couts (frais HL + demi-spread +
REM   slippage calcule sur la taille ET la liquidite REELLES) tombe sous le plancher ci-dessous.
REM   Ne peut QUE reduire les trades. 0 = observation seule (les champs shadow_* restent calcules).
REM ACTIVE 2026-06-25: refuser toute entree dont la marge nette APRES couts reels (frais+spread+
REM slippage selon taille/liquidite) est <= 0. Tue les entrees marginales qui saignent en frais.
set "HYPERSMART_V14_EXEC_COST_AUTHORITATIVE=1"
set "HYPERSMART_V14_EXEC_MIN_NET_EDGE_BPS=0"
REM #183 QUALITE D'ENTREE (smart-money + profondeur): quand =1, refuse une entree si le leader
REM   n'est pas assez "smart money" (score < SMART_MONEY_MIN_SCORE) OU si la liquidite est sous le
REM   minimum (signaux REELS: score leader + liquidite). Ne peut QUE reduire les trades. 0 = obs.
set "HYPERSMART_V14_ENTRY_QUALITY_AUTHORITATIVE=0"
set "HYPERSMART_V14_SMART_MONEY_MIN_SCORE=60"
REM --- SORTIE: SUIVI DU LEADER (preuve par les donnees, 2026-06-24) ---
REM PREUVE: la session SAINE 21/06 (53.2%% WR, +0.80$) avait SL/TP synthetiques DESACTIVES et
REM tenait la position JUSQU'A CE QUE LE LEADER reduise/ferme (vrai copy-trading). Le run perdant
REM 24/06 (12.5%% WR, -20.61$) avait active SL40/TP30/trailing25: sur des entrees retardees, le SL
REM coupe au moindre bruit AVANT que le leader sorte -> beaucoup de petites pertes + saignee de couts.
REM Donc on REVIENT au profil gagnant: sortie pilotee par le LEADER, pas par un stop synthetique.
REM (PnL toujours au VRAI prix marche, jamais de faux PnL. Pour reactiver un stop catastrophe large
REM seulement: SLTP_ENABLED=1, STOP_LOSS_BPS=150, TAKE_PROFIT_BPS=99999, TRAILING_BPS=0.)
REM CORRECTIF PERTE 2026-06-25 (analyse snapshot: gagnants realises a +0.006$ / perdants jusqu'a
REM -5$ = "on coupe les gagnants, on laisse courir les perdants"). On REACTIVE un STOP CATASTROPHE
REM LARGE seulement (pas de TP, pas de trailing): coupe les rares desastres (-5$) SANS etrangler les
REM gagnants (les sorties restent pilotees par le leader). 150 bps de prix = 1.5% (x5 levier = 7.5%
REM de la marge). C'est le profil documente comme sur. Vrais prix, aucune triche.
REM CORRECTIF 2026-06-26 (analyse run 56.9%% WR mais -20$): les GAGNANTS ne realisaient que +0.04$
REM (miettes via les reduces du leader) alors que les PERDANTS atteignaient -0.11$ (2.6x) -> meme a
REM 57%% de reussite, l'esperance est negative. On capture donc NOUS-MEMES les gagnants et on coupe
REM les perdants tot: TP 60 bps (+3%% de marge a 5x) >= SL 45 bps (-2.25%%), trailing 30 bps pour
REM laisser courir un gagnant qui part fort. A 57%% WR: 0.57*60 - 0.43*45 = +15 bps/trade AVANT frais
REM (12 bps round-trip) = positif. Les entrees sont deja FRAICHES (gates actifs) donc le SL protege
REM au lieu de hacher (≠ piege du 24/06 ou les entrees etaient tardives). Vrais prix, aucune triche.
set "HYPERSMART_SLTP_ENABLED=1"
REM V24: profil paper plus reactif et plus stable pour une session 350 USDT.
REM Les logs montraient que levier 5x + sorties tardives amplifiaient les frais
REM et les pics. On reste en simulation locale, au vrai prix marche, sans ordre.
REM ==========================================================================
REM BARRIERES CALIBREES A LA VOLATILITE (2026-07-08, demande Flo: "reproduire les
REM methodes gagnantes + maths complexes"). Au lieu de bps FIXES (incoherents: la
REM range 15min va de 4 bps sur ETH a 135 sur KAITO = facteur 34x), les barrieres
REM sont en UNITES DE VOLATILITE du coin (triple-barrier hummingbot + ATR-stop):
REM le moteur multiplie ces bps de BASE par clamp(range_coin/ref, 0.5, 2.5) -> ETH
REM calme = SL ~30 bps, KAITO volatil = SL ~150 bps. ref=30 bps = MEDIANE EMPIRIQUE
REM des ranges (calibree sur marks.jsonl reels via barrier_calibration.py).
REM ESPERANCE nette EXIGEE positive: E = p(TP-c) - (1-p)(SL+c). SL 60 / TP 120 = R:R
REM 2:1, cout 12 bps -> breakeven ~40%% WR (bas, atteignable en copiant du smart-money).
REM Follow-leader reste la sortie PRIMAIRE; ces barrieres = filet + trailing (laisse
REM courir le gagnant). Recalibrable sur les donnees 48h. Reversible (VOL_BARRIERS=0).
set "HYPERSMART_V26_VOL_BARRIERS=1"
set "HYPERSMART_V26_VOL_REF_RANGE_BPS=30"
set "HYPERSMART_V26_VOL_FACTOR_MIN=0.8"
set "HYPERSMART_V26_VOL_FACTOR_MAX=1.5"
REM ENG-006 AUDIT — PROFIL SLTP REEL (valeurs actives, pas les commentaires perimés) :
REM   TP=110 bps | SL=60 bps | Trail=45 bps (activation a 65 bps) | Breakeven buffer=10 bps
REM   Hold min=45s | Timeout=30min | Catastrophic=110 bps
REM   Ratio R:R = 110/60 = 1.83:1, breakeven WR ~35% (atteignable en copie smart-money).
REM   Les commentaires perimés decrivant TP60/SL45 ou TP120/SL60 ont ete purges.
set "HYPERSMART_SLTP_TAKE_PROFIT_BPS=110"
set "HYPERSMART_SLTP_STOP_LOSS_BPS=60"
set "HYPERSMART_SLTP_TRAILING_BPS=45"
set "HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS=65"
set "HYPERSMART_SLTP_BREAKEVEN_BUFFER_BPS=10"
set "HYPERSMART_SLTP_STOP_MIN_HOLD_MS=45000"
REM CORRECTIF AUDIT 2026-11-06 : catastrophic stop aligne sur le SLTP reel (110 bps = TP).
REM Les commentaires perimés mentionnaient 150/180 bps — la valeur active est 110 bps.
set "HYPERSMART_SLTP_CATASTROPHIC_STOP_BPS=110"
set "HYPERSMART_SLTP_POSITION_TIMEOUT_MS=1800000"
REM CORRECTIF AUDIT 2026-11-06 : 100% = aucun cap effectif.
REM 60% plafonne le biais directionnel net (evite d'etre 100% long ou short).
set "HYPERSMART_MAX_NET_DIRECTIONAL_PCT=60"
set "HYPERSMART_MAX_COIN_NOTIONAL_PCT=60"
set "HYPERSMART_ADAPTIVE_PAPER_SIZING=1"
REM LIQUIDITE (analyse 2026-06-21: 199/256 refus = LIQUIDITY_TOO_LOW alors que signaux FRAIS
REM 5s + edge POSITIF 21 bps). Pour des positions de ~40 USDT, la recherche (mlmodelpoly: MIN_DEPTH=200
REM USDC) montre qu'une liquidite moyenne suffit. On relache 0.30 -> 0.22 pour debloquer ces bonnes
REM entrees fraiches sur alts copiables, tout en rejetant les marches VRAIMENT morts (<0.22).
REM (MIN_LIQUIDITY_SCORE et MAX_COPY_DEGRADATION_BPS definis plus haut, lignes ~170-171)
REM CALIBRATION 2026-06-21 (analyse de 9154 decisions reelles: 100%% NO_TRADE, 0 ouverture).
REM   Cause racine: le cap dur de degradation (22) etait REDONDANT avec le gate d'edge net
REM   (edge_remaining soustrait DEJA toute la degradation). Resultat: 100%% des refus portaient
REM   COPY_DEGRADATION_TOO_HIGH, meme ~250 signaux a edge net positif (BTC/HYPE/ZEC/SOL, consensus).
REM   Fix HONNETE: on passe le cap a 40 (simple garde-fou anti-signal-casse) et on laisse le gate
REM   d'edge net (>=10 bps APRES tous les couts) decider. On n'accepte JAMAIS un edge net negatif.
REM Deviation de prix: 8 bps etait inatteignable a ~11s de latence (bruit normal). 18 rejette
REM toujours les vraies courses-poursuites (prix deja parti) sans tuer les entrees fraiches.
set "HYPERSMART_SIMULATION_MAX_PRICE_DEVIATION_BPS=18"
REM --- TAILLE & DIVERSIFICATION (pour exploiter les 350 USDT sur les meilleurs coins) ---
REM DIAGNOSTIC 2026-06-21: le scan trouve deja 82 coins distincts en candidats, MAIS 100%% des
REM entrees non-ETH etaient refusees pour MAX_OPEN_PAPER_TRADES_REACHED (8 slots satures par ETH).
REM Le goulot n'etait PAS le scan mais le NOMBRE DE POSITIONS. On passe a 20 slots + positions
REM plus petites (60 USDT) pour tenir 15-16 coins EN PARALLELE et capter les bonnes opportunites
REM des autres coins au lieu de re-trader ETH en boucle. Diversification = moins de risque correle.
REM 60 slots = diversification maximale sur les 82+ coins candidats. Positions auto-dimensionnees
REM par l'exposition: l'edge net + le ranker de puissance (signals/opportunity_ranker, plafond
REM par coin) garantissent qu'on remplit les slots avec les MEILLEURES opportunites, pas du bruit ETH.
REM CORRECTIF 2026-06-24: 60 slots = sur-trading (721 trades, churn, saignee de couts). La session
REM gagnante 21/06 tenait MAX 6 positions. On revient a 12 (diversification raisonnable SANS churn):
REM moins de positions, mieux choisies, tenues jusqu'a la sortie du leader. Exposition max 600 USDT.
REM TAILLE & LEVIER (2026-06-25, remarque utilisateur: "des centimes c'est incoherent avec la mise"):
REM   sur Hyperliquid on trade des PERPETUELS avec LEVIER. La "mise" = MARGE bloquee ; la position
REM   controle marge*levier de notionnel ; le PnL = variation_prix * notionnel_leverage (donc un
REM   mouvement de 1% sur 100$ de marge a 5x = ~5$, plus des centimes). On passe la marge par
REM   position a 50$ (2 positions = 100$ de marge deployable) et un levier de 5x (realiste/modere).
REM   L'exposition/cash restent comptes en MARGE -> les 100$ sont toujours proteges. Aucun faux PnL:
REM   tout est calcule au VRAI prix marche, juste dimensionne comme un vrai compte perp.
REM ENG-017 : MAX_POSITION_USDT = MARGE par position (pas notional). Notional = marge * levier (5x).
REM Donc 50 USDT marge = 250 USDT notional. 2 positions = 100 USDT marge = 500 USDT notional max.
set "HYPERSMART_MAX_POSITION_USDT=50"
REM ===== MODE GRINDER (session P1 2026-07-07, flags ON pour collecte de donnees A/B) =====
set "HYPERSMART_EXECUTION_STYLE=maker"
set "HYPERSMART_MAKER_ADVERSE_SELECTION_BPS=2"
set "HYPERSMART_FUNDING_ARB_PAPER=0"
REM 2026-07-08: poller funding ACTIVE — sans lui, funding_rows restait vide et le funding-arb
REM ne pouvait jamais ouvrir de paire (cause racine du "grinder qui ne trade pas").
set "HYPERSMART_V26_FUNDING_POLLER=1"
set "HYPERSMART_V26_FUNDING_POLL_INTERVAL_S=120"
set "HYPERSMART_FUNDING_ARB_MAX_PAIRS=5"
set "HYPERSMART_FUNDING_ARB_LEG_NOTIONAL_USDT=25"
REM CORRECTIF AUDIT 2026-11-06 : aligne sur MAX_OPEN_POSITIONS=2 (3 entrees > 2 slots = incoherent).
set "HYPERSMART_DISTILLED_MAX_PAPER_ENTRIES=2"
set "HYPERSMART_WHALE_CONSENSUS_SIZING=1"
REM ============================================================
REM PLANCHER NOTIONAL (replay A/B 2026-07-07 sur logs frais): les micro-trades ont un net
REM negatif (frais ~59%% du brut). Filtre causal notional>=40: train ET validation positifs
REM (+0.11 vs -1.77 tous trades). Echantillon encore petit (13 trades) - a re-verifier.
set "HYPERSMART_MIN_PAPER_NOTIONAL_USDT=40"
set "HYPERSMART_MAX_TOTAL_EXPOSURE_USDT=100"
REM CORRECTIF AUDIT 2026-11-06 : 20 positions x 40$ min = 800$ >> 100$ d'exposition max.
REM Seules 2 positions de 50$ tiennent dans 100$ d'expo. On aligne a 2 (realiste).
REM Pour augmenter les slots : relever MAX_TOTAL_EXPOSURE_USDT proportionnellement.
set "HYPERSMART_MAX_OPEN_POSITIONS=2"
REM LEVIER de simulation: 5x = realisme perp Hyperliquid (demande Flo 2026-07-08: "pas que des
REM centimes, comme le marche reel"). notional = marge x levier -> $40 de marge = $200 d'expo.
REM PnL = notional x variation. HONNETE: le stop catastrophe (180 bps) plafonne la perte a ~9%%
REM Levier aligne sur 3x partout (backtest + runtime) conformement a la roadmap v10.
REM 1x insuffisant pour couvrir les frais, 10x trop risque pour 350$. 3x = equilibre.
set "HYPERSMART_SIMULATION_LEVERAGE=3"
REM LAISSER COURIR (demande Flo): on coupe le quality-guard qui fermait les positions a ~0.15%%
REM (elles n'atteignaient jamais leur SL/TP 1.2-1.6%%). Desormais SL/TP + sortie du leader gouvernent
REM -> on capture le VRAI mouvement du marche, pas du bruit. Reversible (=1 pour re-activer).
set "HYPERSMART_LEGACY_POSITION_QUALITY_GUARD_ENABLED=0"
REM RESET PROPRE A CHAQUE LANCEMENT (demande utilisateur): equity remise a 100, compteurs
REM trades gagnants/perdants et taux de reussite remis a 0, logs de session repartis a neuf
REM (les anciens sont archives dans _archives). Mettre 0 pour au contraire CONSERVER l'equity.
REM RESET DES LOGS 2026-06-25: en plus, le dossier logs\ encombre est REMIS A ZERO a chaque
REM lancement (prepare-simulation-logs --purge-top-level): les gros *.log sont vides (tronques a 0),
REM les archives lourdes *.zip supprimees, l'ancien dossier mojibake retire. L'INTELLIGENCE DE
REM L'IA n'est JAMAIS touchee (modele + echantillons d'apprentissage vivent dans runtime\, hors logs\).
REM 25/07 (Fix 1) : DEFAUT = CONSERVER equity/PnL/ledgers/positions/historique entre lancements.
REM AUTOPILOT et `restart` ne remettent PLUS a zero. Le reset ne se fait QUE via
REM `LANCER_HYPERSMART.cmd reset-paper --confirm` (sauvegarde horodatee AVANT toute remise a zero).
set "HYPERSMART_RESET_ON_LAUNCH=0"
REM Les anciens modules d'analyse multi-plateforme restent sur disque, non lances.
REM Les auxiliaires HyperSmart utiles (IA shadow + stream read-only) sont demarres par le script
REM principal, rattaches a la meme session, et stoppes avec Q.

REM L'entrainement IA n'est pas necessaire au runtime de collecte/decision. Il reste
REM disponible comme outil d'analyse explicite, sans consommer de ressources au demarrage.
set "HYPERSMART_ENABLE_AUX_IA=0"

REM MOTEUR TEMPS REEL (V16, 2026-06-26): flux WebSocket Hyperliquid PERSISTANT sur les 10 MEILLEURS
REM leaders (cap HL = 10 wallets). Stocke chaque fill FRAIS a la seconde ou il arrive (sub-seconde)
REM au lieu du snapshot REST laggé (~10s) -> entrees vraiment fraiches. Lecture seule, 0 ordre.
REM Fenetre minimisee "HyperSmart Stream" - ferme-la pour stopper le flux temps reel.
REM Stream rattache au lanceur principal; pas de fenetre separee.
set "HYPERSMART_ENABLE_AUX_STREAM=1"

REM Contrat LCH : scope economique unique, autorite dans active_scope.py.
set "HYPERSMART_ACTIVE_STRATEGY_SCOPE=copy_vault"
set "HYPERSMART_SCOPE_VERSION=COPY_VAULT_PAPER_V2"

REM === DIRECT COPY-VAULT RUNTIME (11/2026) : chemin fusion_persistent_adapter ===
REM Ces variables alimentent le decider DIRECT COPY dans fusion_persistent_adapter.py.
REM Sans elles, les defauts du code (MIN_EDGE=32, MAX_POSITIONS=3, CONSENSUS=3) sont
REM INCOHERENTS avec les reglages SIMULATION/FUSION ci-dessus. On les aligne ici.
REM
REM ENG-012 TABLE D'EDGE CONSOLIDEE (tous les seuils d'edge du systeme) :
REM   SIMULATION_MIN_EDGE_BPS      = 16  (entree fusion)
REM   DIRECT_COPY_MIN_EDGE_BPS     = 16  (entree direct copy)
REM   FUSION_COST_BUFFER_BPS       = 24  (marge de cout fusion — voir config Python)
REM   SINGLE_WALLET_MIN_EDGE_BPS   = 9999 (mono-wallet FERME, sentinelle)
REM   SINGLE_WALLET_EDGE_BONUS_BPS = 45  (bonus heuristique si consensus=1, inaccessible)
REM   RECOVERY_EDGE_BONUS_BPS      = 24  (bonus pour recovery apres halt)
REM   Cout round-trip taker/taker   = 9 bps (4.5 bps x2)
REM   → Toute entree exige edge_net > 16 bps > 9 bps cout → positif PAR CONSTRUCTION.
set "HYPERSMART_DIRECT_COPY_MAX_OPEN_POSITIONS=2"
set "HYPERSMART_DIRECT_COPY_MIN_CONSENSUS_WALLETS=2"
set "HYPERSMART_DIRECT_COPY_MIN_EDGE_BPS=16"
set "HYPERSMART_DIRECT_COPY_SINGLE_WALLET_EDGE_BONUS_BPS=45"
set "HYPERSMART_DIRECT_COPY_MAX_SIGNAL_AGE_MS=10000"
set "HYPERSMART_DIRECT_COPY_MIN_LIQUIDITY=0.55"
set "HYPERSMART_DIRECT_COPY_MAX_DEGRADATION_BPS=24"
set "HYPERSMART_DIRECT_COPY_RECOVERY_EDGE_BONUS_BPS=24"
set "HYPERSMART_DIRECT_COPY_RECOVERY_MIN_CONSENSUS=4"
set "HYPERSMART_DIRECT_COPY_RECOVERY_MIN_LIQUIDITY=0.60"

REM === V26 PROTECTIONS PAPER (11/2026) : filets de securite SIMULATION ===
REM Entry vetos (funding spike + drawdown) : thread de veto active. Sans ce flag,
REM le thread n'est JAMAIS lance (fusion_heartbeat_input.py). Paper-only, 0 ordre.
set "HYPERSMART_V26_ENTRY_VETOS_AUTHORITATIVE=1"
REM Sub-flags des vetos (actifs seulement si le flag maitre ci-dessus est a 1).
set "HYPERSMART_V26_FUNDING_VETO=1"
set "HYPERSMART_V26_EDGE_TREND_VETO=1"
REM Halt gradue (passivbot) : vert/ambre/rouge.
set "HYPERSMART_V26_GRADED_HALT=1"
REM Qualite marche / univers top-K forager (passivbot).
set "HYPERSMART_V26_MARKET_QUALITY=1"
REM Budget de couts par tier leader.
set "HYPERSMART_V26_TIER_COST_BUDGET=1"
REM StoplossGuard + LowProfitMarket + WindowedDrawdown (protections_v26.py).
set "HYPERSMART_V26_PROTECTIONS=1"
REM ENG-022 AUDIT — TABLE DES SEUILS DE HALT CONSOLIDEE (pour 350 USDT paper) :
REM   Halt gradue (fenetre 60 min) :  amber = -12 USD (3.4%%) | red = -25 USD (7.1%%)
REM   Drawdown glissant (fenetre 120 min) : max -18 USD (5.1%%), halt 45 min
REM   → amber < DD < red : coherent — le DD attrape les pertes lentes (120 min), le halt
REM     gradue attrape les pertes rapides (60 min). Pas de trou dans la couverture.
REM   Cooldown apres red : 30 min avant de re-ouvrir.
set "HYPERSMART_V26_HALT_AMBER_LOSS_USD=12"
set "HYPERSMART_V26_HALT_RED_LOSS_USD=25"
set "HYPERSMART_V26_HALT_WINDOW_MIN=60"
set "HYPERSMART_V26_HALT_COOLDOWN_MIN=30"
set "HYPERSMART_V26_DD_WINDOW_MIN=120"
set "HYPERSMART_V26_DD_MAX_LOSS_USD=18"
set "HYPERSMART_V26_DD_HALT_MIN=45"
REM Kelly sizing leader (optionnel, active pour dimensionner selon l'edge mesure).
set "HYPERSMART_V26_KELLY_LEADER=0"
set "HYPERSMART_V26_KELLY_FRACTION=0.25"
set "HYPERSMART_V26_KELLY_MIN_TRADES=20"
set "HYPERSMART_V26_KELLY_MIN_EDGE=5"
set "HYPERSMART_V26_KELLY_MAX_MULT=2.0"
set "HYPERSMART_V26_KELLY_MIN_MULT=0.3"
set "HYPERSMART_V26_KELLY_LOOKBACK=200"
REM === RISK GATE UNIFIE (AUDIT 2026-11-06) : halts perte + drawdown kill + VaR + loss-streak ===
REM Le gate etait code et cable (risk_gate_runtime.py -> mirror_paper_executor.py) mais JAMAIS active.
REM Seuils adaptes au capital 350 USDT paper : perte jour 5%, perte mois 15%, drawdown 20%, streak 5.
set "HYPERSMART_RISK_GATE_ENABLED=1"
set "HYPERSMART_RISK_MAX_DAILY_LOSS_PCT=5.0"
set "HYPERSMART_RISK_MAX_MONTHLY_LOSS_PCT=15.0"
set "HYPERSMART_RISK_MAX_DRAWDOWN_PCT=20.0"
set "HYPERSMART_RISK_MAX_LOSS_STREAK=5"
REM === KELLY SIZING (AUDIT 2026-11-06) : dimensionnement adaptatif par Kelly criterion ===
REM Half-Kelly (fraction 0.5) — dimensionne les positions proportionnellement a l'edge mesure.
REM Cap conservateur : si Kelly donne une taille < proportionnel, on prend Kelly.
set "HYPERSMART_KELLY_SIZING_ENABLED=1"
REM === EXIT ENGINE ATR (AUDIT 2026-11-06) : trailing stop, TP partiel, time-stop, momentum giveback ===
REM Sorties intelligentes basees sur l'ATR mesure. Complemente le SLTP bps classique.
set "HYPERSMART_EXIT_ENGINE_ENABLED=1"
REM === FAIR VALUE VETO (AUDIT 2026-11-06) : empecher l'entree adverse vs fair value EMA ===
set "HYPERSMART_V26_FAIR_VALUE_VETO=1"
REM === ENTRY GATE V2 (AUDIT 2026-11-06) : gate d'entree multi-critere (edge, liquidite, consensus) ===
REM Code et cable dans entry_gate_runtime.py -> mirror_paper_executor.py mais jamais active.
set "HYPERSMART_ENTRY_GATE_ENABLED=1"
REM === AUTO-UNSTUCK (AUDIT 2026-11-06) : decoince les positions paper perdantes (passivbot L3) ===
set "HYPERSMART_V26_AUTO_UNSTUCK=1"
REM === PROTECTIONS V26 (AUDIT 2026-11-06) : StoplossGuard, LowProfitMarket, WindowedDrawdown ===
set "HYPERSMART_V26_PROTECTIONS=1"
REM === BOOK POLLER (AUDIT 2026-11-06) : poller L2 books en continu pour couts en temps reel ===
set "HYPERSMART_V26_BOOK_POLLER=1"
set "HYPERSMART_V26_LIVE_BOOK_COSTS=1"
REM === MICROSTRUCTURE GUARD (AUDIT 2026-11-06) : spread, depth, OBI avant entree ===
set "HYPERSMART_RUNTIME_MICROSTRUCTURE_GUARD=1"
REM === DEPTH FILL GUARD (AUDIT 2026-11-06) : verification que la profondeur L2 permet le fill ===
set "HYPERSMART_RUNTIME_DEPTH_FILL_GUARD=1"
REM === REQUIRE EMPIRICAL EDGE (AUDIT 2026-11-06) : n'entre que si edge mesure > 0 ===
set "HYPERSMART_REQUIRE_EMPIRICAL_EDGE=1"
REM === WALLET QUALITY SCORING (AUDIT 2026-11-06) : scoring continu des wallets leaders ===
set "HYPERSMART_WALLET_QUALITY_SCORING=1"
REM === EVENT DRIVEN AUTHORITATIVE (AUDIT 2026-11-06) : pipeline event-driven (pas poll) ===
set "HYPERSMART_EVENT_DRIVEN_AUTHORITATIVE=1"
REM === SESSION LOSS GUARD (AUDIT 2026-11-06) : halt si perte session > seuil ===
set "HYPERSMART_SESSION_LOSS_GUARD_USDC=15"
set "HYPERSMART_SESSION_GUARD_HARD_LOSS_USDC=25"
REM === NOYAU AUTORITAIRE (AUDIT 2026-11-06) : verification stricte du noyau de decision ===
set "HYPERSMART_NOYAU_AUTORITAIRE=1"

REM ENG-040→048 AUDIT GATES (2026-11-06) — tous les gates/modules declares dans interrupteurs.py :
REM   ALLUME : V26_PROTECTIONS, V26_GRADED_HALT, V26_MARKET_QUALITY, V26_ENTRY_VETOS_AUTHORITATIVE,
REM            NOYAU_AUTORITAIRE (5 gardes-fous, ne font que REFUSER, asymetrie ecrasante).
REM   ETEINT VOLONTAIREMENT : V26_KELLY_LEADER (change la TAILLE, edge non mesure → amplifierait les pertes).
REM   Modules ACTIFS supplementaires : BOOK_POLLER, LIVE_BOOK_COSTS, MICROSTRUCTURE_GUARD,
REM            DEPTH_FILL_GUARD, REQUIRE_EMPIRICAL_EDGE, WALLET_QUALITY_SCORING,
REM            EVENT_DRIVEN_AUTHORITATIVE, SESSION_LOSS_GUARD, AUTO_UNSTUCK.
REM === PREFLIGHT BLOQUANT (item 6) — env/deps/disque/dossiers/horloge/endpoints/quotas/schemas/paper.
REM   NO-GO => le moteur NE demarre PAS. Paper strict, lecture publique HL info uniquement, 0 ordre.
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" STEP autopilot "blocking-preflight" ""
"%HYPERSMART_PYTHON%" "%~dp0tools\cmd_progress.py" phase "Preflight bloquant" 4 7
"%HYPERSMART_PYTHON%" -m hl_observer.ops.preflight_lanceur "%~dp0."
set "BLOCKING_PREFLIGHT_RC=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" RESULT autopilot "blocking-preflight" "%BLOCKING_PREFLIGHT_RC%"
if not "%BLOCKING_PREFLIGHT_RC%"=="0" (
  echo.
  echo   [PREFLIGHT] NO-GO : environnement non pret. Le moteur ne demarre pas. Corrige les blocages ci-dessus.
  echo.
  REM LCH-011/LCH-012 : le verrou a deja ete acquis avant ce controle.
  REM Toujours passer par la sortie commune afin de liberer le verrou, meme sur NO-GO.
  set "RC=2"
  call :liberer_verrou_lanceur
  goto :fin
)

REM ARCHIVE REPLAY (2026-07-09, demande Flo): au lieu de perdre les donnees du run precedent,
REM on les DEPLACE dans runtime\replay\_archive\run_<ts>\ (serveur eteint, avant tout writer).
REM => le dataset replay s'accumule entre rallumages ; runtime\replay\ reste propre pour le run.
REM Le replay (merge_replay/include_archive) lit TOUT l'historique. Best-effort, jamais destructif.
if not exist "%~dp0runtime\logs" mkdir "%~dp0runtime\logs" >nul 2>&1
"%HYPERSMART_PYTHON%" -m hl_observer.runtime.replay_recorder --archive-run --base "%~dp0runtime\replay" 1>>"%~dp0runtime\logs\archive_replay.log" 2>&1
set "ARCHIVE_REPLAY_RC=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" RESULT autopilot "archive-previous-replay; details=runtime/logs/archive_replay.log" "%ARCHIVE_REPLAY_RC%"
if not "%ARCHIVE_REPLAY_RC%"=="0" echo   [ATTENTION] Archivage replay: erreur signalee (non masquee) -- voir runtime\logs\archive_replay.log

REM -MaxLeaders eleve = scan TRES large (pool de leaders) ; le gate de qualite (smart money) garde la copie etroite.
REM === CARRY HISTORIQUE : DESACTIVE / SHADOW (decision Flo 2026-07-23) ===
REM Ce carry delta-neutre HL-only affichait -8,24 $ : 100%% du funding au PLANCHER (0,125 bph) -> ~2-3%%
REM APR net, DOMINE par HLP (15-30%%). Le cross-venue mid-cap (DOT/NEO/RUNE, net OOS positif battant
REM HLP) le remplace comme piste carry. On coupe donc l'OUVERTURE (budget 0, AUCUNE entree). Les 6
REM positions ouvertes sont fermees proprement aux prix executables (couts complets) par
REM tools\fermer_carry_historique.py APRES la relance ; l'historique reste au ledger. SHADOW : le
REM module peut encore EVALUER/journaliser mais n'OUVRE plus rien. Remettre a 1 = re-litiger une piste refutee.
set "HYPERSMART_CARRY_HYPE_PAPER=0"
set "HYPERSMART_CARRY_ETAPE2=0"
set "HYPERSMART_CARRY_DISABLED=1"
REM === CARRY : alimentation AUTO des inputs spot (best coin, toutes les 10 min, en arriere-plan) ===
REM Sans ca, carry_spot_inputs.json n'est jamais ecrit -> le carry refuse tout (INPUTS_SPOT_ABSENTS).
REM 19/07 — SANS FENETRE. Ces 3 collecteurs ouvraient 3 fenetres cmd a chaque demarrage :
REM insupportable a l'usage, et c'est moi qui les avais ajoutees. Ils tournent desormais CACHES.
REM ⚠️ Mais un processus cache qui echoue en SILENCE serait exactement la maladie qu'on vient de
REM corriger (les 105 `except: pass`). Chacun ecrit donc son journal dans runtime\logs\ :
REM   runtime\logs\carry-feeder.log · marks-collector.log · liq-collector.log
REM En cas de doute : ouvre le .log, ou double-clique le .cmd correspondant pour le voir tourner.
if not exist "%~dp0runtime\logs" mkdir "%~dp0runtime\logs" >nul 2>&1
REM ⚠️ `start "" /b` et PAS PowerShell/Start-Process. J'avais d'abord ecrit une ligne PowerShell
REM avec trois niveaux de guillemets imbriques sur un chemin qui contient une ESPACE
REM ("Projet invest") -- du code qui casse en silence, et un collecteur qui ne demarre jamais
REM sans le dire, c'est exactement la maladie qu'on passe la journee a corriger.
REM `/b` = pas de nouvelle fenetre (doc Windows), UN seul niveau de guillemets, et toute la
REM sortie part deja dans le log depuis boucle_collecteur.cmd.
REM ⚠️ CHEMINS RELATIFS, ZERO GUILLEMET. Ma version precedente passait des chemins ABSOLUS
REM entre guillemets ; le dossier s'appelle « Projet invest » (avec une ESPACE), et `start /b`
REM lance un .cmd via `cmd /c` qui, des qu'il voit PLUSIEURS paires de guillemets, retire la
REM premiere et la derniere. Resultat mesure chez Flo :
REM     'C:\Users\flo\Desktop\Projet' n'est pas reconnu... (x3, un par collecteur)
REM Le lanceur a deja fait `cd /d "%~dp0"` (ligne 3) : on est DANS le dossier projet. Des chemins
REM relatifs n'ont donc ni espace ni guillemet -- le bug ne peut plus se produire.
REM 21/07 ANTI-ORPHELIN : marqueur UNIQUE de session, ecrit AVANT les boucles. Les boucles
REM d'une session precedente voient le marqueur changer et s'arretent d'elles-memes ->
REM plus jamais deux carry-feeders en parallele apres un Q, une croix ou un crash.
if not exist "runtime\data" mkdir "runtime\data" >nul 2>&1
echo %random%-%random%-%date%-%time% > "runtime\data\lanceur_session_marqueur.txt"
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" STEP autopilot "collector-startup" ""
"%HYPERSMART_PYTHON%" "%~dp0tools\cmd_progress.py" phase "Demarrage collecteurs" 5 7
call :demarrer_collecteurs
set "COLLECTOR_START_RC=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" RESULT autopilot "collector-startup-first-pass" "%COLLECTOR_START_RC%"
REM === Item 8 : une source OBLIGATOIRE (CORE) non demarree BLOQUE le moteur (superviseur -> exit 3).
if not "%COLLECTOR_START_RC%"=="0" (
  echo.
  echo   [COLLECTEURS] Une source obligatoire n'a pas demarre. Le moteur ne demarre pas. Voir ci-dessus.
  echo.
  call :stop_impl
  set "RC=3"
  goto :fin
)
REM Le superviseur enregistre directement les PID et reutilise les instances deja
REM vivantes. Aucun second passage de detection, aucun demarrage en double.
timeout /t 2 /nobreak >nul 2>&1
REM Une ancienne boucle peut sortir juste apres le changement du marqueur de session.
REM Ce second passage idempotent ne duplique rien et recree seulement les collecteurs disparus.
call :demarrer_collecteurs
set "COLLECTOR_RECONCILE_RC=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" RESULT autopilot "collector-startup-reconciliation" "%COLLECTOR_RECONCILE_RC%"
if not "%COLLECTOR_RECONCILE_RC%"=="0" (
  echo   [COLLECTEURS] Echec de reconciliation apres changement de session.
  call :stop_impl
  set "RC=3"
  goto :fin
)
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs status harvest
echo   [collecteurs HARVEST] allMids + BBO(HL+Binance) + userFills + Native(Bybit+OKX+Gate+Bitget) + carnet L2 + marks + liq + venues + vaults + backfills.
REM === ITEM 1 : BARRIERE READY_CORE **BLOQUANTE** =============================================
REM Apres le demarrage des collecteurs, on attend (fenetre BORNEE de warmup) que le socle CORE
REM (allMids + BBO + userFills) PROUVE reellement sa vie. Tant que READY_CORE != true, le moteur,
REM l'UI et le poller NE demarrent PAS. On verifie ERRORLEVEL immediatement ; sortie non-zero
REM DATA_NOT_READY avec la SOURCE et la RAISON exactes affichees ci-dessus. Paper strict.
REM ENG-038 : fenetre de warmup surchargable (defaut 90s). Augmenter pour un 1er demarrage a froid :
REM   set HYPERSMART_WARMUP_CORE_SEC=180 pour un demarrage a froid sur une machine lente.
set "HYPERSMART_WARMUP_CORE_SEC=%HYPERSMART_WARMUP_CORE_SEC%"
if "%HYPERSMART_WARMUP_CORE_SEC%"=="" set "HYPERSMART_WARMUP_CORE_SEC=90"
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" STEP autopilot "ready-core-warmup" ""
"%HYPERSMART_PYTHON%" "%~dp0tools\cmd_progress.py" phase "READY_CORE warmup" 6 7
echo   [READY_CORE] Attente bornee (%HYPERSMART_WARMUP_CORE_SEC% s) de la preuve de vie du socle CORE...
"%HYPERSMART_PYTHON%" -m hl_observer.ops.preuve_de_vie "%~dp0." --niveau core --attendre %HYPERSMART_WARMUP_CORE_SEC% --intervalle 3
set "READY_CORE_RC=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" RESULT autopilot "ready-core-warmup" "%READY_CORE_RC%"
if not "%READY_CORE_RC%"=="0" (
  echo.
  echo   [READY_CORE] DATA_NOT_READY : allMids/BBO/userFills n'ont PAS prouve leur vie dans la fenetre.
  echo   Le moteur, l'UI et le poller NE demarrent PAS ^(paper strict, aucune donnee fabriquee^).
  echo   Source et raison exactes affichees ci-dessus. Corrige puis relance.
  echo.
  call :stop_impl
  set "RC=4"
  goto :fin
)
echo   [READY_CORE] OK : allMids + BBO + userFills prouves vivants. Demarrage moteur/UI/poller autorise.
REM Item 4 : niveau HARVEST detaille (COMPLET / DEGRADE_DOCUMENTE) — INFORMATIF, va au catalogue de session.
"%HYPERSMART_PYTHON%" -m hl_observer.ops.preuve_de_vie "%~dp0." --niveau harvest
set "HARVEST_HEALTH_RC=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" RESULT autopilot "harvest-health-informational" "%HARVEST_HEALTH_RC%"

REM === ITEM 7 (cablage) : ouverture de la SESSION canonique + declaration de TOUTES les sources ========
REM   Ecrit runtime\data\sessions\<run_id>\DATA_CATALOG.json (ACTIVE) + le pointeur COURANTE.json que le
REM   moniteur et ANALYSER retrouvent. Chaque source est DECLAREE (vivante avec compteurs reels, ou absente
REM   avec sa raison). Aucune donnee fabriquee.
"%HYPERSMART_PYTHON%" -m hl_observer.ops.session_harvest ouvrir "%~dp0."
set "RC_SESSION=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" RESULT autopilot "open-canonical-harvest-session" "%RC_SESSION%"
if not "%RC_SESSION%"=="0" (
  echo.
  echo   [SESSION] Echec bloquant de creation du catalogue de session. Le moteur ne demarre pas.
  echo   Aucun run incomplet ne sera promu ; consulte les logs et corrige les droits/artefacts.
  echo.
  call :stop_impl
  set "RC=5"
  goto :fin
)

REM ENG-049→055 OBSERVABILITE :
REM   ENG-049 moniteur_sante (ci-dessous), ENG-050 crash_notification (ops.crash_notification),
REM   ENG-051 log_rotation (ops.log_rotation), ENG-052 health_monitor (ops.health_monitor),
REM   ENG-053 data_purge (ops.data_purge), ENG-054 config_dump (ops.config_dump, branche en prevol),
REM   ENG-055 network_health (ops.network_health, branche en prevol ENG-032).
REM === ITEM 9 : MONITEUR de sante INTEGRE AU LANCEMENT (plus besoin de "LANCER_HYPERSMART.cmd sante"). ==
REM   Boucle CACHEE (start /b) : rafraichit le tableau + APPEND runtime\logs\sante_journal.log en continu
REM   (READY_CORE/HARVEST, source, PID, heartbeat, events/s, fichier qui grossit, gaps/reconnects/stale,
REM   carnet sync, statut/raison). Process separe : une panne du moniteur n'affecte pas le moteur. 0 ordre.
if not exist "%~dp0runtime\logs" mkdir "%~dp0runtime\logs" >nul 2>&1
REM item 9 : UN SEUL writer pour sante_journal.log = le module moniteur_sante (journal synthetique).
REM La sortie CONSOLE redirigee va dans un fichier SEPARE (sante_console.log) -> plus d'ecritures
REM concurrentes ni de doublons sur le journal.
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" STEP autopilot "health-monitor-launch; details=runtime/logs/sante_console.log" ""
start "" /b "%HYPERSMART_PYTHON%" -m hl_observer.ops.moniteur_sante "%~dp0." --intervalle 3 1>>"%~dp0runtime\logs\sante_console.log" 2>&1
set "HEALTH_MONITOR_START_RC=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" RESULT autopilot "health-monitor-launch-request; details=runtime/logs/sante_console.log" "%HEALTH_MONITOR_START_RC%"

call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" STEP autopilot "interactive-simulation-engine" ""
"%HYPERSMART_PYTHON%" "%~dp0tools\cmd_progress.py" phase "Moteur simulation" 7 7
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start_hypersmart_simulation.ps1" -Port %HYPERSMART_PORT% -IntervalSeconds 15 -MaxLeaders 50 -Interactive

REM item 4 : a la SORTIE du moteur interactif (Q / croix / fin), on arrete REELLEMENT les writers puis on
REM CLOTURE la session (COMPLETE si tout verifie + zero orphelin + preuve d'arret ; sinon QUARANTINED).
set "RC_MOTEUR=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" RESULT autopilot "interactive-simulation-engine" "%RC_MOTEUR%"
echo   [ARRET] Sortie du moteur : arret des collecteurs + cloture de session...
call :stop_impl
set "RC_STOP=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" RESULT autopilot "stop-and-session-close" "%RC_STOP%"
REM item 9 : propage le PREMIER code non nul (moteur PowerShell puis arret/cloture).
if not "%RC_MOTEUR%"=="0" ( set "RC=%RC_MOTEUR%" ) else ( if not "%RC_STOP%"=="0" set "RC=%RC_STOP%" )
goto :fin

:fin
REM item 9 : code de sortie reel (0 seulement si tout a reussi), jamais un exit /b 0 systematique.
REM [2026-08-05] JAMAIS de fermeture invisible. Un prevol NO_GO sortait en 7 sans pause : la
REM fenetre disparaissait avant d'etre lue, et la panne devenait indiagnosticable a l'oeil nu.
if /I "%HYPERSMART_NO_PAUSE%"=="1" goto :fin_exit
if "%HYPERSMART_INTERACTIVE_LAUNCH%"=="1" goto :fin_pause
if not "%RC%"=="0" goto :fin_pause
goto :fin_exit

:fin_pause
echo.
"%HYPERSMART_PYTHON%" "%~dp0tools\cmd_progress.py" elapsed
echo   ============================================================
if "%RC%"=="0" (
  echo     HyperSmart est arrete proprement. Cette fenetre reste ouverte.
) else (
  echo     ARRET sur le code %RC% - la raison exacte est AU-DESSUS.
  echo     Diagnostic complet : DIAGNOSTIC_LANCEUR.cmd
)
echo     ^(HYPERSMART_NO_PAUSE=1 pour supprimer cette pause en automatise^)
echo   ============================================================
echo.
pause

:fin_exit
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" EXIT completion "launcher-finished" "%RC%"
endlocal & exit /b %RC%

REM ############################################################################
REM #  SOUS-ROUTINE PARTAGEE : DEMARRAGE DES COLLECTEURS (source unique)
REM #  Reutilisee par l'AUTOPILOT et par la sous-commande `collectors`.
REM #  ENG-057 : le canari s'appuie sur le REGISTRE Python (collecteur_registry.py),
REM #  pas sur le comptage de lignes 'start' du bloc mort L660+.
REM ############################################################################
:demarrer_collecteurs
REM Profil HARVEST officiel (items 1/2) : socle CORE (allMids+BBO+userFills) PLUS la recolte dense
REM multi-venue native (Bybit/OKX/Gate/Bitget) et les autres collecteurs HARVEST. Le superviseur evite les
REM doublons et enregistre lui-meme les PID pour l'arret cible.
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs demarrer-tous harvest
exit /b %ERRORLEVEL%

:liberer_verrou_lanceur
REM Sortie de preflight et arrets anticipes : ne jamais laisser le verrou du lanceur
REM vivre jusqu'a son TTL lorsque le moteur n'a pas demarre.
"%HYPERSMART_PYTHON%" -m hl_observer.ops.verrou_lanceur liberer "%~dp0."
exit /b %ERRORLEVEL%

REM ---------------------------------------------------------------------------
REM REFERENCE LEGACY — CODE MORT (INATTEIGNABLE apres exit /b ci-dessus).
REM AUDIT 2026-11-06 : ces lignes `start` suivaient un `exit /b` et n'ont JAMAIS ete executees.
REM Tous ces collecteurs sont geres par le superviseur via les profils maintenance/research/all.
REM Conserve en commentaire comme documentation des collecteurs disponibles.
REM ---------------------------------------------------------------------------
REM start "" /b tools\boucle_collecteur.cmd marks-collector tools\ecrire_marks_tous_coins.py 60 --une-fois
REM start "" /b tools\boucle_collecteur.cmd allmids-collector tools\collecter_allmids.py 15 --une-fois
REM start "" /b tools\boucle_collecteur.cmd liq-collector tools\collecter_liquidations.py 300 --une-fois
REM start "" /b tools\boucle_collecteur.cmd venues-collector tools\collecter_dispersion_venues.py 60 --une-fois
REM start "" /b tools\boucle_collecteur.cmd carnet-collector tools\collecter_carnet.py 60 --une-fois
REM start "" /b tools\boucle_collecteur.cmd overshoot-collector tools\collecter_overshoots.py 10 --une-fois
REM start "" /b tools\boucle_collecteur.cmd vault-collector tools\collecter_vaults.py 300 --une-fois
REM start "" /b tools\boucle_collecteur.cmd scorer-vaults tools\scorer_vaults.py 600 --une-fois
REM start "" /b tools\boucle_collecteur.cmd backfill-fills tools\backfill_vault_fills.py 14400 --une-fois
REM start "" /b tools\boucle_collecteur.cmd backfill-candles-vaults tools\backfill_candles_vaults.py 14400 --une-fois
REM start "" /b tools\boucle_collecteur.cmd pipeline-reel tools\pipeline_copie_reel.py 1800 --une-fois
REM start "" /b tools\boucle_collecteur.cmd geler-prelim tools\geler_prelim_copie.py 3600 --une-fois
REM start "" /b tools\boucle_collecteur.cmd userfills-live tools\collecter_userfills_vaults.py 5
REM start "" /b tools\boucle_collecteur.cmd bbo-collector tools\collecter_bbo.py 5
REM start "" /b tools\boucle_collecteur.cmd copy-whitelist tools\ecrire_copy_whitelist.py 21600
REM start "" /b tools\boucle_collecteur.cmd rapport-quotidien tools\rapport_quotidien.py 21600
REM start "" /b tools\boucle_collecteur.cmd research-lab tools\lancer_research_parallel.py 60 --max-ticks 1
REM start "" /b tools\boucle_collecteur.cmd lab-microstructure tools\collecter_lab_microstructure.py 30

exit /b 0

REM ############################################################################
REM #  DISPATCHER DES SOUS-COMMANDES
REM ############################################################################
:dispatch
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM === INVARIANTS DE SECURITE (identiques a :autopilot, L144-147) ===
REM ENG-068 : duplication VOLONTAIRE — pas de factorisation en call :label.
REM Raison : chaque chemin d'execution doit poser ses propres gardes paper/read-only
REM sans dependre d'un label partage qui pourrait etre contourne ou mal ordonne.
set "HL_ENV=paper"
set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
set "HYPERSMART_MODE=SIMULATION_ONLY_UNTIL_MANUAL_REVIEW"
set "SUB=%~1"
set "ALINA_LAUNCH_MODE=%SUB%"
call "%~dp0tools\launcher_log.cmd" "LANCER_HYPERSMART" STEP command-dispatch "subcommand-selected" ""
REM ENG-031 : --help / -h affiche le menu d'aide.
if /I "%SUB%"=="--help"            goto :cmd_menu
if /I "%SUB%"=="-h"                goto :cmd_menu
if /I "%SUB%"=="help"              goto :cmd_menu
if /I "%SUB%"=="status"            goto :cmd_status
if /I "%SUB%"=="stop"              goto :cmd_stop
if /I "%SUB%"=="restart"           goto :cmd_restart
if /I "%SUB%"=="restart-userfills" goto :cmd_ruserfills
if /I "%SUB%"=="collectors"        goto :cmd_collectors
if /I "%SUB%"=="collectors-harvest" goto :cmd_collectors_harvest
if /I "%SUB%"=="collectors-maintenance" goto :cmd_collectors_maintenance
if /I "%SUB%"=="collectors-research"    goto :cmd_collectors_research
if /I "%SUB%"=="collectors-all"         goto :cmd_collectors_all
if /I "%SUB%"=="sante"             goto :cmd_sante
if /I "%SUB%"=="report"            goto :cmd_report
if /I "%SUB%"=="test"              goto :cmd_test
if /I "%SUB%"=="audit"             goto :cmd_audit
if /I "%SUB%"=="replay"            goto :cmd_replay
if /I "%SUB%"=="moisson"           goto :cmd_moisson
if /I "%SUB%"=="verify-oos"        goto :cmd_verifoos
if /I "%SUB%"=="github-push"       goto :cmd_github
if /I "%SUB%"=="reset-paper"       goto :cmd_resetpaper
if /I "%SUB%"=="self-test"         goto :cmd_selftest
if /I "%SUB%"=="menu"              goto :cmd_menu
if /I "%SUB%"=="audit-moissonneur" goto :cmd_auditmoiss
if /I "%SUB%"=="premier-raw"       goto :cmd_premierraw
if /I "%SUB%"=="kill-userfills"    goto :cmd_killuserfills
if /I "%SUB%"=="verif-l2"          goto :cmd_verifl2
if /I "%SUB%"=="sonde"             goto :cmd_sonde
if /I "%SUB%"=="notif-test"        goto :cmd_notiftest
if /I "%SUB%"=="portable-check"    goto :cmd_portablecheck
if /I "%SUB%"=="portable-install"  goto :cmd_portableinstall
if /I "%SUB%"=="portable-build"    goto :cmd_portablebuild
if /I "%SUB%"=="portable-zip"      goto :cmd_portablezip
if /I "%SUB%"=="portable-proof"    goto :cmd_portableproof
echo.
echo   Sous-commande inconnue : "%SUB%"
set "RC=64"
goto :fin

:cmd_menu
echo.
echo   =================  LANCER_HYPERSMART.cmd  =================
echo   Double-clic sans argument = RUNTIME CORE ^(moteur + dashboard + flux essentiels^).
echo.
echo   Controle :
echo     status              etat des processus du lanceur ^(lecture seule^)
echo     stop                arret cible ^(collecteurs + userfills^), jamais un kill global
echo     restart             stop puis autopilot
echo     restart-userfills   recharge le collecteur userfills avec le code courant
echo     collectors          demarre/reanime allMids + BBO + userFills ^(CORE^)
echo     collectors-harvest  collecte HARVEST; checkpoints causaux via LANCER_COLLECTEURS_COPY_VAULT.cmd
echo     collectors-maintenance   outils periodiques explicites
echo     collectors-research      collecteurs de recherche explicites
echo     collectors-all           tous les collecteurs ^(diagnostic exceptionnel^)
echo   Rapports / recherche :
echo     report              rapport du jour
echo     self-test           verification rapide 7 sections
echo     test                suite complete TOUT-TESTER
echo     audit               audit ~180 controles ^(resultat-audit.md^)
echo     replay              lance ANALYSER_BACKTESTS_REPLAYS.cmd
echo     moisson [github^|relire^|voir^|stop]     moissonneur de recherche
echo   Ops :
echo     verify-oos [install^|uninstall^|run^|diag^|test-notif]   verificateur OOS local
echo     github-push     delegue au pousseur securise avec Git embarque
echo     reset-paper --confirm   remise a zero VOLONTAIRE ^(sauvegarde horodatee avant^)
echo     portable-check          verifie le runtime Python relocalisable
echo     portable-install        installe/repare le runtime Windows x64 local
echo     portable-build          clone de secours complet ^(donnees/historique inclus^)
echo     portable-zip            ZIP application seule, demarrage propre
echo     portable-proof          preuve PC A vers PC B ^(15 min + replay full/deep^)
echo     menu                cette aide
echo.
echo   Dependances optionnelles :
echo     Ollama    explications IA locales ^(repli automatique sur phrases-regles si absent^)
echo     websockets   collecteurs WS ^(BBO/userFills/lab-microstructure^)
echo.
echo   Securite : lecture seule marche. 0 ordre reel, 0 cle, 0 signature.
echo.
REM ENG-037 : table documentee des codes de sortie.
echo   Codes de sortie :
echo     0   succes
echo     2   erreur de la commande executee
echo     3   verrou d'instance ^(deja en cours^)
echo     4   argument inconnu
echo     5   API Hyperliquid non joignable
echo     7   securite — flag mainnet/testnet actif ^(paper-only viole^)
echo     8   deja en cours ^(instance existante sur le port^)
echo    30   portable_env absent ou invalide
echo    31   erreur de sous-commande
echo    32   Python 3.11+ requis ^(version trop ancienne^)
echo    64   erreur de configuration critique
echo.
goto :fin

REM -------- PORTABILITE WINDOWS --------
:cmd_portablecheck
echo.
"%HYPERSMART_PYTHON%" tools\portable_runtime.py --root "%~dp0." check --require-embedded --json
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :portablecheck_fin
"%HYPERSMART_PYTHON%" tools\portable_runtime.py --root "%~dp0." relocate-check --json
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :portablecheck_fin
if exist "%~dp0PORTABLE_FULL_CLONE_MANIFEST.json" (
  "%HYPERSMART_PYTHON%" -m hl_observer.ops.portable_clone --verify "%~dp0."
  set "RC=%ERRORLEVEL%"
)
:portablecheck_fin
if "%RC%"=="0" echo PORTABLE_LAUNCHER_CHECK_OK
echo.
goto :fin

:cmd_portableinstall
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install_portable_runtime.ps1" -ProjectRoot "%~dp0."
set "RC=%ERRORLEVEL%"
echo.
goto :fin

:cmd_portablebuild
echo.
"%HYPERSMART_PYTHON%" -m hl_observer.ops.portable_clone --racine "%~dp0."
set "RC=%ERRORLEVEL%"
echo.
goto :fin

:cmd_portablezip
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\create_portable_bundle.ps1" -ProjectRoot "%~dp0."
set "RC=%ERRORLEVEL%"
echo.
goto :fin

:cmd_portableproof
echo.
"%HYPERSMART_PYTHON%" -m hl_observer.ops.portable_transfer_proof --root "%~dp0." --collection-seconds 900
set "RC=%ERRORLEVEL%"
echo.
goto :fin

REM -------- STATUT (lecture seule) --------
:cmd_status
echo.
echo   ===  STATUT HYPERSMART  ^(lecture seule^)  ===
if exist "runtime\data\launcher_pids.json" ( echo   Registre lanceur : & type "runtime\data\launcher_pids.json" & echo. ) else ( echo   Pas de registre lanceur. )
REM ENG-085 : test de socket rapide (Python) au lieu de Test-NetConnection (lent, pas universel).
"%HYPERSMART_PYTHON%" -c "import socket,sys;s=socket.socket();s.settimeout(1);r=s.connect_ex(('127.0.0.1',%HYPERSMART_PORT%));s.close();print(f'  UI %HYPERSMART_PORT% : {\"ACTIVE\" if r==0 else \"inactive\"}')"
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs status harvest
set "RC=%ERRORLEVEL%"
echo.
goto :fin

REM -------- SANTE LIVE (tableau dynamique + journal horodate) --------
:cmd_sante
echo   Tableau de sante live des collecteurs (Ctrl-C pour quitter).
echo   Journal append-only : runtime\logs\sante_journal.log
"%HYPERSMART_PYTHON%" -m hl_observer.ops.moniteur_sante "%~dp0." --intervalle 2
set "RC=%ERRORLEVEL%"
goto :fin

REM -------- STOP (cible, jamais de kill global) --------
:cmd_stop
echo.
echo   Arret cible des collecteurs + userfills ^(par ligne de commande du projet ; aucun kill global^)...
call :stop_impl
set "RC=%ERRORLEVEL%"
call :stop_launcher_wrappers
echo.
echo   Arret + cloture termines ^(code %RC%^). QUARANTINED si un writer vivait encore ou un artefact manque.
echo.
goto :fin

:stop_impl
REM ARRET CIBLE (Fix 5) : SEULEMENT les PID enregistres du run + enfants verifies + process signes
REM registre + detenteur valide du port 8794 + verrou userfills. AUCUN motif large (*hl_observer*/*projet*).
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs arreter
set "RC_SUP=%ERRORLEVEL%"
REM === ITEMS 4 & 8 : CLOTURE SURE APRES l'arret des writers. On NE passe PLUS --writers-arretes : la
REM   preuve d'arret est CALCULEE independamment (registre PID -> aucun collecteur vivant). La session ne
REM   passe COMPLETE que si writers reellement arretes + checksums OK + artefacts reels + ZERO orphelin ;
REM   sinon QUARANTINED. Un collecteur orphelin encore vivant => QUARANTINED (jamais un faux COMPLETE).
"%HYPERSMART_PYTHON%" -m hl_observer.ops.session_harvest cloturer "%~dp0."
set "RC_CLO=%ERRORLEVEL%"
REM item 11 : libere le verrou d'instance (le lanceur est autoritaire sur son cycle de vie).
"%HYPERSMART_PYTHON%" -m hl_observer.ops.verrou_lanceur liberer "%~dp0." >nul 2>&1
REM item 9 : PREMIER code non nul (superviseur puis cloture). Jamais un exit /b 0 systematique.
set "RC_STOP=0"
if not "%RC_SUP%"=="0" ( set "RC_STOP=%RC_SUP%" ) else ( if not "%RC_CLO%"=="0" set "RC_STOP=%RC_CLO%" )
exit /b %RC_STOP%

:stop_launcher_wrappers
REM Les anciens wrappers PowerShell pouvaient rester bloques sur Read-Host apres que
REM leurs enfants avaient ete arretes. On cible UNIQUEMENT ce script dans CE projet.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$root=[IO.Path]::GetFullPath('%~dp0'); $targets=@(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessId -ne $PID -and $_.Name -in @('powershell.exe','pwsh.exe') -and $_.CommandLine -like '*start_hypersmart_simulation.ps1*' -and $_.CommandLine -like ('*'+$root+'*') }); foreach($t in $targets){ $killPid=[int]$t.ProcessId; $parent=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$t.ParentProcessId) -ErrorAction SilentlyContinue; if($parent -and $parent.Name -eq 'cmd.exe' -and $parent.CommandLine -like '*LANCER_HYPERSMART.cmd*'){ $killPid=[int]$parent.ProcessId }; Write-Host ('  Arret ancien arbre lanceur HyperSmart pid='+$killPid); Start-Process -FilePath taskkill.exe -ArgumentList @('/PID',[string]$killPid,'/T','/F') -Wait -NoNewWindow }"
exit /b 0

REM -------- RESTART = stop puis autopilot --------
:cmd_restart
echo.
echo   Redemarrage : arret cible ^(collecteurs + userfills + moteur^) puis autopilot...
call :stop_impl
set "RC_STOP=%ERRORLEVEL%"
call :stop_launcher_wrappers
REM item 9 : un arret/cloture en echec NE redemarre PAS en silence (on propage le code).
if not "%RC_STOP%"=="0" (
  echo   [RESTART] Arret/cloture en echec ^(code %RC_STOP%^) : on NE redemarre pas. Corrige d'abord.
  set "RC=%RC_STOP%"
  goto :fin
)
timeout /t 6 >nul
goto :autopilot

REM -------- RESTART-USERFILLS (absorbe REDEMARRER / RELANCER / TUER-ORPHELIN) --------
:cmd_ruserfills
echo.
echo   Rechargement du collecteur userfills-live avec le code courant...
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs arreter-userfills
set "RC_USERFILLS=%ERRORLEVEL%"
if not "%RC_USERFILLS%"=="0" (
  echo   [USERFILLS] Arret refuse : verrou conserve et aucun nouveau processus lance.
  set "RC=%RC_USERFILLS%"
  goto :fin
)
cmd /c start "" /b tools\boucle_collecteur.cmd userfills-live tools\collecter_userfills_vaults.py 5
set "RC=%ERRORLEVEL%"
echo   collecteur userfills-live relance ^(detache, sans fenetre, code courant^).
timeout /t 9 >nul
if exist "runtime\data\userfills_live.lock" ( echo   OK : verrou recree : & type "runtime\data\userfills_live.lock" ) else ( echo   Pas encore de verrou ^(demarrage en cours, patiente ~10 s^). )
echo.
goto :fin

REM -------- COLLECTORS (absorbe REANIMER-COLLECTEURS ; reutilise la source unique) --------
:cmd_collectors
echo.
echo   Reanimation du profil CORE ^(idempotent, sans doublon^)...
call :demarrer_collecteurs
set "RC=%ERRORLEVEL%"
echo   Profil CORE actif. Journaux : runtime\logs\. Le moteur n'a pas ete touche.
echo.
goto :fin

:cmd_collectors_harvest
echo.
echo   Demarrage du profil HARVEST ^(collecte Copy-Vault, sans moteur principal^)...
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs demarrer-tous harvest
set "RC=%ERRORLEVEL%"
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs status harvest
if "%RC%"=="0" set "RC=%ERRORLEVEL%"
echo.
goto :fin

:cmd_collectors_maintenance
echo.
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs demarrer-tous maintenance
set "RC=%ERRORLEVEL%"
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs status maintenance
if "%RC%"=="0" set "RC=%ERRORLEVEL%"
echo.
goto :fin

:cmd_collectors_research
echo.
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs demarrer-tous research
set "RC=%ERRORLEVEL%"
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs status research
if "%RC%"=="0" set "RC=%ERRORLEVEL%"
echo.
goto :fin

:cmd_collectors_all
echo.
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs demarrer-tous all
set "RC=%ERRORLEVEL%"
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs status all
if "%RC%"=="0" set "RC=%ERRORLEVEL%"
echo.
goto :fin

REM -------- REPORT (absorbe RAPPORT-DU-JOUR) --------
:cmd_report
echo.
"%HYPERSMART_PYTHON%" tools\rapport_quotidien.py
set "RC=%ERRORLEVEL%"
echo.
REM ENG-061 : pas de pause ici — :fin gere la pause unique.
goto :fin

REM -------- TEST (absorbe TOUT-TESTER) --------
:cmd_test
"%HYPERSMART_PYTHON%" "%~dp0tools\lanceur_tout_tester.py" %2 %3 %4 %5 %6 %7 %8 %9
set "RC=%ERRORLEVEL%"
goto :fin

REM -------- AUDIT (absorbe TEST-AUDIT-complet) --------
:cmd_audit
echo.
echo   Lancement de l'audit ^(~180 controles^)...
REM LCH-029 : aucun pip install automatique dans un audit.
"%HYPERSMART_PYTHON%" tools\audit_report.py %2 %3 %4 %5 %6 %7 %8 %9
set "AUDIT_CODE=%ERRORLEVEL%"
set "RC=%AUDIT_CODE%"
if exist "resultat-audit.md" ( echo   Rapport ecrit : %~dp0resultat-audit.md ) else ( echo   ATTENTION : le rapport n'a pas ete ecrit. )
echo.
REM ENG-061 : pas de pause ici — :fin gere la pause unique.
goto :fin

REM -------- REPLAY / BACKTESTS (outil separe du runtime principal) --------
:cmd_replay
echo.
call "%~dp0tools\launchers\ANALYSER_BACKTESTS_REPLAYS.cmd" %2 %3 %4 %5 %6 %7 %8 %9
set "RC=%ERRORLEVEL%"
goto :fin

REM -------- MOISSON (absorbe LANCER-MOISSON-12H / MOISSONNER-GITHUB / RELIRE / VOIR / FERMER + workers) --------
:cmd_moisson
if /I "%~2"=="voir"   goto :moisson_voir
if /I "%~2"=="stop"   goto :moisson_stop
if /I "%~2"=="github" goto :moisson_github
if /I "%~2"=="relire" goto :moisson_relire
if not "%GITHUB_TOKEN%"=="" ( echo   Cle GitHub deja presente : on l'utilise. & goto :moisson_go )
set /p GITHUB_TOKEN=  Ta cle GitHub ^(vide = 60 req/h, sans recherche code^) :
:moisson_go
if not exist "%~dp0runtime\reports\legacy\moisson" mkdir "%~dp0runtime\reports\legacy\moisson" >nul 2>&1
if exist "%~dp0runtime\reports\legacy\moisson\moisson-termine.flag" del "%~dp0runtime\reports\legacy\moisson\moisson-termine.flag" >nul 2>&1
if exist "%~dp0runtime\reports\legacy\moisson\moisson-en-cours.txt" del "%~dp0runtime\reports\legacy\moisson\moisson-en-cours.txt" >nul 2>&1
start "MOISSON 12h - travail (NE PAS FERMER)" /min cmd /c "set PYTHONPATH=%~dp0src;%~dp0& set PYTHONIOENCODING=utf-8& set PYTHONUTF8=1& "%HYPERSMART_PYTHON%" tools\moissonner_10h.py --heures 12 > "%~dp0runtime\reports\legacy\moisson\moisson_console.txt" 2>&1& echo done> "%~dp0runtime\reports\legacy\moisson\moisson-termine.flag""
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\voir_dashboard.ps1" -Root "%~dp0"
echo   Moisson terminee. Resultat : runtime\reports\legacy\moisson\moisson-fini.md
goto :fin
:moisson_relire
if not exist "%~dp0runtime\reports\legacy\moisson" mkdir "%~dp0runtime\reports\legacy\moisson" >nul 2>&1
if not exist "%~dp0data\reports\moisson_10h_etat.json" ( echo   Aucun etat sauvegarde -- lance d'abord `moisson`. & goto :fin )
if exist "%~dp0runtime\reports\legacy\moisson\moisson-termine.flag" del "%~dp0runtime\reports\legacy\moisson\moisson-termine.flag" >nul 2>&1
start "MOISSON 12h - travail (NE PAS FERMER)" /min cmd /c "set PYTHONPATH=%~dp0src;%~dp0& set PYTHONIOENCODING=utf-8& set PYTHONUTF8=1& "%HYPERSMART_PYTHON%" tools\moissonner_10h.py --heures 3 --relire > "%~dp0runtime\reports\legacy\moisson\moisson_console.txt" 2>&1& echo done> "%~dp0runtime\reports\legacy\moisson\moisson-termine.flag""
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\voir_dashboard.ps1" -Root "%~dp0"
goto :fin
:moisson_github
"%HYPERSMART_PYTHON%" tools\moissonner_10h.py %3 %4 %5 %6 %7 %8 %9
echo.
goto :fin
:moisson_voir
title Tableau de bord - Moisson
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\voir_dashboard.ps1" -Root "%~dp0"
goto :fin
:moisson_stop
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs arreter-moisson
set "RC_MOISSON=%ERRORLEVEL%"
if not "%RC_MOISSON%"=="0" (
  echo   [MOISSON] Arret refuse ou incomplet : aucune suppression globale executee.
  set "RC=%RC_MOISSON%"
  goto :fin
)
if exist "%~dp0runtime\reports\legacy\moisson\moisson-termine.flag" del "%~dp0runtime\reports\legacy\moisson\moisson-termine.flag" >nul 2>&1
echo   Moisson fermee. Rien n'est perdu : relancer reprend ou on s'etait arrete.
goto :fin

REM -------- VERIFY-OOS (absorbe LANCER/INSTALLER/DESINSTALLER/VERIF-PLANIF/TESTER-NOTIFICATION) --------
:cmd_verifoos
if /I "%~2"=="install"    goto :oos_install
if /I "%~2"=="uninstall"  goto :oos_uninstall
if /I "%~2"=="diag"       goto :oos_diag
if /I "%~2"=="test-notif" goto :oos_testnotif
if not exist "runtime\rapports\checkpoint_oos_shadow" mkdir "runtime\rapports\checkpoint_oos_shadow" >nul 2>&1
"%HYPERSMART_PYTHON%" tools\verif_checkpoint_oos_shadow.py >> "runtime\rapports\checkpoint_oos_shadow\verif.log" 2>&1
set "RC=%ERRORLEVEL%"
goto :fin
:oos_install
REM ENG-090 : verifier la presence de wscript.exe (requis pour la tache planifiee silencieuse).
where wscript.exe >nul 2>nul
if errorlevel 1 (
  echo   [ERREUR] wscript.exe introuvable. La tache planifiee OOS ne peut pas etre installee.
  set "RC=31"
  goto :fin
)
REM ENG-087 : schtasks peut exiger des droits admin. Detecter au lieu d'echouer en silence.
schtasks /Create /SC MINUTE /MO 30 /TN "HyperSmart_VerifOOS" /TR "wscript.exe \"%~dp0tools\run_verify_oos_silent.vbs\"" /F
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo   [ERREUR] schtasks a echoue ^(code %RC%^). Droits administrateur peut-etre requis.
  echo   Essayez : clic droit sur LANCER_HYPERSMART.cmd ^> "Executer en tant qu'administrateur"
  echo   puis : LANCER_HYPERSMART.cmd verify-oos install
  goto :fin
)
schtasks /Query /TN "HyperSmart_VerifOOS" /V /FO LIST 2>nul | findstr /I "TaskName Next Task_To_Run Scheduled"
echo.
goto :fin
:oos_uninstall
schtasks /Delete /TN "HyperSmart_VerifOOS" /F
set "RC=%ERRORLEVEL%"
echo.
goto :fin
:oos_diag
set "DIR=%~dp0runtime\rapports\checkpoint_oos_shadow"
if not exist "%DIR%" mkdir "%DIR%" >nul 2>&1
schtasks /Query /TN "HyperSmart_VerifOOS" /V /FO LIST
set "RC=%ERRORLEVEL%"
schtasks /Run /TN "HyperSmart_VerifOOS"
if not "%RC%"=="0" goto :oos_diag_fin
timeout /t 12 /nobreak >nul
if exist "%DIR%\status.json" type "%DIR%\status.json"
:oos_diag_fin
echo.
goto :fin
:oos_testnotif
"%HYPERSMART_PYTHON%" tools\verif_checkpoint_oos_shadow.py --test-notification
set "RC=%ERRORLEVEL%"
echo   Code de sortie : %ERRORLEVEL%
echo.
goto :fin

REM -------- GITHUB-PUSH : un seul chemin securise, Git embarque uniquement --------
:cmd_github
call "%~dp0POUSSER-GITHUB-FORCE.cmd" %2 %3 %4 %5 %6 %7 %8 %9
set "RC=%ERRORLEVEL%"
echo.
goto :fin

REM -------- RESET-PAPER (Fix 1) : remise a zero VOLONTAIRE, sauvegarde horodatee, exige --confirm --------
:cmd_resetpaper
echo.
echo   RESET PAPER : efface equity/PnL/positions ^(sauvegarde horodatee AVANT^). Exige --confirm.
"%HYPERSMART_PYTHON%" tools\reset_paper.py %2 %3
set "RC=%ERRORLEVEL%"
echo.
goto :fin

REM -------- SELF-TEST (absorbe VERIFIER-TOUT) --------
:cmd_selftest
"%HYPERSMART_PYTHON%" tools\verifier_tout.py %2 %3 %4 %5 %6 %7 %8 %9
set "RC=%ERRORLEVEL%"
echo.
goto :fin

REM -------- AVANCES (conservation totale) --------
:cmd_auditmoiss
if not exist "%~dp0runtime\reports\legacy" mkdir "%~dp0runtime\reports\legacy" >nul 2>&1
"%HYPERSMART_PYTHON%" tools\audit_moissonneur.py > "%~dp0runtime\reports\legacy\audit_moissonneur.txt" 2>&1
echo   Rapport : runtime\reports\legacy\audit_moissonneur.txt
goto :fin
:cmd_premierraw
"%HYPERSMART_PYTHON%" -c "from hl_observer.experimental import rapport_raw as R; p=R.ecrire_rapport('.'); print('Rapport ecrit :', p) if p else print('Aucun OPEN RAW pour l instant.')"
if exist "runtime\rapports\PREMIER_RAW.md" type "runtime\rapports\PREMIER_RAW.md"
echo.
goto :fin
:cmd_killuserfills
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs arreter-userfills
set "RC=%ERRORLEVEL%"
echo.
goto :fin
:cmd_verifl2
if not exist "runtime\data" mkdir "runtime\data" >nul 2>&1
"%HYPERSMART_PYTHON%" -c "import sys; sys.path.insert(0,'tools'); import collecter_userfills_vaults as C; [print(c, C._lecteur_l2_ondemand(c)) for c in ('WLD','AERO','TIA','IO','LDO','SOL')]"
echo.
goto :fin
:cmd_sonde
if not exist "runtime\data" mkdir "runtime\data" >nul 2>&1
"%HYPERSMART_PYTHON%" "tools\sonde_confirmation_vaults.py" --shard B
echo.
goto :fin
:cmd_notiftest
"%HYPERSMART_PYTHON%" tools\verif_checkpoint_oos_shadow.py --test-notification
echo.
goto :fin
