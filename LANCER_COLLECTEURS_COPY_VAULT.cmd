@echo off
setlocal EnableExtensions EnableDelayedExpansion
rem 22/11/2026 : ce lanceur n ecrivait plus rien dans runtime\logs\launchers depuis le 12/11 ; on ne
rem   pouvait donc pas savoir si un lancement avait ete tente. Meme journal que LANCER_HYPERSMART.
set "ALINA_LAUNCH_RUN_ID=%DATE%_%TIME%_%RANDOM%_%RANDOM%"
set "ALINA_LAUNCH_MODE=%~1"
if not defined ALINA_LAUNCH_MODE set "ALINA_LAUNCH_MODE=loop"
set "ALINA_LAUNCH_PYTHON=unresolved"
set "ALINA_LAUNCH_OUTPUT_LOG=runtime/logs/supervisor.log"
call "%~dp0tools\launcher_log.cmd" "LANCER_COLLECTEURS_COPY_VAULT" START preflight "launcher-entry" ""
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

rem DEPLACE ICI le 22/11/2026 : `--status` saute a :status AVANT l analyse des arguments,
rem   donc Python n etait pas resolu dans ce chemin. Consequences mesurees en lancant le
rem   vrai lanceur : l etat interne ne s affichait pas (defaut PREEXISTANT) et la detection
rem   a identite verifiee etait sautee, donc l ecran annoncait "ARRETE" par defaut, meme
rem   avec des collecteurs vivants. Resoudre Python d abord repare les deux.
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

if /I "%~1"=="--help" goto :help
if /I "%~1"=="-h" goto :help
if /I "%~1"=="--status" goto :status
if /I "%~1"=="--stop" set "CV_MODE=stop"&shift
if /I "%~1"=="--arreter" set "CV_MODE=stop"&shift
if /I "%~1"=="--once" set "CV_MODE=once"&shift
rem 22/11/2026 : profil allege. 13 collecteurs au lieu de 20 : seuls ceux que CopyVault exige et leurs
rem   soutiens (prix, carnets et contexte des leaders, certification, controle). Les 7 autres servent des
rem   familles desactivees. Usage : LANCER_COLLECTEURS_COPY_VAULT.cmd --copyvault-seul
if /I "%~1"=="--copyvault-seul" set "CV_PROFILE=copy-vault-seul"&shift
if /I "%~1"=="--duration" set "CV_DURATION=%~2"&shift&shift

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
rem PERIME 22/11/2026 -- l ancienne detection testait seulement "ce PID est UN python".
rem   Un PID recycle par n importe quel python (mesure du jour : douze python.exe vivants,
rem   les ouvriers d une suite de tests) faisait croire a une campagne en cours, donc un
rem   refus de demarrer. Et un collecteur dont le .pid avait disparu restait INVISIBLE.
rem   Ancien code, conserve et desactive :
rem     for %%F in (poll_leaders.pid explorer_autonome.pid) do (
rem       tasklist /FI "PID eq %%A" /NH | findstr /I "python" && set "CV_DEJA=1" )
rem   Desormais l identite se lit sur la LIGNE DE COMMANDE : racine du projet + marqueur de
rem   collecteur, avec exclusion de l ecran, du scelleur, de la sync et du labo.
set "CV_DEJA="
set "CV_VIVANTS=0"
if defined CV_PYTHON (
  rem Compteur par FICHIER, pas par backquote : `for /f usebackq` coupait le chemin
  rem   de python.exe au premier espace (mesure du 22/11/2026 : "C:\Users\flo\Desktop\Projet"
  rem   n est pas reconnu), le for echouait et CV_VIVANTS restait 0 -- un faux ARRETE
  rem   obtenu PAR ECHEC, qui ressemblait a une mesure.
  "%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\collecteurs_balayage.py" --racine "%CV_ROOT%." --compter > "%CV_ROOT%runtime\data\.cv_vivants" 2>nul
  if exist "%CV_ROOT%runtime\data\.cv_vivants" set /p CV_VIVANTS=<"%CV_ROOT%runtime\data\.cv_vivants"
  if exist "%CV_ROOT%runtime\data\.cv_vivants" del /f /q "%CV_ROOT%runtime\data\.cv_vivants" >nul 2>nul
  if not defined CV_VIVANTS set "CV_VIVANTS=INCONNU"
)
if not "%CV_VIVANTS%"=="0" set "CV_DEJA=1"
if defined CV_DEJA (
  echo [DEJA EN COURS] Des collecteurs tournent deja sur ce PC.
  echo   Arretez-les d'abord : appuyez sur  q  dans leur ecran, ou relancez avec  --stop.
  goto :fail_lock
)

