@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONPATH=%~dp0src;%~dp0;%~dp0tools"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
set "REAL_MAINNET_TRADING=false"
set "TESTNET_ONLY=true"
set "ALINA_QUANT_CPU_PERCENT=60"
rem Plafond mesure: 4 workers max evite la contention disque/import sous Windows.
set "ALINA_QUANT_MAX_WORKERS=4"
rem Audit SAFE: 4 lectures SHA-256 exactes en parallele, sans reutiliser de cache metadata.
set "ALINA_QUANT_HASH_WORKERS=4"

set "ALINA_LAB_MODE=%~1"
if not defined ALINA_LAB_MODE set "ALINA_LAB_MODE=safe"
set "ALINA_LAUNCH_RUN_ID=%DATE%_%TIME%_%RANDOM%_%RANDOM%"
set "ALINA_LAUNCH_MODE=%ALINA_LAB_MODE%"
set "ALINA_LAUNCH_PYTHON=unresolved"
set "ALINA_LAUNCH_OUTPUT_LOG=runtime/logs/launchers/LANCER_LAB_QUANT_COPY_VAULT.log"
call "%~dp0tools\launcher_log.cmd" "LANCER_LAB_QUANT_COPY_VAULT" START preflight "mode-selected" ""
echo.
echo ================================================================
echo   ALINA SMART FLOW - COPY-VAULT LAB
echo   Double clic : shards SAFE locaux, replays/backtests en continu
echo   Arret propre : CTRL+C dans cette fenetre
echo   Modes : safe (continu) / once (un passage) / copiabilite / tests / preflight / research / legacy
echo   copiabilite : que reste-t-il au copieur apres observation et couts ? [coffre LOCAL, exploratoire]
echo   PAPER / READ-ONLY - aucun ordre, aucune collecte
echo ================================================================
echo.

set "ALINA_LAB_PYTHON="
set "ALINA_LAB_PY_ARGS="
if exist "%~dp0tools\python\python.exe" set "ALINA_LAB_PYTHON=%~dp0tools\python\python.exe"
if not defined ALINA_LAB_PYTHON if exist "%~dp0.venv\Scripts\python.exe" set "ALINA_LAB_PYTHON=%~dp0.venv\Scripts\python.exe"
if not defined ALINA_LAB_PYTHON (
  where py >nul 2>nul
  if not errorlevel 1 (
    set "ALINA_LAB_PYTHON=py"
    set "ALINA_LAB_PY_ARGS=-3"
  )
)
if defined ALINA_LAB_PYTHON set "ALINA_LAUNCH_PYTHON=%ALINA_LAB_PYTHON% %ALINA_LAB_PY_ARGS%"
if not defined ALINA_LAB_PYTHON (
  echo [ERREUR] Python 3 introuvable; aucun telechargement automatique.
  set "RC=30"
  goto :done
)

call "%~dp0tools\launcher_log.cmd" "LANCER_LAB_QUANT_COPY_VAULT" START mode-dispatch "dispatching-lab-mode" ""

