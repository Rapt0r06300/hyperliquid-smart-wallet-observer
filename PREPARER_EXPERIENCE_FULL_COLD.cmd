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

set "SUITE=%~1"
set "FAMILY=%~2"
set "COIN=%~3"
set "METRIC=%~4"
set "START_MS=%~5"
set "END_MS=%~6"
set "WALLET=%~7"

if "%SUITE%"=="" goto :usage

set "DATA_ROOT="
for /f "usebackq delims=" %%I in (`"%HYPERSMART_PYTHON%" -m hl_observer.ops.dataset_bridge locate --root "%~dp0." --suite "%SUITE%"`) do set "DATA_ROOT=%%I"
if not defined DATA_ROOT (
  echo [NO_GO] Aucun workspace courant pour la suite %SUITE%.
  echo Prepare d'abord la suite avec LANCER_LABO_180GO.cmd.
  goto :erreur
)

set "ARGS=--root ^"%DATA_ROOT%^""
if not "%FAMILY%"=="" set "ARGS=%ARGS% --family ^"%FAMILY%^""
if not "%COIN%"=="" set "ARGS=%ARGS% --coin ^"%COIN%^""
if not "%METRIC%"=="" set "ARGS=%ARGS% --metric ^"%METRIC%^""
if not "%START_MS%"=="" set "ARGS=%ARGS% --start-ms %START_MS%"
if not "%END_MS%"=="" set "ARGS=%ARGS% --end-ms %END_MS%"
if not "%WALLET%"=="" set "ARGS=%ARGS% --wallet ^"%WALLET%^""

echo ============================================================
echo   ALINA SMARTFLOW - PLAN D'EXPERIENCE FULL/COLD
echo   Suite : %SUITE%
echo   Workspace : %DATA_ROOT%
echo   Lecture locale uniquement - aucun ordre reel
echo ============================================================
echo.
echo Famille : %FAMILY%
echo Coin    : %COIN%
echo Metrique: %METRIC%
echo Debut ms: %START_MS%
echo Fin ms  : %END_MS%
echo Wallet  : %WALLET%
echo.

call "%HYPERSMART_PYTHON%" -m hl_observer.ops.dataset_experiment_plan %ARGS%
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" (
  echo.
  echo [OK] Plan d'experience pret.
  echo Le plan ne copie aucune grosse donnee et ne lance aucun replay.
  echo Rapport courant :
  echo   %DATA_ROOT%\runtime\reports\datasets\experiment_plans\CURRENT_EXPERIMENT_PLAN.md
  goto :fin
)
if "%RC%"=="3" (
  echo.
  echo [NO_MATCH] Le plan est ecrit mais aucune source ne satisfait tous les criteres.
  echo Verifie le rapport courant avant d'elargir les criteres.
  goto :fin
)
goto :erreur_code

:usage
echo Usage :
echo   PREPARER_EXPERIENCE_FULL_COLD.cmd SUITE [FAMILLE] [COIN] [METRIQUE] [START_MS] [END_MS] [WALLET]
echo.
echo Exemples :
echo   PREPARER_EXPERIENCE_FULL_COLD.cmd economic-full copy_vault BTC net_pnl_usd
echo   PREPARER_EXPERIENCE_FULL_COLD.cmd sqlite-core copy_vault BTC "" 1780000000000 1780100000000 0xabc
echo.
echo Ce bouton utilise uniquement un workspace deja reconstruit.
set "RC=2"
goto :fin

:erreur
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" set "RC=1"
:erreur_code
echo.
echo [NO_GO] Preparation de l'experience interrompue. Code %RC%.
echo Aucune donnee absente n'est inventee et aucun ordre reel n'est possible.

:fin
if /I not "%HYPERSMART_NO_PAUSE%"=="1" pause
endlocal & exit /b %RC%
