@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0" || (
  echo [ERREUR] Impossible d'ouvrir le depot local.
  pause
  exit /b 2
)
chcp 65001 >nul
title ALINA SMART FLOW - COLLECTEURS (Copy-Vault)

rem ============================================================
rem  ALINA SMART FLOW - COLLECTE COPY-VAULT
rem  Superviseur resilient avec auto-recovery et backoff
rem
rem  Sources observees : fills leaders, vaults, L2/BBO, prix, backfills,
rem                       OI/funding/premium (asset-ctx), multi-venue natif,
rem                       microstructure dense, liquidations, overshoots
rem  Checkpoints causaux : ecriture dediee sous bail de campagne
rem  Replay historique : seuls les shards valides SAFE sont admissibles
rem  Ordres : aucun | execution mainnet/testnet : desactivee
rem
rem  Ameliorations v2 :
rem    - Auto-recovery avec backoff exponentiel (30s -> 5min max)
rem    - Detection d'instance deja en cours (mutex fichier)
rem    - Verification Python 3.11+ et dependances completes
rem    - Health check des fichiers critiques au demarrage
rem    - Compteur de restarts et uptime affiche
rem    - Mode --status pour inspecter sans lancer
rem    - Mode --once pour une seule campagne sans boucle
rem    - Duree de campagne configurable (defaut 6 jours)
rem    - Journal : runtime\logs\economic-collector-watchdog.jsonl
rem ============================================================

set "CV_ROOT=%~dp0"
set "CV_DURATION=518400"
set "CV_LEASE=120"
set "CV_INTERVAL=30"
set "CV_MODE=loop"
set "CV_MAX_RESTARTS=50"
set "CV_BACKOFF_INIT=30"
set "CV_BACKOFF_MAX=300"
set "CV_PROFILE=copy-vault"
set "CV_LOCKFILE=%CV_ROOT%runtime\data\collecteurs.lock"

if /I "%~1"=="--help" goto :help
if /I "%~1"=="-h" goto :help
if /I "%~1"=="--status" goto :status
if /I "%~1"=="--stop" set "CV_MODE=stop"&shift
if /I "%~1"=="--arreter" set "CV_MODE=stop"&shift
if /I "%~1"=="--once" set "CV_MODE=once"&shift
if /I "%~1"=="--duration" set "CV_DURATION=%~2"&shift&shift

rem --- Python ---
set "CV_PYTHON="
set "CV_PY_ARGS="
if exist "%CV_ROOT%tools\python\python.exe" set "CV_PYTHON=%CV_ROOT%tools\python\python.exe"
if not defined CV_PYTHON if exist "%CV_ROOT%.venv\Scripts\python.exe" set "CV_PYTHON=%CV_ROOT%.venv\Scripts\python.exe"
if not defined CV_PYTHON (
  where py >nul 2>nul
  if not errorlevel 1 (
    set "CV_PYTHON=py"
    set "CV_PY_ARGS=-3"
  )
)
if not defined CV_PYTHON (
  where python >nul 2>nul
  if not errorlevel 1 set "CV_PYTHON=python"
)
if not defined CV_PYTHON goto :python_missing

rem --- Version Python 3.11+ ---
"%CV_PYTHON%" %CV_PY_ARGS% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 (
  echo [ERREUR] Python 3.11 ou plus requis. Version detectee :
  "%CV_PYTHON%" %CV_PY_ARGS% --version
  goto :fail_deps
)

rem --- Dependances ---
"%CV_PYTHON%" %CV_PY_ARGS% -c "import httpx, websockets, orjson" >nul 2>nul
if errorlevel 1 (
  "%CV_PYTHON%" %CV_PY_ARGS% -c "import httpx, websockets" >nul 2>nul
  if errorlevel 1 goto :dependencies_missing
)