"%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\cmd_progress.py" start > "%TEMP%\alina_cmd_start.tmp" 2>nul
set /p ALINA_CMD_START=<"%TEMP%\alina_cmd_start.tmp"
if /I "%ALINA_LAB_MODE%"=="tests" (
  call "%~dp0tools\launcher_log.cmd" "LANCER_LAB_QUANT_COPY_VAULT" STEP lab-mode "tests; report=tools/alina_quant_lab_console.py" ""
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% -c "import pytest, typer" >nul 2>nul
  if errorlevel 1 (
    echo [ERREUR] Installez les dependances: py -3 -m pip install -e ".[dev]"
    set "RC=31"
    goto :done
  )
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% -c "import xdist" >nul 2>nul
  if errorlevel 1 echo [INFO] xdist absent, tests en serie.
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\alina_quant_lab_console.py"
) else if /I "%ALINA_LAB_MODE%"=="preflight" (
  call "%~dp0tools\launcher_log.cmd" "LANCER_LAB_QUANT_COPY_VAULT" STEP lab-mode "preflight; report=tools/alina_quant_lab_console.py" ""
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\alina_quant_lab_console.py" --preflight-only
) else if /I "%ALINA_LAB_MODE%"=="legacy" (
  call "%~dp0tools\launcher_log.cmd" "LANCER_LAB_QUANT_COPY_VAULT" STEP lab-mode "legacy-local-economic; report=tools/alina_quant_lab_console.py" ""
  rem Preserve the Codex/Claude local economic laboratory as explicit opt-in.
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% -c "import pydantic, pytest, typer" >nul 2>nul
  if errorlevel 1 (
    echo [NO_GO] Installez les dependances du laboratoire local : py -3 -m pip install -e ".[dev]"
    set "RC=31"
    goto :done
  )
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\alina_quant_lab_console.py" --legacy-local-economic
) else if /I "%ALINA_LAB_MODE%"=="research" (
  call "%~dp0tools\launcher_log.cmd" "LANCER_LAB_QUANT_COPY_VAULT" STEP lab-mode "research; workspace-path-redacted" ""
  if "%~2"=="" (
    echo [ERREUR] Indiquez le chemin du workspace FULL/COLD en deuxieme argument.
    set "RC=2"
    goto :done
  )
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\alina_quant_lab_console.py" --research --dataset-root "%~2"
) else if /I "%ALINA_LAB_MODE%"=="copiabilite" (
  call "%~dp0tools\launcher_log.cmd" "LANCER_LAB_QUANT_COPY_VAULT" STEP lab-mode "copiabilite; multiple-offline-studies" ""
  rem Etude hors ligne sur le coffre LOCAL : verdicts exploratoires + besoins transmis aux collecteurs.
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\etude_copiabilite.py"
set "STEP_RC=!ERRORLEVEL!"
call "%~dp0tools\launcher_log.cmd" "LANCER_LAB_QUANT_COPY_VAULT" RESULT lab-step "copiabilite-base" "!STEP_RC!"
if not "!STEP_RC!"=="0" (set "RC=!STEP_RC!" & goto :done)
  rem Portefeuilles OBSERVES des vaults [instantanes certifies] puis historique reconstruit [backfill].
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\etude_copiabilite.py" --positions
set "STEP_RC=!ERRORLEVEL!"
call "%~dp0tools\launcher_log.cmd" "LANCER_LAB_QUANT_COPY_VAULT" RESULT lab-step "copiabilite-positions" "!STEP_RC!"
if not "!STEP_RC!"=="0" (set "RC=!STEP_RC!" & goto :done)
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\etude_copiabilite.py" --retrospectif
set "STEP_RC=!ERRORLEVEL!"
call "%~dp0tools\launcher_log.cmd" "LANCER_LAB_QUANT_COPY_VAULT" RESULT lab-step "copiabilite-retrospectif" "!STEP_RC!"
if not "!STEP_RC!"=="0" (set "RC=!STEP_RC!" & goto :done)
  rem Meme etude sur 208 jours de prix horaires [douze fois plus d'histoire que les bougies 5 min].
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\etude_copiabilite.py" --retrospectif --bougies 1h
set "STEP_RC=!ERRORLEVEL!"
call "%~dp0tools\launcher_log.cmd" "LANCER_LAB_QUANT_COPY_VAULT" RESULT lab-step "copiabilite-retrospectif-1h" "!STEP_RC!"
if not "!STEP_RC!"=="0" (set "RC=!STEP_RC!" & goto :done)
  rem Etude d'evenements : les ouvertures AGRESSIVES des leaders gardent-elles une valeur apres observation ?
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\etude_copiabilite.py" --ouvertures
set "STEP_RC=!ERRORLEVEL!"
call "%~dp0tools\launcher_log.cmd" "LANCER_LAB_QUANT_COPY_VAULT" RESULT lab-step "copiabilite-openings" "!STEP_RC!"
if not "!STEP_RC!"=="0" (set "RC=!STEP_RC!" & goto :done)
  rem Ordres en attente des leaders : quelle part de leurs executions etait visible a l'avance ?
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\etude_copiabilite.py" --ordres
set "STEP_RC=!ERRORLEVEL!"
call "%~dp0tools\launcher_log.cmd" "LANCER_LAB_QUANT_COPY_VAULT" RESULT lab-step "copiabilite-orders" "!STEP_RC!"
if not "!STEP_RC!"=="0" (set "RC=!STEP_RC!" & goto :done)
  rem Persistance des leaders : le classement passe d'un vault predit-il son rendement suivant ?
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\etude_copiabilite.py" --persistance
set "STEP_RC=!ERRORLEVEL!"
call "%~dp0tools\launcher_log.cmd" "LANCER_LAB_QUANT_COPY_VAULT" RESULT lab-step "copiabilite-persistence" "!STEP_RC!"
if not "!STEP_RC!"=="0" (set "RC=!STEP_RC!" & goto :done)
  rem Compte PAPER de 350 USD tenant le portefeuille observe d'un leader : frais, ecart, funding,
  rem ordre minimal de 10 USD, delai - et ce que coute chaque friction.
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\etude_copiabilite.py" --replication-350
set "STEP_RC=!ERRORLEVEL!"
call "%~dp0tools\launcher_log.cmd" "LANCER_LAB_QUANT_COPY_VAULT" RESULT lab-step "copiabilite-replication-350" "!STEP_RC!"
if not "!STEP_RC!"=="0" (set "RC=!STEP_RC!" & goto :done)
  rem Plan de recherche : quelle hypothese regarder ensuite, et combien de jours de donnees lui manquent.
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\etude_copiabilite.py" --plan
set "STEP_RC=!ERRORLEVEL!"
call "%~dp0tools\launcher_log.cmd" "LANCER_LAB_QUANT_COPY_VAULT" RESULT lab-step "copiabilite-plan" "!STEP_RC!"
if not "!STEP_RC!"=="0" (set "RC=!STEP_RC!" & goto :done)
) else if /I "%ALINA_LAB_MODE%"=="safe" (
  call "%~dp0tools\launcher_log.cmd" "LANCER_LAB_QUANT_COPY_VAULT" STEP lab-mode "safe-research" ""
  rem Etude consultative : son resultat est journalise sans masquer le resultat du moteur principal.
  call :optional_copiability
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\alina_quant_lab_console.py" --safe-research
) else if /I "%ALINA_LAB_MODE%"=="once" (
  call "%~dp0tools\launcher_log.cmd" "LANCER_LAB_QUANT_COPY_VAULT" STEP lab-mode "safe-research-once" ""
  call :optional_copiability
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\alina_quant_lab_console.py" --safe-research --once
) else (
  echo [ERREUR] Mode inconnu: %ALINA_LAB_MODE% [safe, once, copiabilite, tests, preflight, research, legacy]
  set "RC=2"
  goto :done
)
set "RC=%ERRORLEVEL%"
:done
call "%~dp0tools\launcher_log.cmd" "LANCER_LAB_QUANT_COPY_VAULT" EXIT completion "launcher-finished" "%RC%"
echo.
"%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\cmd_progress.py" elapsed
if "%RC%"=="0" (
  echo [FIN] Commande executee; seuls les rapports economiques determinent le resultat.
) else if "%RC%"=="130" (
  echo [ARRET] CTRL+C pris en compte. Essais complets et candidats geles conserves; rapport final ecrit.
) else (
  echo [NO_GO] Code %RC%. Aucune rentabilite n'est prouvee.
)
if /I not "%ALINA_QUANT_NO_PAUSE%"=="1" pause
endlocal & exit /b %RC%

:optional_copiability
if /I "%ALINA_LAB_COPIABILITE%"=="0" (
  call "%~dp0tools\launcher_log.cmd" "LANCER_LAB_QUANT_COPY_VAULT" RESULT lab-step "optional-copiability-skipped-by-config" "0"
  exit /b 0
)
call "%~dp0tools\launcher_log.cmd" "LANCER_LAB_QUANT_COPY_VAULT" STEP lab-step "optional-copiability-study" ""
"%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\etude_copiabilite.py"
set "OPTIONAL_RC=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "LANCER_LAB_QUANT_COPY_VAULT" RESULT lab-step "optional-copiability-study" "%OPTIONAL_RC%"
exit /b %OPTIONAL_RC%
