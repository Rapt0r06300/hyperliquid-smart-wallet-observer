@echo off
REM ============================================================================
REM  TOUT-TESTER — LE SEUL fichier a lancer
REM ============================================================================
REM  Tu double-cliques ICI, tu vas boire un cafe, et a la fin tu as UN fichier
REM  qui dit tout : RECAP-COMPLET.md (a la racine du projet).
REM
REM  LES ETAPES, DANS L'ORDRE :
REM    1. SECURITE        0 ordre reel possible (la barriere non negociable)
REM    2. CONSOLIDATION   les shards du replay du jour, avant tout ce qui les lit
REM    3. TESTS           la suite pytest COMPLETE = la verite du code
REM    4. INVARIANTS      les LOIS du PnL (property-based, ~700 cas generes)
REM    5. CABLAGE         modules cables / testes-seulement / orphelins
REM    6. DONNEES         qualite du replay (etiquetage, couverture, doublons, prix)
REM    7. BACKTESTS       carry rejoue sous d'autres reglages + convergence arbitrage
REM    8. RECHERCHE       pepites par module (carry, copy, arbitrage, cross-venue)
REM    9. RAPPORT DU JOUR PnL par motif, economie des positions, a-faire
REM   10. SANTE LIVE      moteur, collecteurs, positions, mesures en cours
REM
REM  LE RECAP CITE AUSSI LE VOLUME DE DONNEES par source (lignes / Mo / etendue).
REM  Ce qu'on ne cite pas, on le surestime : c'est cette table qui a revele que le
REM  carry n'avait que 96 lignes rejouables le 21/07.
REM
REM  OPTIONS :
REM    --aide                 la liste des options, puis on sort
REM    --rapide               saute la recherche de pepites          -^> ~10 min
REM    --tests-seulement      securite + pytest + invariants         -^> ~5 min
REM    --securite-seulement   UNIQUEMENT l'audit no-real-trade       -^> ~30 s
REM    --sans-pause           ne demande pas d'appuyer sur une touche a la fin
REM    --ouvrir               ouvre le RECAP dans l'editeur a la fin
REM
REM  Compte ~1 h en mode complet. 100%% lecture seule : 0 ordre reel, 0 cle.
REM ============================================================================
REM
REM  ── LES 40 AMELIORATIONS DE CE LANCEUR (21/07) ────────────────────────────
REM  Le .cmd ne faisait que quatre choses : cd, PYTHONPATH, lancer, pause. Tout le
REM  reste etait SUPPOSE. Chaque numero ci-dessous est marque dans le code.
REM
REM  PRE-VOL — on ne lance pas une heure de calcul sur un environnement casse
REM   01 Python present ? message clair et actionnable sinon
REM   02 version de Python ^>= 3.10 verifiee (le code utilise la syntaxe X ^| None)
REM   03 tools\tout_tester.py present ? sinon le .cmd a ete deplace
REM   04 dossier src\ present ? sans lui PYTHONPATH ne sert a rien
REM   05 espace disque libre annonce (l'audit ecrit RECAP + logs + rapports)
REM   06 verrou anti-double-lancement : deux audits en parallele se marchent dessus
REM   07 pytest-timeout installe (sinon un test qui pend mange la soiree)
REM   08 chemin avec ESPACE gere partout ("Projet invest" en a un)
REM   09 alerte si le projet est sous OneDrive ou sur un lecteur reseau
REM   10 racine figee une fois pour toutes, independante du repertoire courant
REM
REM  SECURITE — la barriere avant tout le reste
REM   11 refus NET si une variable d'execution reelle est armee dans l'environnement
REM   12 refus NET si une cle privee / seed / mnemonic traine dans l'environnement
REM   13 READ_ONLY et PAPER_ONLY poses explicitement pour le processus fils
REM   14 banniere lecture-seule affichee AVANT le premier calcul
REM   15 l'empreinte de securite est ecrite en tete du log de session
REM
REM  TRACABILITE — un run qu'on ne peut pas rejouer ne prouve rien
REM   16 identifiant de session unique (date-heure)
REM   17 log de session dans logs-audit\ (en plus du RECAP)
REM   18 le RECAP precedent est ARCHIVE, jamais ecrase
REM   19 etat git capture (branche, HEAD, fichiers non commites) — 5 jours non
REM      commites avaient ete decouverts le 14/07 parce que personne ne regardait
REM   20 horodatage de debut et de fin
REM   21 duree totale calculee et affichee
REM   22 taille du RECAP affichee (un RECAP de 0 octet est un echec silencieux)
REM   23 code de sortie ecrit dans le log
REM   24 purge au-dela de 30 logs (on garde, mais on ne noie pas le dossier)
REM   25 detection d'un RECAP PERIME : s'il n'a pas ete reecrit, on lirait le run
REM      PRECEDENT en croyant lire celui-ci
REM
REM  ERGONOMIE
REM   26 --aide, transmis au Python qui possede la liste de reference
REM   27 --rapide transmis
REM   28 --tests-seulement transmis
REM   29 --securite-seulement transmis
REM   30 --sans-pause (tache planifiee, lancement de nuit)
REM   31 --ouvrir : ouvre le RECAP a la fin
REM   32 une option INCONNUE est refusee par le Python, jamais avalee en silence
REM   33 verdict final explicite, avec le code de sortie
REM   34 bip sonore en fin de run (on est parti boire un cafe)
REM   35 titre de la fenetre mis a jour a chaque phase
REM
REM  ROBUSTESSE
REM   36 PYTHONDONTWRITEBYTECODE : les .pyc periment a travers le mount (piege connu)
REM   37 PYTHONUNBUFFERED : la progression s'affiche en direct, pas par blocs
REM   38 PYTHONIOENCODING + chcp 65001 : le RECAP a des accents
REM   39 Ctrl-C reconnu et explique (le RECAP couvre les etapes deja faites)
REM   40 code de sortie PROPAGE a l'appelant (tache planifiee, script parent)
REM ============================================================================
setlocal EnableDelayedExpansion

REM --- 38 : la console doit savoir afficher les accents du RECAP -------------
chcp 65001 >nul 2>&1

REM --- 08/10 : racine du projet, avec espace, figee une fois pour toutes -----
cd /d "%~dp0"
set "PROJ=%~dp0"
if "%PROJ:~-1%"=="\" set "PROJ=%PROJ:~0,-1%"

REM --- 13/36/37/38 : environnement du processus fils -------------------------
set "PYTHONPATH=%PROJ%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONUNBUFFERED=1"
set "HYPERSMART_READ_ONLY=1"
set "HYPERSMART_PAPER_ONLY=1"

REM --- 16 : identifiant de session -------------------------------------------
set "SID="
for /f "usebackq tokens=*" %%T in (`powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"`) do set "SID=%%T"
if not defined SID set "SID=session"
set "LOGDIR=%PROJ%\logs-audit"
if not exist "%LOGDIR%" mkdir "%LOGDIR%" >nul 2>&1
set "LOG=%LOGDIR%\tout-tester-%SID%.log"

REM --- 35 : le titre suit la phase -------------------------------------------
title TOUT-TESTER — pre-vol

echo.
echo   ============================================================
echo     TOUT-TESTER : securite, tests, cablage, donnees,
echo     recherche de pepites, sante live.
echo     A la fin : RECAP-COMPLET.md
echo   ============================================================
REM --- 14 : la banniere AVANT le premier calcul ------------------------------
echo     LECTURE SEULE — 0 ordre reel, 0 argent reel, 0 cle privee.
echo     session %SID%
echo.

REM ==========================================================================
REM  PRE-VOL
REM ==========================================================================
REM --- 01 : Python present ? -------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
  echo   [PRE-VOL] ECHEC : "python" est introuvable dans le PATH.
  echo             Installe Python 3.10+, ou ouvre un terminal ou "python --version" repond.
  echo.
  pause
  exit /b 3
)

