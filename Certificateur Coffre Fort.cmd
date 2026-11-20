@echo off
setlocal enableextensions enabledelayedexpansion
chcp 65001 >nul
title ALINA SMART FLOW - CERTIFIER COFFRE-FORT
set "CV_ROOT=%~dp0"
set "ALINA_LAUNCH_RUN_ID=%DATE%_%TIME%_%RANDOM%_%RANDOM%"
set "ALINA_LAUNCH_MODE=certificate-all"
set "ALINA_LAUNCH_PYTHON=unresolved"

rem --- Resolution de Python ---
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
set "ALINA_LAUNCH_PYTHON=%CV_PYTHON% %CV_PY_ARGS%"
set "ALINA_LAUNCH_OUTPUT_LOG=runtime/coffre_certifie/CERTIF_JOURNAL.jsonl"
set "PYTHONUNBUFFERED=1"
if not defined CV_PYTHON (
  set "ALINA_LAUNCH_PYTHON=unresolved"
  call "%CV_ROOT%tools\launcher_log.cmd" "Certificateur Coffre Fort" EXIT preflight "python-3-not-found" "30"
  echo [NO_GO] Python 3 introuvable. Aucune certification n'a ete lancee.
  endlocal & exit /b 30
)

rem --- Arguments : (defaut) TOUT le projet ; --data = seulement runtime\data ; --reset = remet l affichage a zero ---
rem     RATTRAPAGE (15/11/2026) : par defaut, le certificateur COMPLETE les donnees avant de les
rem     sceller. Scelle-t-on un coffre a moitie rempli alors qu'une requete publique suffisait a
rem     le remplir ? Non : certifier n'est pas qu'un tampon, c'est la garantie que le labo lira
rem     TOUT ce qui etait disponible. --sans-rattrapage retrouve l'ancien comportement.
set "MODE=--tout"
set "RESET="
set "RATTRAPAGE=1"
set "RATTRAPAGE_BUDGET=2400"
set "PLAN_SEUL="
for %%A in (%*) do (
  if /I "%%~A"=="--data" set "MODE="
  if /I "%%~A"=="--reset" set "RESET=--reset-affichage"
  if /I "%%~A"=="--sans-rattrapage" set "RATTRAPAGE="
  if /I "%%~A"=="--rattrapage-long" set "RATTRAPAGE_BUDGET=21600"
  if /I "%%~A"=="--plan" set "PLAN_SEUL=--plan"
  if /I "%%~A"=="--help" goto :help
  if /I "%%~A"=="-h" goto :help
)

echo.
echo === Certification du coffre-fort "donnees certifiees" (tier LOCAL) ===
if defined MODE (echo   Source : TOUT le dossier projet) else (echo   Source : runtime\data uniquement)
if defined RESET echo   Reset affichage : les flux vivants seront remis a zero apres scellage verifie.
if defined RATTRAPAGE (
  echo   Rattrapage : OUI - les donnees sont COMPLETEES avant d'etre scellees ^(budget %RATTRAPAGE_BUDGET% s^)
) else (
  echo   Rattrapage : non ^(--sans-rattrapage^) - on scelle ce qui est deja la
)
echo   PAPER / LECTURE SEULE - les seules requetes sont candleSnapshot et fundingHistory, publics.
echo.
call "%CV_ROOT%tools\launcher_log.cmd" "Certificateur Coffre Fort" START preflight "certification-request" ""

rem Ouvre l'ecran de suivi (%% avancement, debit, ETA) dans une fenetre separee.
rem
rem CV_NO_OPEN : la MEME garde que RAPPORT-COLLECTEURS.cmd applique deja (20/11/2026). Pour
rem un humain cette fenetre est utile ; pour un harnais non interactif elle est nuisible deux
rem fois : elle s ouvre sur le bureau sans que personne l ait demandee, et la console fille
rem HERITE du tuyau de sortie, donc le lecteur du harnais attend un EOF qui tarde. Mesure du
rem jour sur RAPPORT-COLLECTEURS, qui faisait la meme chose avec notepad : la passe est restee
rem bloquee 60 MINUTES. Rien ne change pour l operateur, qui ne definit pas cette variable.
if /I not "%CV_NO_OPEN%"=="1" (
  if exist "%CV_ROOT%SUIVI_COFFRE.cmd" start "" "%CV_ROOT%SUIVI_COFFRE.cmd"
)