rem --- Auto-reparation : restes d'un Ctrl+C precedent. CMD ne peut pas
rem     piéger Ctrl+C ; si "Terminate batch job" a coupe sans :cleanup, le
rem     poll a pu rester. On le neutralise AVANT une nouvelle campagne. ---
rem PERIME 22/11/2026 -- DEUX FACONS DE TUER UN INNOCENT, remplacees :
rem   taskkill /PID %%P /T /F    : PID lu dans un .pid, AUCUNE verification. Windows
rem                                RECYCLE les PID ; /T emporte tout l arbre du malheureux.
rem   taskkill /FI "WINDOWTITLE" : un titre de fenetre n appartient a personne.
rem   Ancien code, conserve et desactive :
rem     for /f %%P in (poll_leaders.pid) do taskkill /PID %%P /T /F
rem     taskkill /FI "WINDOWTITLE eq ALINA-POLL-LEADERS*" /T /F
rem     taskkill /FI "WINDOWTITLE eq ALINA-EXPLORER-AUTO*" /T /F
rem     taskkill /FI "WINDOWTITLE eq ALINA-ASSET-CTX*" /T /F
rem     taskkill /FI "WINDOWTITLE eq ALINA-SUPERVISOR*" /T /F
rem   Desormais : identite verifiee (racine + marqueur + exclusions), les PID des .pid sont
rem   VERIFIES eux aussi, et tout refus est motive et affiche. Un arret qui ECHOUE empeche
rem   de demarrer : croire avoir arrete un collecteur encore vivant, c est lancer une
rem   seconde campagne par-dessus la premiere.
if defined CV_PYTHON (
  "%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\collecteurs_balayage.py" --racine "%CV_ROOT%." --arreter --pid-de "%CV_ROOT%runtime\data\poll_leaders.pid" --pid-de "%CV_ROOT%runtime\data\explorer_autonome.pid"
  if errorlevel 3 (
    echo [ARRET INCOMPLET] Un collecteur n a PAS pu etre arrete : on ne demarre pas une
    echo    seconde campagne par-dessus. Relancez avec --stop ou verifiez les droits.
    goto :fail_lock
  )
)
if exist "%CV_ROOT%runtime\data\poll_leaders.pid" del /f /q "%CV_ROOT%runtime\data\poll_leaders.pid" >nul 2>nul
if exist "%CV_ROOT%runtime\data\explorer_autonome.pid" del /f /q "%CV_ROOT%runtime\data\explorer_autonome.pid" >nul 2>nul
if exist "%CV_ROOT%runtime\data\stop_collecteurs.flag" del /f /q "%CV_ROOT%runtime\data\stop_collecteurs.flag" >nul 2>nul
if exist "%CV_ROOT%runtime\data\.session_nettoyee" del /f /q "%CV_ROOT%runtime\data\.session_nettoyee" >nul 2>nul

rem --- Ecrire le verrou : une IDENTITE (PID + commande + instant), pas un hasard ---
rem PERIME 22/11/2026 : `echo %RANDOM%%RANDOM%` ecrivait un nombre ALEATOIRE sous un
rem   commentaire annoncant "PID du cmd courant". Le code contredisait son commentaire, et
rem   personne ne pouvait savoir qui detenait le verrou -- donc ni le valider, ni le liberer
rem   en connaissance de cause. Verifie sur la machine le 22/11 : le verrou reel portait
rem   encore ce format, et le nouveau lecteur l annonce FORMAT_ANCIEN_OU_ILLISIBLE au lieu
rem   de le lire comme un PID. Ancien code conserve, desactive :
rem     echo %RANDOM%%RANDOM%> "%CV_LOCKFILE%"
if defined CV_PYTHON (
  "%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\ecrire_verrou_collecteurs.py" --verrou "%CV_LOCKFILE%" --commande "LANCER_COLLECTEURS_COPY_VAULT.cmd" >nul 2>nul
)
rem Repli : si Python manque, un verrou vaut mieux que pas de verrou -- mais il sera annonce
rem comme illisible, ce qui est la verite.
if not exist "%CV_LOCKFILE%" echo %RANDOM%%RANDOM%> "%CV_LOCKFILE%"