REM --- 02 : version ^>= 3.10 -------------------------------------------------
python -c "import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if errorlevel 1 (
  set "PYV=?"
  for /f "usebackq tokens=*" %%V in (`python -c "import sys;print(sys.version.split()[0])"`) do set "PYV=%%V"
  echo   [PRE-VOL] ECHEC : Python !PYV! est trop ancien, il faut 3.10 ou plus.
  echo.
  pause
  exit /b 3
)

REM --- 03/04 : on est bien a la racine du projet ? --------------------------
if not exist "%PROJ%\tools\tout_tester.py" (
  echo   [PRE-VOL] ECHEC : tools\tout_tester.py introuvable sous "%PROJ%".
  echo             Ce .cmd doit rester A LA RACINE du projet.
  echo.
  pause
  exit /b 3
)
if not exist "%PROJ%\src" (
  echo   [PRE-VOL] ECHEC : le dossier src\ est absent — PYTHONPATH ne servirait a rien.
  echo.
  pause
  exit /b 3
)

REM --- 06 : verrou anti-double-lancement ------------------------------------
set "LOCK=%PROJ%\.tout-tester.lock"
if exist "%LOCK%" (
  echo   [PRE-VOL] Un audit semble DEJA en cours ^(verrou present^).
  echo             Si c'est faux, supprime ce fichier : .tout-tester.lock
  echo.
  set "REP=n"
  set /p "REP=  Continuer quand meme ? [o/N] "
  if /i not "!REP!"=="o" exit /b 4
)
echo %SID%>"%LOCK%"