rem --- Fichiers critiques ---
if not exist "%CV_ROOT%tools\watch_economic_collectors.py" (
  echo [ERREUR] Module manquant : tools\watch_economic_collectors.py
  goto :fail_deps
)
if not exist "%CV_ROOT%src\hl_observer\ops\bounded_collection.py" (
  echo [ERREUR] Module manquant : src\hl_observer\ops\bounded_collection.py
  goto :fail_deps
)
if not exist "%CV_ROOT%src\hl_observer\ops\collecteur_registry.py" (
  echo [ERREUR] Module manquant : src\hl_observer\ops\collecteur_registry.py
  goto :fail_deps
)

rem --- Verifier syntaxe du watchdog ---
"%CV_PYTHON%" %CV_PY_ARGS% -c "import ast,sys; ast.parse(open(sys.argv[1],'rb').read())" "%CV_ROOT%tools\watch_economic_collectors.py" >nul 2>nul
if errorlevel 1 (
  echo [ERREUR] Syntaxe invalide dans tools\watch_economic_collectors.py
  goto :fail_deps
)

rem --- Securite read-only ---
set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
set "REAL_MAINNET_TRADING=false"
set "TESTNET_ONLY=true"
set "HYPERSMART_EXPERIMENTAL_PAPER=0"
rem Journal d'audit des evenements canoniques desactive : non relu par les
rem replays/backtests, il gonflait a plusieurs Go. Mettre 1 pour le reactiver.
set "ALINA_CANONICAL_EVENT_LEDGER=0"
rem Page de vaults suivie par ce PC = 0. La lane GitHub en suit une autre
rem (offset distinct) pour couvrir des leaders differents sans chevauchement.
set "ALINA_VAULT_ROTATION_OFFSET=0"
set "PYTHONPATH=%CV_ROOT%src;%CV_ROOT%tools;%PYTHONPATH%"
rem Sorties en UTF-8 pour TOUS les sous-collecteurs : evite les UnicodeEncodeError
rem (ex. caractere « fleche » non encodable en cp1252 qui faisait planter des cycles).
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

rem --- Dossiers runtime ---
if not exist "%CV_ROOT%runtime\logs" mkdir "%CV_ROOT%runtime\logs"
if not exist "%CV_ROOT%runtime\data" mkdir "%CV_ROOT%runtime\data"

rem --- Arret propre immediat demande (--stop) : rien a demarrer ---
if /I "%CV_MODE%"=="stop" goto :stop

