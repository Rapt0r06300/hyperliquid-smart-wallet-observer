@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..\..") do set "ALINA_PROJECT_ROOT=%%~fI"
cd /d "%ALINA_PROJECT_ROOT%" || exit /b 1
REM ============================================================
REM  ANALYSE_HISTORIQUE_COMPLETE.cmd
REM  Lance la SUITE d'analyse historique complete (hl_observer.ops.historical_analysis_suite) sur les
REM  donnees locales : backtests, replays, walk-forward, anti-overfit -> rapport horodate.
REM  PAPER STRICT : 0 ordre reel, 0 cle privee, 0 signature, aucun endpoint d ordre reel.
REM ============================================================
cd /d "%ALINA_PROJECT_ROOT%\"
REM MEME Python que le runtime (portable), ERRORLEVEL verifie immediatement, aucun repli systeme.
call "%ALINA_PROJECT_ROOT%\tools\portable_env.cmd"
if errorlevel 1 (
  echo   [PYTHON] portable_env a echoue : aucun runtime Python portable valide. Abandon.
  if /I not "%HYPERSMART_NO_PAUSE%"=="1" pause
  endlocal ^& exit /b 30
)
if not defined HYPERSMART_PYTHON (
  echo   [PYTHON] HYPERSMART_PYTHON non defini par portable_env. Abandon.
  if /I not "%HYPERSMART_NO_PAUSE%"=="1" pause
  endlocal ^& exit /b 31
)
set "PYTHONPATH=%ALINA_PROJECT_ROOT%\src;%ALINA_PROJECT_ROOT%\tools"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
set "REAL_MAINNET_TRADING=false"
set "TESTNET_ONLY=true"
echo.
echo ============================================================
echo   SUITE D'ANALYSE HISTORIQUE COMPLETE - paper strict (0 ordre reel)
echo ============================================================
echo.
set "OPT_MODE=--full"
if /I "%~1"=="deep" set "OPT_MODE=--deep"
"%HYPERSMART_PYTHON%" -m hl_observer.ops.historical_analysis_suite --root "%ALINA_PROJECT_ROOT%\." %OPT_MODE%
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" (
  echo   [ANALYSE] Suite historique terminee : toutes les etapes PASSED. Rapport dans runtime\reports.
) else (
  echo   [ANALYSE] Suite historique RC=%RC% ^(voir le rapport horodate pour le detail^).
)
if /I not "%HYPERSMART_NO_PAUSE%"=="1" pause
endlocal ^& exit /b %RC%