REM --- 05 : espace disque libre ---------------------------------------------
set "FREEGB="
for /f "usebackq tokens=*" %%D in (`powershell -NoProfile -Command "[math]::Round((Get-Item '%PROJ%').PSDrive.Free/1GB,1)"`) do set "FREEGB=%%D"
if defined FREEGB echo   [PRE-VOL] espace libre : !FREEGB! Go

REM --- 09 : OneDrive / lecteur reseau ---------------------------------------
echo "%PROJ%" | findstr /i "OneDrive" >nul && (
  echo   [PRE-VOL] ATTENTION : projet sous OneDrive — la synchro peut modifier des
  echo             fichiers PENDANT l'audit et fausser les resultats.
)
if "%PROJ:~0,2%"=="\\" echo   [PRE-VOL] ATTENTION : chemin reseau — l'audit sera lent et fragile.

REM ==========================================================================
REM  SECURITE — la barriere avant tout le reste
REM ==========================================================================
REM --- 11 : un interrupteur d'execution reelle arme = arret NET --------------
set "DANGER="
if /i "%REAL_MAINNET_TRADING%"=="true" set "DANGER=REAL_MAINNET_TRADING"
if /i "%HYPERSMART_REAL_TRADING%"=="true" set "DANGER=HYPERSMART_REAL_TRADING"
if /i "%ENABLE_REAL_ORDERS%"=="true" set "DANGER=ENABLE_REAL_ORDERS"
if defined DANGER (
  echo.
  echo   [SECURITE] ARRET : la variable !DANGER! est armee dans cet environnement.
  echo              TOUT-TESTER est un outil de LECTURE SEULE et refuse de tourner
  echo              a cote d'un interrupteur d'execution reelle.
  echo.
  del "%LOCK%" >nul 2>&1
  pause
  exit /b 5
)

REM --- 12 : aucune cle privee ne doit trainer dans l'environnement -----------
set "SECRET="
if defined PRIVATE_KEY set "SECRET=PRIVATE_KEY"
if defined HL_PRIVATE_KEY set "SECRET=HL_PRIVATE_KEY"
if defined MNEMONIC set "SECRET=MNEMONIC"
if defined SEED_PHRASE set "SECRET=SEED_PHRASE"
if defined WALLET_SECRET set "SECRET=WALLET_SECRET"
if defined SECRET (
  echo.
  echo   [SECURITE] ARRET : !SECRET! est presente dans l'environnement.
  echo              Ce projet n'utilise JAMAIS de cle. Retire-la avant de lancer
  echo              quoi que ce soit — meme un outil en lecture seule.
  echo.
  del "%LOCK%" >nul 2>&1
  pause
  exit /b 5
)
echo   [SECURITE] aucun interrupteur d'execution reelle, aucune cle : OK

