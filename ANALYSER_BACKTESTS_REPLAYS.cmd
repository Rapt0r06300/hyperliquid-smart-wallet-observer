@echo off
setlocal
cd /d "%~dp0"
title HyperSmart - Backtests et replays locaux

call "%~dp0tools\portable_env.cmd"
if errorlevel 1 (
  echo.
  echo   ERREUR : aucun runtime Python HyperSmart valide.
  echo   Lance d'abord LANCER_HYPERSMART.cmd portable-install
  echo.
  pause
  exit /b 2
)

set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
set "HYPERSMART_ANALYSIS_LOCAL_ONLY=1"
set "OMP_NUM_THREADS=2"
set "OPENBLAS_NUM_THREADS=2"
set "MKL_NUM_THREADS=2"
set "NUMEXPR_NUM_THREADS=2"

set "SUITE_ARGS=%*"
set "MODE_LABEL=FULL - validation temporelle et anti-overfit"
if "%~1"=="" set "SUITE_ARGS=--full"
if /i "%~1"=="quick" (
  set "SUITE_ARGS="
  set "MODE_LABEL=QUICK - diagnostic borne"
)
if /i "%~1"=="full" (
  set "SUITE_ARGS=--full"
  set "MODE_LABEL=FULL - validation temporelle et anti-overfit"
)
if /i "%~1"=="deep" (
  set "SUITE_ARGS=--deep"
  set "MODE_LABEL=DEEP - recherche exhaustive reprenable"
)
if /i "%~1"=="maximum" (
  set "SUITE_ARGS=--deep"
  set "MODE_LABEL=MAXIMUM - recherche exhaustive reprenable"
)
if /i "%~1"=="--full" set "MODE_LABEL=FULL - validation temporelle et anti-overfit"
if /i "%~1"=="--deep" set "MODE_LABEL=DEEP - recherche exhaustive reprenable"

echo.
echo   ================================================================
echo    HYPERSMART - LABORATOIRE PNL + BACKTESTS + REPLAYS
echo   ================================================================
echo.
echo   Mode    : %MODE_LABEL%
echo   Sources : runtime\replay et logs\logs a envoyer
echo   Reseau  : non utilise
echo   Sortie  : runtime\reports\backtest_replay
echo.
echo   Double-clic = FULL : laboratoire PnL + walk-forward + anti-overfit
echo   Argument quick = diagnostic standard plus court
echo   Argument full  = analyse complete recommandee
echo   Argument deep  = ajoute la recherche exhaustive reprenable
echo   Argument maximum = alias explicite du mode deep
echo.
echo   Les comparaisons utilisent train / validation / holdout chronologiques.
echo   Aucun reglage n'est active automatiquement depuis un backtest.
echo.

python -u "%~dp0tools\run_backtest_replay_suite.py" --root "%~dp0." %SUITE_ARGS%
set "ANALYSIS_CODE=%ERRORLEVEL%"

echo.
if "%ANALYSIS_CODE%"=="0" (
  echo   TERMINE : toutes les etapes executables ont reussi.
) else if "%ANALYSIS_CODE%"=="1" (
  echo   TERMINE AVEC ALERTES : le rapport indique les etapes en echec.
) else (
  echo   TERMINE SANS DONNEE EXPLOITABLE : consulter le rapport.
)
echo.
echo   Rapport le plus recent :
echo   %~dp0runtime\reports\backtest_replay\RAPPORT_LATEST.md
echo.
if exist "%~dp0runtime\reports\backtest_replay\RAPPORT_LATEST.md" (
  start "" notepad.exe "%~dp0runtime\reports\backtest_replay\RAPPORT_LATEST.md"
)
pause
exit /b %ANALYSIS_CODE%