rem --- Detection d'instance existante : collecteurs REELLEMENT vivants ? ---
rem     On verifie les PID des collecteurs (le verrou n'etait qu'un nombre aleatoire,
rem     donc l'ancienne detection ne matchait jamais un vrai process).
set "CV_DEJA="
for %%F in (poll_leaders.pid explorer_autonome.pid) do (
  if exist "%CV_ROOT%runtime\data\%%F" (
    for /f "usebackq tokens=*" %%A in ("%CV_ROOT%runtime\data\%%F") do (
      tasklist /FI "PID eq %%A" /NH 2>nul | findstr /I "python" >nul 2>nul && set "CV_DEJA=1"
    )
  )
)
if defined CV_DEJA (
  echo [DEJA EN COURS] Des collecteurs tournent deja sur ce PC.
  echo   Arretez-les d'abord : appuyez sur  q  dans leur ecran, ou relancez avec  --stop.
  goto :fail_lock
)

rem --- Auto-reparation : restes d'un Ctrl+C precedent. CMD ne peut pas
rem     piéger Ctrl+C ; si "Terminate batch job" a coupe sans :cleanup, le
rem     poll a pu rester. On le neutralise AVANT une nouvelle campagne. ---
if exist "%CV_ROOT%runtime\data\poll_leaders.pid" (
  for /f "usebackq tokens=*" %%P in ("%CV_ROOT%runtime\data\poll_leaders.pid") do taskkill /PID %%P /T /F >nul 2>nul
  del /f /q "%CV_ROOT%runtime\data\poll_leaders.pid" >nul 2>nul
)
taskkill /FI "WINDOWTITLE eq ALINA-POLL-LEADERS*" /T /F >nul 2>nul
rem Idem explorer autonome + superviseur de fond (orphelins d'un Ctrl+C+O precedent).
if exist "%CV_ROOT%runtime\data\explorer_autonome.pid" (
  for /f "usebackq tokens=*" %%P in ("%CV_ROOT%runtime\data\explorer_autonome.pid") do taskkill /PID %%P /T /F >nul 2>nul
  del /f /q "%CV_ROOT%runtime\data\explorer_autonome.pid" >nul 2>nul
)
taskkill /FI "WINDOWTITLE eq ALINA-EXPLORER-AUTO*" /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq ALINA-ASSET-CTX*" /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq ALINA-SUPERVISOR*" /T /F >nul 2>nul
if exist "%CV_ROOT%runtime\data\stop_collecteurs.flag" del /f /q "%CV_ROOT%runtime\data\stop_collecteurs.flag" >nul 2>nul
if exist "%CV_ROOT%runtime\data\.session_nettoyee" del /f /q "%CV_ROOT%runtime\data\.session_nettoyee" >nul 2>nul

rem --- Ecrire le verrou (PID du cmd courant) ---
echo %RANDOM%%RANDOM%> "%CV_LOCKFILE%"

rem --- SESSION FRAICHE : on NE certifie PAS au lancement (c'est LENT et c'est le role
rem     du certificateur A L'ARRET, sur les donnees de la session). On se contente
rem     d'ARCHIVER l'eventuel reste d'une session precedente (RAPIDE : deplace juste les
rem     tapes) pour repartir a ZERO sans rien perdre. La certification -> coffre a lieu
rem     a l'arret (touche q), sur la session courante. ---
if exist "%CV_ROOT%tools\archiver_tapes.py" (
  if not exist "%CV_ROOT%runtime\logs\coffre_certifie" mkdir "%CV_ROOT%runtime\logs\coffre_certifie" >nul 2>nul
  echo [RESET] Session a zero : archivage rapide du reste eventuel ^(rien n'est perdu^)...
  "%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\archiver_tapes.py" --root "%CV_ROOT%." >> "%CV_ROOT%runtime\logs\coffre_session.log" 2>&1
)

rem --- Affichage ---
for /f "tokens=1-2 delims=." %%A in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set "CV_START_TIME=%%A"
echo.
echo ================================================================
echo   ALINA SMART FLOW - COLLECTE DE DONNEES
echo   %CV_START_TIME%
echo ================================================================
echo.
echo   Que fait ce lanceur ?
echo   Collecte en continu les prix, carnets, trades, liquidations
echo   et vaults depuis Hyperliquid + venues secondaires (Binance,
echo   Bybit, OKX, Gate, Bitget) pour alimenter les backtests et
echo   replays du laboratoire quant Copy-Vault.
echo.
echo   14 collecteurs actifs (profil %CV_PROFILE%)
echo   + poll causal des leaders (REST) : casse le cap WebSocket ~10/IP
echo   + explorer autonome : decouvre les traders ACTIFS (suivi adaptatif)
echo   Securite : PAPER / READ-ONLY / FAIL-CLOSED
echo.
echo   ARRET : appuyez sur  q  dans l'ecran -^> certification coffre + reset + rapport auto.
echo   ^(Ctrl+C marche aussi : le nettoyage se fait AVANT tout prompt O/N.^)
echo.
echo   L'ecran unique affiche tous les collecteurs + toutes les donnees en temps reel.
echo ================================================================
echo.

"%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\cmd_progress.py" start > "%TEMP%\alina_cmd_start.tmp" 2>nul
set /p ALINA_CMD_START=<"%TEMP%\alina_cmd_start.tmp"
set "CV_RESTARTS=0"
set "CV_BACKOFF=%CV_BACKOFF_INIT%"
set "CV_CONSECUTIVE_FAILS=0"

rem --- Poll causal des leaders : casse le plafond WebSocket (~10 userFills/IP)
rem     en suivant plus de leaders via REST userFillsByTime (forward, observed_at
rem     honnete, discipline anti-look-ahead). Fenetre dediee, boucle resiliente,
rem     arretee proprement au nettoyage. Leaders lus depuis copy_whitelist.json.
rem Sharding multi-IP : chaque lane (PC + runners GitHub) suit une tranche
rem DISJOINTE de leaders. Defaut 1/0 (tout en local) ; surcharger par env sur
rem les autres lanes pour un scaling lineaire sans chevauchement.
if not defined ALINA_POLL_SHARD_COUNT set "ALINA_POLL_SHARD_COUNT=1"
if not defined ALINA_POLL_SHARD_INDEX set "ALINA_POLL_SHARD_INDEX=0"
rem --- Suivi ADAPTATIF des leaders : base curee + traders ACTIFS decouverts par l'explorer ---
rem     (diversifie les fills ; le debit REST reste cape par l'AIMD anti-429 du poll) ---
if exist "%CV_ROOT%tools\fusionner_leaders_actifs.py" (
  "%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\fusionner_leaders_actifs.py" --root "%CV_ROOT%." 2>nul
)

if exist "%CV_ROOT%tools\collecter_userfills_poll.py" (
  del /f /q "%CV_ROOT%runtime\data\poll_leaders.pid" >nul 2>nul
  start "ALINA-POLL-LEADERS" /B "%CV_ROOT%tools\_run_poll_leaders.cmd"
  echo [POLL] Collecteur fills leaders demarre SANS fenetre - log: runtime\logs\poll-leaders.log
)

rem --- Explorer autonome : auto-decouverte de leaders + estimation de fills, SANS fenetre ---
if exist "%CV_ROOT%tools\explorer_autonome.py" (
  del /f /q "%CV_ROOT%runtime\data\explorer_autonome.pid" >nul 2>nul
  start "ALINA-EXPLORER-AUTO" /B "%CV_ROOT%tools\_run_explorer_autonome.cmd"
  echo [EXPLORER] Explorer autonome demarre SANS fenetre - log: runtime\logs\explorer-autonome.log
)

rem --- Asset-ctx : OI/funding/premium (metaAndAssetCtxs), flux SEPARE (zero contention), utilise par le labo ---
if exist "%CV_ROOT%tools\collecter_asset_ctx.py" (
  start "ALINA-ASSET-CTX" /B "%CV_ROOT%tools\_run_asset_ctx.cmd"
  echo [ASSET-CTX] OI/funding/premium demarre SANS fenetre - log: runtime\logs\asset-ctx.log
)

rem --- Nettoyer un eventuel drapeau d'arret precedent ---
if exist "%CV_ROOT%runtime\data\stop_collecteurs.flag" del /f /q "%CV_ROOT%runtime\data\stop_collecteurs.flag" >nul 2>nul

rem --- Superviseur des collecteurs EN ARRIERE-PLAN (boucle resiliente, log dedie) ---
start "ALINA-SUPERVISOR" /B "%CV_ROOT%tools\_run_supervisor_loop.cmd"
echo [SUPERVISEUR] Collecteurs demarres en arriere-plan - log: runtime\logs\supervisor.log

rem --- Declenche AUSSI les lanes de collecte sur GitHub (multi-IP, gratuit car repo public) ---
rem     fail-soft : si gh absent/non connecte, la collecte locale continue normalement.
where gh >nul 2>nul
if errorlevel 1 (
  echo [GITHUB] gh CLI absent : lanes GitHub non declenchees. ^(Installe gh + 'gh auth login' pour le multi-IP.^)
) else (
  echo [GITHUB] Declenchement des lanes de collecte sur GitHub ^(poll/WS/L2/market/contexte/explorer^)...
  for %%W in (copy-vault-poll-lanes userfills-live-lanes copy-vault-l2-lanes copy-vault-market-lanes copy-vault-contexte-lanes explorer-collecte) do (
    gh workflow run "%%W.yml" --ref main >nul 2>nul && echo   [GITHUB] %%W : declenche || echo   [GITHUB] %%W : non declenche
  )
)
echo.
echo   ============================================================
echo     ECRAN UNIQUE : tous les collecteurs + toutes les donnees
echo     Appuyez sur  q  pour ARRETER proprement ^(evite le prompt O/N^)
echo     -^> envoi au coffre certifie + reset + rapport automatiques
echo   ============================================================
echo.
timeout /t 2 /nobreak >nul 2>nul

rem --- ECRAN UNIQUE au premier plan (lecture seule) ---
"%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\affichage_temps_reel.py" --root "%CV_ROOT%." --intervalle 2

rem --- L'utilisateur a quitte l'ecran : nettoyage + depot coffre ---
goto :cleanup

:status
echo.
echo === ETAT DES COLLECTEURS COPY-VAULT ===
echo.
set "CV_DEJA="
for %%F in (poll_leaders.pid explorer_autonome.pid) do (
  if exist "%CV_ROOT%runtime\data\%%F" (
    for /f "usebackq tokens=*" %%A in ("%CV_ROOT%runtime\data\%%F") do (
      tasklist /FI "PID eq %%A" /NH 2>nul | findstr /I "python" >nul 2>nul && set "CV_DEJA=1"
    )
  )
)
if defined CV_DEJA (
  echo Statut : EN COURS ^(collecteurs vivants^)
) else (
  echo Statut : ARRETE
)
echo.
if exist "%CV_ROOT%runtime\data\economic_collection_pids.json" (
  echo --- Etat interne (economic_collection_pids.json^) ---
  "%CV_PYTHON%" %CV_PY_ARGS% -c "import json,sys; d=json.loads(open(sys.argv[1],'r',encoding='utf-8').read()); print('  Lease valide:',d.get('lease_valid','?')); print('  Schema:',d.get('schema_version','?')); pids=d.get('pids',{}); print('  Workers:',len(pids)); [print(f'    {k}: PID {v}') for k,v in sorted(pids.items())]" "%CV_ROOT%runtime\data\economic_collection_pids.json" 2>nul
) else (
  echo Aucun fichier d'etat trouve.
)
echo.
if exist "%CV_ROOT%runtime\logs\collecteur_restarts.log" (
  echo --- Derniers restarts ---
  powershell -NoProfile -Command "Get-Content '%CV_ROOT%runtime\logs\collecteur_restarts.log' | Select-Object -Last 5"
)
echo.
if exist "%CV_ROOT%runtime\logs\economic-collector-watchdog.jsonl" (
  echo --- Dernier log watchdog ---
  powershell -NoProfile -Command "$lines = Get-Content '%CV_ROOT%runtime\logs\economic-collector-watchdog.jsonl' -Tail 1; $lines"
)
echo.
set "RC=0"
goto :end

:help
echo.
echo Usage : LANCER_COLLECTEURS_COPY_VAULT.cmd [options]
echo.
echo  (defaut)         Collecte continue + ECRAN UNIQUE temps reel ; auto-recovery.
echo  --once           Une seule campagne, pas de boucle de recovery
echo  --duration N     Duree de chaque campagne en secondes (defaut: 518400 = 6 jours)
echo  --status         Afficher l'etat des collecteurs sans lancer
echo  --stop           Arret propre et immediat ^(invalide le bail, stoppe tout^)
echo  --help / -h      Cette aide
echo.
echo Fonctionnement :
echo   - Collecteurs + poll + explorer autonome tournent EN ARRIERE-PLAN.
echo   - Un ECRAN UNIQUE affiche tous les flux et derniers fills en temps reel.
echo   - Pour ARRETER : appuyez sur  q  -^> stop + CERTIFICATION ^(runtime/data vers
echo     runtime/coffre_certifie, que le labo lit^) + reset session + rapport auto.
echo   - Suivi ADAPTATIF des leaders : base curee + traders actifs decouverts.
echo   - Rapport detaille : runtime/logs/rapport_collecteurs.log ^(erreurs + ameliorations^).
echo.
echo Collecteurs lances (profil copy-vault / harvest, 14 collecteurs) :
echo   CORE     : allmids-collector, bbo-collector, userfills-live
echo   DONNEES  : carnet-collector, venues-collector, marks-collector
echo   ANALYSE  : liq-collector, overshoot-collector, vault-collector, scorer-vaults
echo   BACKFILL : backfill-fills, backfill-candles-vaults
echo   CAUSAL   : copy-vault-checkpoints (L2 lie aux fills leaders)
echo   ENRICHI  : native-venues, lab-microstructure
echo.
echo Auto-recovery :
echo   Si le superviseur crash, il est relance avec un backoff exponentiel
echo   (30s, 60s, 120s, 240s, 300s max). Apres une campagne reussie, le backoff
echo   est reinitialise. Maximum %CV_MAX_RESTARTS% restarts avant abandon.
echo.
echo Securite : PAPER / READ-ONLY / FAIL-CLOSED
echo   Aucun ordre, aucune execution mainnet/testnet, aucune cle privee.
echo.
set "RC=0"
goto :end

:python_missing
echo [ERREUR] Python 3.11+ introuvable. Installe Python ou le runtime embarque.
set "RC=30"
goto :end

:dependencies_missing
echo [ERREUR] Dependances requises absentes (httpx, websockets).
echo Le lanceur n'installe rien automatiquement.
echo Utilise : pip install httpx websockets
set "RC=31"
goto :end

:fail_deps
set "RC=32"
goto :end

:fail_lock
set "RC=33"
goto :end

:cleanup
rem Si l'ecran Python a deja tout nettoye (certif + reset + rapport), ne pas le refaire.
if exist "%CV_ROOT%runtime\data\.session_nettoyee" (
  del /f /q "%CV_ROOT%runtime\data\.session_nettoyee" >nul 2>nul
  echo.
  echo [ARRET] Nettoyage deja fait par l'ecran ^(certification + reset + rapport^).
  goto :cleanup_fin
)
echo.
echo [ARRET] Arret propre en cours...
rem --- Signal d'arret au superviseur de fond + arret des workers collecteurs ---
>"%CV_ROOT%runtime\data\stop_collecteurs.flag" echo 1
if defined CV_PYTHON "%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\watch_economic_collectors.py" --root "%CV_ROOT%." --stop >nul 2>nul
taskkill /FI "WINDOWTITLE eq ALINA-SUPERVISOR*" /T /F >nul 2>nul
rem --- Arreter l'explorer autonome ---
if exist "%CV_ROOT%runtime\data\explorer_autonome.pid" (
  for /f "usebackq tokens=*" %%P in ("%CV_ROOT%runtime\data\explorer_autonome.pid") do taskkill /PID %%P /T /F >nul 2>nul
  del /f /q "%CV_ROOT%runtime\data\explorer_autonome.pid" >nul 2>nul
)
taskkill /FI "WINDOWTITLE eq ALINA-EXPLORER-AUTO*" /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq ALINA-ASSET-CTX*" /T /F >nul 2>nul
rem --- Arreter le poll des leaders (fenetre dediee) ---
if exist "%CV_ROOT%runtime\data\poll_leaders.pid" (
  for /f "usebackq tokens=*" %%P in ("%CV_ROOT%runtime\data\poll_leaders.pid") do taskkill /PID %%P /T /F >nul 2>nul
  del /f /q "%CV_ROOT%runtime\data\poll_leaders.pid" >nul 2>nul
)
taskkill /FI "WINDOWTITLE eq ALINA-POLL-LEADERS*" /T /F >nul 2>nul

rem --- ENVOYER LES DONNEES AU BON ENDROIT : depot dans le COFFRE CERTIFIE
rem     (scellage verifie) puis remise a zero des flux. Zero perte. ---
if exist "%CV_ROOT%tools\sceller_coffre_local.py" (
  echo [COFFRE] Certification + envoi des donnees de la session vers le coffre certifie...
  "%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\sceller_coffre_local.py" --root "%CV_ROOT%." >> "%CV_ROOT%runtime\logs\coffre_session.log" 2>&1
  echo [COFFRE] Donnees validees rangees dans runtime\coffre_certifie ^(le labo y puisera^).
)
if exist "%CV_ROOT%tools\archiver_tapes.py" (
  echo [RESET] Archivage des tapes : prochaine session a zero ^(rien n'est perdu^)...
  "%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\archiver_tapes.py" --root "%CV_ROOT%." >> "%CV_ROOT%runtime\logs\coffre_session.log" 2>&1
)
del /f /q "%CV_ROOT%runtime\data\stop_collecteurs.flag" >nul 2>nul
rem --- RAPPORT detaille : toutes les erreurs + ameliorations detectees ---
if exist "%CV_ROOT%tools\rapport_collecteurs.py" (
  echo [RAPPORT] Generation du rapport detaille ^(erreurs + ameliorations^)...
  "%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\rapport_collecteurs.py" --root "%CV_ROOT%." 2>nul
  echo [RAPPORT] Tout est dans : runtime\logs\rapport_collecteurs.log
)
:cleanup_fin
rem --- Supprimer le verrou ---
if exist "%CV_LOCKFILE%" del /f /q "%CV_LOCKFILE%" >nul 2>nul
for /f "tokens=1-2 delims=." %%A in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set "CV_END_TIME=%%A"
"%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\cmd_progress.py" elapsed
echo.
echo [FIN] %CV_END_TIME% — %CV_RESTARTS% campagne(s) executee(s)
set "RC=0"
if defined CV_CONSECUTIVE_FAILS if %CV_CONSECUTIVE_FAILS% GTR 0 set "RC=1"
goto :end

:stop
echo.
echo === ARRET PROPRE DES COLLECTEURS COPY-VAULT ===
rem Arret immediat : invalide le bail + tue les workers verifies (watchdog --stop).
>"%CV_ROOT%runtime\data\stop_collecteurs.flag" echo 1
if defined CV_PYTHON "%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\watch_economic_collectors.py" --root "%CV_ROOT%." --stop
taskkill /FI "WINDOWTITLE eq ALINA-SUPERVISOR*" /T /F >nul 2>nul
rem Arret de l'explorer autonome.
if exist "%CV_ROOT%runtime\data\explorer_autonome.pid" (
  for /f "usebackq tokens=*" %%P in ("%CV_ROOT%runtime\data\explorer_autonome.pid") do taskkill /PID %%P /T /F >nul 2>nul
  del /f /q "%CV_ROOT%runtime\data\explorer_autonome.pid" >nul 2>nul
)
taskkill /FI "WINDOWTITLE eq ALINA-EXPLORER-AUTO*" /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq ALINA-ASSET-CTX*" /T /F >nul 2>nul
del /f /q "%CV_ROOT%runtime\data\stop_collecteurs.flag" >nul 2>nul
rem Arret du poll des leaders.
if exist "%CV_ROOT%runtime\data\poll_leaders.pid" (
  for /f "usebackq tokens=*" %%P in ("%CV_ROOT%runtime\data\poll_leaders.pid") do taskkill /PID %%P /T /F >nul 2>nul
  del /f /q "%CV_ROOT%runtime\data\poll_leaders.pid" >nul 2>nul
)
taskkill /FI "WINDOWTITLE eq ALINA-POLL-LEADERS*" /T /F >nul 2>nul
rem Liberer le verrou.
if exist "%CV_LOCKFILE%" del /f /q "%CV_LOCKFILE%" >nul 2>nul
echo [OK] Collecteurs arretes proprement. Vous pouvez relancer sans souci.
set "RC=0"
goto :end

:end
echo.
if /I not "%HYPERSMART_PUSH_NO_PAUSE%"=="1" pause
if exist "%CV_LOCKFILE%" del /f /q "%CV_LOCKFILE%" >nul 2>nul
endlocal & exit /b %RC%