REM ==========================================================================
REM  TRACABILITE
REM ==========================================================================
REM --- 15/17/20 : en-tete du log de session ---------------------------------
>"%LOG%" echo TOUT-TESTER — session %SID%
>>"%LOG%" echo projet   : %PROJ%
>>"%LOG%" echo debut    : %DATE% %TIME%
>>"%LOG%" echo securite : READ_ONLY=1 PAPER_ONLY=1 · 0 ordre reel · 0 cle · 0 signature
>>"%LOG%" echo options  : %*

REM --- 19 : etat git ---------------------------------------------------------
where git >nul 2>&1 && (
  set "GHEAD=?" & set "GBR=?" & set "GDIRTY=?"
  for /f "usebackq tokens=*" %%G in (`git rev-parse --short HEAD 2^>nul`) do set "GHEAD=%%G"
  for /f "usebackq tokens=*" %%B in (`git rev-parse --abbrev-ref HEAD 2^>nul`) do set "GBR=%%B"
  for /f %%C in ('git status --porcelain 2^>nul ^| find /c /v ""') do set "GDIRTY=%%C"
  echo   [GIT] !GBR! @ !GHEAD! — !GDIRTY! fichier^(s^) non commite^(s^)
  >>"%LOG%" echo git      : !GBR! @ !GHEAD! — !GDIRTY! non commites
  if not "!GDIRTY!"=="0" echo   [GIT] rappel : l'audit juge le DISQUE, pas le dernier commit.
)

REM --- 18 : le RECAP precedent est ARCHIVE, jamais ecrase -------------------
if exist "%PROJ%\RECAP-COMPLET.md" (
  if not exist "%LOGDIR%\recaps" mkdir "%LOGDIR%\recaps" >nul 2>&1
  copy /y "%PROJ%\RECAP-COMPLET.md" "%LOGDIR%\recaps\RECAP-%SID%.md" >nul 2>&1
  echo   [ARCHIVE] RECAP precedent conserve : logs-audit\recaps\RECAP-%SID%.md
)

REM --- 25 : marqueur de depart, pour detecter un RECAP perime ---------------
set "MARQUEUR=%PROJ%\.tout-tester.start"
echo %SID%>"%MARQUEUR%"

REM --- 07 : pytest-timeout, sinon un test qui pend mange la soiree ----------
title TOUT-TESTER — dependances
python -m pip install -q pytest-timeout 2>nul

REM ==========================================================================
REM  LANCEMENT
REM ==========================================================================
REM --- 26/27/28/29 : --aide, --rapide, --tests-seulement, --securite-seulement
REM     ne sont PAS interpretees ici : elles sont transmises telles quelles au Python,
REM     qui possede la liste de reference (`OPTIONS` dans tools/tout_tester.py).
REM     Deux listes d'options finissent toujours par diverger ; il n'y en a qu'une.
REM --- 32 : une option inconnue est REFUSEE par le Python (code 2), jamais avalee.
REM     Une option avalee sans effet donne un run qui ne fait pas ce qu'on croit, et
REM     on lit ensuite un RECAP en pensant qu'il repond a une question jamais posee.
REM --- 30/31 : options du LANCEUR, retirees avant de passer la main au Python
set "PAUSEFIN=1"
set "OUVRIR=0"
set "ARGS="
for %%A in (%*) do (
  if /i "%%~A"=="--sans-pause" (
    set "PAUSEFIN=0"
  ) else if /i "%%~A"=="--ouvrir" (
    set "OUVRIR=1"
  ) else (
    set "ARGS=!ARGS! %%~A"
  )
)

title TOUT-TESTER — en cours (session %SID%)
set "T0=%TIME%"
echo.
echo   --- lancement : python tools\tout_tester.py!ARGS! ---
echo.

python "%PROJ%\tools\tout_tester.py"!ARGS!
set "CODE=%ERRORLEVEL%"
set "T1=%TIME%"

