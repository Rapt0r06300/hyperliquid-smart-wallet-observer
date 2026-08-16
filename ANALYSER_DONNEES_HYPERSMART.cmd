@echo off
setlocal EnableExtensions
cd /d "%~dp0"

call "%~dp0tools\portable_env.cmd"
if errorlevel 1 (
  echo [ERREUR] Python portable introuvable.
  if /I not "%HYPERSMART_NO_PAUSE%"=="1" pause
  exit /b 30
)

set "PYTHONPATH=%~dp0src;%~dp0tools"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
set "REAL_MAINNET_TRADING=false"
set "TESTNET_ONLY=true"
set "HYPERSMART_ANALYSIS_LOCAL_ONLY=1"

set "DATASET_SUITE=%~1"
set "DATA_ROOT="
set "ECONOMIC_RUNNER=%~dp0tools\run_economic_objective_campaigns.py"

REM Sans argument, on garde la compatibilite avec l'ancien dossier materialized.
if "%DATASET_SUITE%"=="" (
  set "DATASET_SUITE=legacy-materialized"
  set "DATA_ROOT=%~dp0data\hypersmart_datasets\materialized"
) else (
  for /f "usebackq delims=" %%I in (`"%HYPERSMART_PYTHON%" -m hl_observer.ops.dataset_bridge locate --root "%~dp0." --suite "%DATASET_SUITE%"`) do set "DATA_ROOT=%%I"
  set "ECONOMIC_RUNNER=%~dp0tools\run_dataset_economic_campaigns.py"
)

if not defined DATA_ROOT (
  echo.
  echo [NO_GO] Aucun workspace courant pour la suite %DATASET_SUITE%.
  echo Lance d'abord LANCER_LABO_180GO.cmd et prepare cette suite.
  if /I not "%HYPERSMART_NO_PAUSE%"=="1" pause
  exit /b 5
)

if not exist "%DATA_ROOT%\runtime\data" (
  echo.
  echo [NO_GO] Les donnees FULL/COLD ne sont pas reconstruites ici :
  echo         %DATA_ROOT%\runtime\data
  echo.
  echo Suite : %DATASET_SUITE%
  if /I not "%HYPERSMART_NO_PAUSE%"=="1" pause
  exit /b 5
)

"%HYPERSMART_PYTHON%" -m hl_observer.ops.dataset_workspace --root "%~dp0." --materialized-root "%DATA_ROOT%"
if errorlevel 1 (
  echo [NO_GO] Impossible de preparer l'espace de replay.
  if /I not "%HYPERSMART_NO_PAUSE%"=="1" pause
  exit /b 6
)

echo.
echo ============================================================
echo   ALINA SMARTFLOW - REPLAY FULL/COLD - PAPER STRICT
echo   Suite : %DATASET_SUITE%
echo   Copy-Vault + Lead-Lag + Cross-Venue
echo   Aucune collecte live, aucun ordre reel.
echo ============================================================
echo.

"%HYPERSMART_PYTHON%" "%ECONOMIC_RUNNER%" --root "%DATA_ROOT%" --no-start-collection --lead-history-sources 8
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo [OK] Replay economique termine.
  echo Rapport lourd/local : %DATA_ROOT%\runtime\reports\economic_campaigns\HYPERSMART_ECONOMIC_OBJECTIVE_CAMPAIGN.md
  if /I not "%DATASET_SUITE%"=="legacy-materialized" (
    echo Couverture des sources : %DATA_ROOT%\runtime\reports\datasets\SOURCE_CONSUMPTION_COVERAGE.md
  )
  echo.
  echo [EXPORT] Copie du petit verdict dans docs\research\datasets ...
  "%HYPERSMART_PYTHON%" -m hl_observer.ops.dataset_result_export --root "%~dp0." --replay-root "%DATA_ROOT%" --suite "%DATASET_SUITE%"
  if errorlevel 1 (
    echo [ATTENTION] Le replay est termine mais le petit export GitHub a echoue.
    set "RC=7"
  ) else (
    echo [OK] Petit verdict pret pour GitHub :
    echo      docs\research\datasets\DERNIER_REPLAY_DATASETS.md
    echo      docs\research\datasets\DERNIER_REPLAY_DATASETS.json
  )
) else (
  echo [NO_GO] Replay termine avec le code %RC%.
  echo Une donnee peut manquer dans la suite reconstruite. Rien n'est invente.
)

if /I not "%HYPERSMART_NO_PAUSE%"=="1" pause
endlocal & exit /b %RC%