rem --- ETAPE 1 : COMPLETER. Une tache a la fois, garde memoire active, une ligne par coin a
rem     l'ecran. L'ordre est calcule (jours-coins gagnes par seconde de requete), pas devine. ---
if defined RATTRAPAGE (
  if exist "%CV_ROOT%tools\rattrapage_complet.py" (
    echo === ETAPE 1/2 : completer les donnees manquantes ===
    "%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\rattrapage_complet.py" --root "%CV_ROOT%." --budget-s %RATTRAPAGE_BUDGET% --sans-scellement %PLAN_SEUL%
    set "RC_RATT=!ERRORLEVEL!"
    call "%CV_ROOT%tools\launcher_log.cmd" "Certificateur Coffre Fort" RESULT rattrapage "rattrapage_complet.py" "!RC_RATT!"
    rem Un rattrapage incomplet n'empeche PAS de certifier : il reprendra au passage suivant, et
    rem sceller ce qui est deja la vaut toujours mieux que de ne rien sceller.
    if not "!RC_RATT!"=="0" echo [AVERTISSEMENT] Rattrapage interrompu ^(code !RC_RATT!^) : on certifie quand meme ce qui est deja la.
    echo.
  ) else (
    echo [AVERTISSEMENT] tools\rattrapage_complet.py introuvable : certification sans rattrapage.
  )
)
if defined PLAN_SEUL (
  echo [--plan] Plan affiche, rien n'a ete lance ni scelle.
  call "%CV_ROOT%tools\launcher_log.cmd" "Certificateur Coffre Fort" EXIT completion "plan-only" "0"
  endlocal & exit /b 0
)

echo === ETAPE 2/2 : certifier et sceller ===
"%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\sceller_coffre_local.py" --root "%CV_ROOT%." %MODE% %RESET%
set "RC=%ERRORLEVEL%"
call "%CV_ROOT%tools\launcher_log.cmd" "Certificateur Coffre Fort" RESULT certification "sceller_coffre_local.py" "%RC%"
echo.
if "%RC%"=="0" (
  echo [OK] Coffre-fort a jour.
  echo   Index   : runtime\coffre_certifie\COFFRE_INDEX.json
  echo   Journal : runtime\coffre_certifie\CERTIF_JOURNAL.jsonl
  echo.
  rem --- ETAPE 3 (18/11/2026) : annoncer le decoupage que le prochain rejeu du labo fera.
  rem     Lu dans l'INDEX du coffre, sans ouvrir un shard (0,4 s). Ne lance PAS le labo :
  rem     un rejeu dure des heures et demande de la memoire ; le plan dit ce qui sera fait.
  rem     N'echoue JAMAIS la certification : un coffre bien scelle ne doit pas etre declare
  rem     en echec parce qu'un affichage a manque.
  echo === PLAN DU PROCHAIN REJEU DU LABO ===
  "%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\conduire_labo_par_tranches.py" "%CV_ROOT%." --depuis-le-coffre --sortie "%CV_ROOT%runtime\reports\plan_tranches.json"
  if errorlevel 1 echo   [INFO] Plan indisponible pour l instant : la certification reste valide.
  call "%CV_ROOT%tools\launcher_log.cmd" "Certificateur Coffre Fort" RESULT plan-tranches "conduire_labo_par_tranches.py" "0"
) else (
  echo [ERREUR] Certification interrompue ^(code %RC%^). Voir le log runtime\logs\coffre_certifie\.
)
call "%CV_ROOT%tools\launcher_log.cmd" "Certificateur Coffre Fort" EXIT completion "certification-finished" "%RC%"
endlocal & exit /b %RC%

:help
call "%CV_ROOT%tools\launcher_log.cmd" "Certificateur Coffre Fort" START help "usage-request" "0"
echo Usage : Certificateur Coffre Fort.cmd [--data] [--reset] [--sans-rattrapage] [--rattrapage-long] [--plan]
echo   (defaut)            COMPLETE les donnees manquantes (40 min max) puis certifie TOUT le projet
echo   --data              limite la certification a runtime\data (collecte courante)
echo   --reset             remet les flux vivants a zero apres un scellage verifie (affichage repart de 0)
echo   --sans-rattrapage   ne complete rien : scelle uniquement ce qui est deja la
echo   --rattrapage-long   6 h de rattrapage au lieu de 40 min (pour creuser la profondeur)
echo   --plan              AFFICHE ce qui manque et ce que ca couterait, puis s'arrete (0 requete)
call "%CV_ROOT%tools\launcher_log.cmd" "Certificateur Coffre Fort" EXIT help "usage-returned" "0"
endlocal & exit /b 0