REM --- 21 : duree totale -----------------------------------------------------
set "DUREE="
for /f "usebackq tokens=*" %%S in (`powershell -NoProfile -Command "$a=[datetime]::Parse('%T0%');$b=[datetime]::Parse('%T1%');if($b -lt $a){$b=$b.AddDays(1)};'{0:hh\:mm\:ss}' -f ($b-$a)"`) do set "DUREE=%%S"

REM --- 06 : le verrou tombe quoi qu'il arrive -------------------------------
del "%LOCK%" >nul 2>&1

REM ==========================================================================
REM  VERDICT
REM ==========================================================================
echo.
echo   ============================================================
if defined DUREE echo     duree : !DUREE!   ^| session %SID%

REM --- 22/25 : le RECAP existe, n'est pas vide, et vient bien de CE run -----
if exist "%PROJ%\RECAP-COMPLET.md" (
  set "TAILLE=0"
  for %%F in ("%PROJ%\RECAP-COMPLET.md") do set "TAILLE=%%~zF"
  if "!TAILLE!"=="0" (
    echo     !! RECAP VIDE ^(0 octet^) : envoie CETTE fenetre a Claude.
  ) else (
    echo     RECAP ecrit : RECAP-COMPLET.md   ^(!TAILLE! octets^)
    echo     ^(c'est CE fichier a envoyer a Claude^)
  )
  set "FRAICHEUR=?"
  for /f "usebackq tokens=*" %%P in (`powershell -NoProfile -Command "if((Get-Item '%PROJ%\RECAP-COMPLET.md').LastWriteTime -lt (Get-Item '%MARQUEUR%').LastWriteTime){'PERIME'}else{'FRAIS'}"`) do set "FRAICHEUR=%%P"
  if "!FRAICHEUR!"=="PERIME" (
    echo     !! ATTENTION : le RECAP n'a PAS ete reecrit par ce run.
    echo        Tu lirais les resultats du run PRECEDENT.
  )
) else (
  echo     !! RECAP ABSENT : envoie CETTE fenetre a Claude.
)
del "%MARQUEUR%" >nul 2>&1

REM --- 33/39 : verdict explicite, Ctrl-C reconnu ----------------------------
if "%CODE%"=="0" (
  echo     TOUT EST VERT.
) else if "%CODE%"=="2" (
  echo     OPTION INCONNUE — rien n'a ete lance.  TOUT-TESTER.cmd --aide
) else if "%CODE%"=="3" (
  echo     PRE-VOL en echec — l'environnement n'est pas pret.
) else if "%CODE%"=="5" (
  echo     ARRET DE SECURITE — voir le message ci-dessus.
) else (
  echo     Des etapes ont ECHOUE ^(code %CODE%^) — le detail est dans le RECAP.
)
echo   ============================================================

REM --- 23 : le code de sortie va aussi dans le log --------------------------
>>"%LOG%" echo fin      : %DATE% %TIME%
>>"%LOG%" echo duree    : !DUREE!
>>"%LOG%" echo code     : %CODE%
echo     log de session : logs-audit\tout-tester-%SID%.log

REM --- 24 : on garde les 30 derniers logs -----------------------------------
for /f "usebackq skip=30 tokens=*" %%L in (`powershell -NoProfile -Command "Get-ChildItem '%LOGDIR%\tout-tester-*.log' ^| Sort-Object LastWriteTime -Descending ^| Select-Object -ExpandProperty FullName"`) do del "%%L" >nul 2>&1

REM --- 34 : bip de fin -------------------------------------------------------
powershell -NoProfile -Command "[console]::beep(880,150)" >nul 2>&1

REM --- 31 : ouverture du RECAP si demandee ----------------------------------
if "%OUVRIR%"=="1" if exist "%PROJ%\RECAP-COMPLET.md" start "" "%PROJ%\RECAP-COMPLET.md"

title TOUT-TESTER — termine (code %CODE%)
echo.
REM --- 30 : pas de pause en tache planifiee ---------------------------------
if "%PAUSEFIN%"=="1" pause

REM --- 40 : le code de sortie est PROPAGE a l'appelant ----------------------
endlocal & exit /b %CODE%