rem --- SESSION FRAICHE : on NE certifie PAS au lancement (c'est LENT et c'est le role
rem     du certificateur A L'ARRET, sur les donnees de la session). On se contente
rem     d'ARCHIVER l'eventuel reste d'une session precedente (RAPIDE : deplace juste les
rem     tapes) pour repartir a ZERO sans rien perdre. La certification -> coffre a lieu
rem     a l'arret (touche q), sur la session courante. ---
if exist "%CV_ROOT%tools\archiver_tapes.py" (
  if not exist "%CV_ROOT%runtime\logs\coffre_certifie" mkdir "%CV_ROOT%runtime\logs\coffre_certifie" >nul 2>nul
  rem Reste d une session interrompue : il passe D ABORD par le certificateur ; sinon l archiveur
  rem le laisse en place. Rapide quand il n y a rien de nouveau. Rien n echappe au coffre.
  rem 22/11/2026 : cette etape etait MUETTE. Apres la ligne [ARRET] l ecran restait vide une a deux
  rem minutes et le lanceur paraissait bloque. On l annonce AVANT de la lancer.
  echo [COFFRE] Mise au coffre du reste d'une session precedente ^(1 a 2 minutes, ecran immobile = normal^)...
  if exist "%CV_ROOT%tools\sceller_coffre_local.py" "%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\sceller_coffre_local.py" --root "%CV_ROOT%." >> "%CV_ROOT%runtime\logs\coffre_session.log" 2>&1
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
if /I "%CV_PROFILE%"=="copy-vault-seul" (echo   13 collecteurs actifs ^(profil %CV_PROFILE% : CopyVault et ses soutiens^)) else (echo   20 collecteurs actifs ^(profil %CV_PROFILE%^))
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
rem --- Carnets L2 des coins trades par les leaders, dex HIP-3 compris : liste locale regeneree
rem     depuis les besoins mesures par le labo, chaque nom verifie aupres de l'univers officiel
rem     (un nom inconnu ferait fermer la connexion). Lue par le collecteur l2-leaders. Fail-soft.
if exist "%CV_ROOT%tools\generer_coins_lanes.py" (
  "%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\generer_coins_lanes.py" --root "%CV_ROOT%." 2>nul
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
rem PERIME 22/11/2026 -- MEME DEFAUT, DEUXIEME COPIE. L ecran `:status` affichait
rem   "EN COURS" ou "ARRETE" avec la logique "ce PID est UN python" : il pouvait donc
rem   mentir dans les deux sens, alors que son seul role est de dire l etat REEL.
rem   Ancien code conserve, desactive :
rem     for %%F in (poll_leaders.pid explorer_autonome.pid) do (
rem       tasklist /FI "PID eq %%A" /NH | findstr /I "python" && set "CV_DEJA=1" )
set "CV_DEJA="
set "CV_VIVANTS=0"
if defined CV_PYTHON (
  rem Compteur par FICHIER, pas par backquote : `for /f usebackq` coupait le chemin
  rem   de python.exe au premier espace (mesure du 22/11/2026 : "C:\Users\flo\Desktop\Projet"
  rem   n est pas reconnu), le for echouait et CV_VIVANTS restait 0 -- un faux ARRETE
  rem   obtenu PAR ECHEC, qui ressemblait a une mesure.
  "%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\collecteurs_balayage.py" --racine "%CV_ROOT%." --compter > "%CV_ROOT%runtime\data\.cv_vivants" 2>nul
  if exist "%CV_ROOT%runtime\data\.cv_vivants" set /p CV_VIVANTS=<"%CV_ROOT%runtime\data\.cv_vivants"
  if exist "%CV_ROOT%runtime\data\.cv_vivants" del /f /q "%CV_ROOT%runtime\data\.cv_vivants" >nul 2>nul
  if not defined CV_VIVANTS set "CV_VIVANTS=INCONNU"
  echo   Collecteurs identifies par leur ligne de commande : %CV_VIVANTS%
  "%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\collecteurs_balayage.py" --racine "%CV_ROOT%." --lister --verrou "%CV_LOCKFILE%" 2>nul
)
if not "%CV_VIVANTS%"=="0" set "CV_DEJA=1"
if defined CV_DEJA (
  echo Statut : EN COURS ^(collecteurs vivants^)
) else (
  echo Statut : ARRETE
)
echo.
if exist "%CV_ROOT%runtime\data\economic_collection_pids.json" (
  echo --- Etat interne (economic_collection_pids.json^) ---
rem PERIME 22/11/2026 : cette ligne lisait `d.get('lease_valid')`, une clef ABSENTE de ce
rem   schema (elle appartient a `bounded_collection`). L ecran affichait donc
rem   `Lease valide: ?` POUR TOUJOURS, alors que le bail etait expire depuis 10,2 h : le
rem   bail vit ici sous `lease.expires_at_ms`. Et le fichier listait 20 workers quand 0
rem   etait vivant. Remplacee par l etat REEL a quatre niveaux (processus vivant !=
rem   collecte fonctionnelle != donnees fraiches != certifiables). Ancienne ligne gardee :
rem "%CV_PYTHON%" %CV_PY_ARGS% -c "import json,sys; d=json.loads(open(sys.argv[1],'r',encoding='utf-8').read()); print('  Lease valide:',d.get('lease_vali
  "%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\etat_collecte_reel.py" --racine "%CV_ROOT%." 2>nul
rem --- AVANCEMENT DU RATTRAPAGE : cable le 22/11/2026 apres mesure `prod=0`.
rem     `tools/avancement_rattrapage.py` existait, teste, et n etait appele par PERSONNE.
rem     Or la passe de rattrapage etait MUETTE : zero octet de sortie en une heure (verifie
rem     le 15/11), son resume n arrivant qu APRES epuisement du budget, jusqu a 8 h plus
rem     tard. Un rattrapage silencieux est indistinguable d un rattrapage MORT, et sans le
rem     voir on ne peut decider ni d attendre ni de relancer. LECTURE SEULE : il ne lance
rem     aucune passe. ---
if exist "%CV_ROOT%tools\avancement_rattrapage.py" (
  echo.
  "%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\avancement_rattrapage.py" --root "%CV_ROOT%." 2>nul
)
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
echo Collecteurs lances (profil copy-vault / harvest, 15 collecteurs) :
echo   CORE     : allmids-collector, bbo-collector, userfills-live
echo   DONNEES  : carnet-collector, venues-collector, marks-collector
echo   ANALYSE  : liq-collector, overshoot-collector, vault-collector, scorer-vaults
echo              (vault-collector : positions + courbes valeur/PnL, univers elargi vaults fermes compris)
echo   BACKFILL : backfill-fills, backfill-candles-vaults
echo   CAUSAL   : copy-vault-checkpoints (L2 lie aux fills leaders)
echo   ENRICHI  : native-venues, lab-microstructure
echo   CARNETS  : l2-leaders (L2 + BBO continus des coins trades par les leaders, dex HIP-3 compris)
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
rem --- Arret a IDENTITE VERIFIEE : racine du projet + marqueur de collecteur,
rem     exclusions (ecran, scelleur, sync, labo), PID des .pid VERIFIES eux aussi,
rem     et tout refus est motive et affiche. Remplace les taskkill ci-dessous. ---
if defined CV_PYTHON (
  "%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\collecteurs_balayage.py" --racine "%CV_ROOT%." --arreter --pid-de "%CV_ROOT%runtime\data\poll_leaders.pid" --pid-de "%CV_ROOT%runtime\data\explorer_autonome.pid"
)
rem PERIME 22/11/2026 (PID recycle / titre de fenetre) : taskkill /FI "WINDOWTITLE eq ALINA-SUPERVISOR*" /T /F >nul 2>nul
rem --- Arreter l'explorer autonome ---
if exist "%CV_ROOT%runtime\data\explorer_autonome.pid" (
rem PERIME 22/11/2026 (PID recycle / titre de fenetre) : for /f "usebackq tokens=*" %%P in ("%CV_ROOT%runtime\data\explorer_autonome.pid") do taskkill /PID %%P /T /F >nul 2>nul
  del /f /q "%CV_ROOT%runtime\data\explorer_autonome.pid" >nul 2>nul
)
rem PERIME 22/11/2026 (PID recycle / titre de fenetre) : taskkill /FI "WINDOWTITLE eq ALINA-EXPLORER-AUTO*" /T /F >nul 2>nul
rem PERIME 22/11/2026 (PID recycle / titre de fenetre) : taskkill /FI "WINDOWTITLE eq ALINA-ASSET-CTX*" /T /F >nul 2>nul
rem --- Arreter le poll des leaders (fenetre dediee) ---
if exist "%CV_ROOT%runtime\data\poll_leaders.pid" (
rem PERIME 22/11/2026 (PID recycle / titre de fenetre) : for /f "usebackq tokens=*" %%P in ("%CV_ROOT%runtime\data\poll_leaders.pid") do taskkill /PID %%P /T /F >nul 2>nul
  del /f /q "%CV_ROOT%runtime\data\poll_leaders.pid" >nul 2>nul
)
rem PERIME 22/11/2026 (PID recycle / titre de fenetre) : taskkill /FI "WINDOWTITLE eq ALINA-POLL-LEADERS*" /T /F >nul 2>nul

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
rem --- Arret a IDENTITE VERIFIEE : racine du projet + marqueur de collecteur,
rem     exclusions (ecran, scelleur, sync, labo), PID des .pid VERIFIES eux aussi,
rem     et tout refus est motive et affiche. Remplace les taskkill ci-dessous. ---
if defined CV_PYTHON (
  "%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\collecteurs_balayage.py" --racine "%CV_ROOT%." --arreter --pid-de "%CV_ROOT%runtime\data\poll_leaders.pid" --pid-de "%CV_ROOT%runtime\data\explorer_autonome.pid"
)
rem PERIME 22/11/2026 (PID recycle / titre de fenetre) : taskkill /FI "WINDOWTITLE eq ALINA-SUPERVISOR*" /T /F >nul 2>nul
rem Arret de l'explorer autonome.
if exist "%CV_ROOT%runtime\data\explorer_autonome.pid" (
rem PERIME 22/11/2026 (PID recycle / titre de fenetre) : for /f "usebackq tokens=*" %%P in ("%CV_ROOT%runtime\data\explorer_autonome.pid") do taskkill /PID %%P /T /F >nul 2>nul
  del /f /q "%CV_ROOT%runtime\data\explorer_autonome.pid" >nul 2>nul
)
rem PERIME 22/11/2026 (PID recycle / titre de fenetre) : taskkill /FI "WINDOWTITLE eq ALINA-EXPLORER-AUTO*" /T /F >nul 2>nul
rem PERIME 22/11/2026 (PID recycle / titre de fenetre) : taskkill /FI "WINDOWTITLE eq ALINA-ASSET-CTX*" /T /F >nul 2>nul
del /f /q "%CV_ROOT%runtime\data\stop_collecteurs.flag" >nul 2>nul
rem Arret du poll des leaders.
if exist "%CV_ROOT%runtime\data\poll_leaders.pid" (
rem PERIME 22/11/2026 (PID recycle / titre de fenetre) : for /f "usebackq tokens=*" %%P in ("%CV_ROOT%runtime\data\poll_leaders.pid") do taskkill /PID %%P /T /F >nul 2>nul
  del /f /q "%CV_ROOT%runtime\data\poll_leaders.pid" >nul 2>nul
)
rem PERIME 22/11/2026 (PID recycle / titre de fenetre) : taskkill /FI "WINDOWTITLE eq ALINA-POLL-LEADERS*" /T /F >nul 2>nul
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
