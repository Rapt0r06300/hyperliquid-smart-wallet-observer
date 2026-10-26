@echo off
setlocal EnableExtensions
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
set "ALINA_QUANT_CPU_PERCENT=65"

set "ALINA_LAB_MODE=%~1"
if not defined ALINA_LAB_MODE set "ALINA_LAB_MODE=safe"
echo.
echo ================================================================
echo   ALINA SMART FLOW - COPY-VAULT LAB
echo   Double clic : shards SAFE locaux, replays/backtests en continu
echo   Arret propre : CTRL+C dans cette fenetre
echo   Modes : safe (continu) / once (un passage) / tests / preflight / research / legacy
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
if not defined ALINA_LAB_PYTHON (
  echo [ERREUR] Python 3 introuvable; aucun telechargement automatique.
  set "RC=30"
  goto :done
)

if /I "%ALINA_LAB_MODE%"=="tests" (
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
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\alina_quant_lab_console.py" --preflight-only
) else if /I "%ALINA_LAB_MODE%"=="legacy" (
  rem Preserve the Codex/Claude local economic laboratory as explicit opt-in.
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% -c "import pydantic, pytest, typer" >nul 2>nul
  if errorlevel 1 (
    echo [NO_GO] Installez les dependances du laboratoire local : py -3 -m pip install -e ".[dev]"
    set "RC=31"
    goto :done
  )
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\alina_quant_lab_console.py" --legacy-local-economic
) else if /I "%ALINA_LAB_MODE%"=="research" (
  if "%~2"=="" (
    echo [ERREUR] Indiquez le chemin du workspace FULL/COLD en deuxieme argument.
    set "RC=2"
    goto :done
  )
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\alina_quant_lab_console.py" --research --dataset-root "%~2"
) else if /I "%ALINA_LAB_MODE%"=="safe" (
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\alina_quant_lab_console.py" --safe-research
) else if /I "%ALINA_LAB_MODE%"=="once" (
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\alina_quant_lab_console.py" --safe-research --once
) else (
  echo [ERREUR] Mode inconnu: %ALINA_LAB_MODE% [safe, once, tests, preflight, research, legacy]
  set "RC=2"
  goto :done
)
set "RC=%ERRORLEVEL%"
:done
echo.
if "%RC%"=="0" (
  echo [FIN] Commande executee; seuls les rapports economiques determinent le resultat.
) else if "%RC%"=="130" (
  echo [ARRET] CTRL+C pris en compte. Essais complets et candidats geles conserves; rapport final ecrit.
) else (
  echo [NO_GO] Code %RC%. Aucune rentabilite n'est prouvee.
)
if /I not "%ALINA_QUANT_NO_PAUSE%"=="1" pause
endlocal & exit /b %RC%
