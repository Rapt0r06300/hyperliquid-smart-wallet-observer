@echo off
setlocal EnableExtensions
REM ============================================================
REM  ANALYSE_HISTORIQUE_COMPLETE.cmd
REM  Lance la SUITE d'analyse historique complete (hl_observer.ops.historical_analysis_suite) sur les
REM  donnees locales : backtests, replays, walk-forward, anti-overfit -> rapport horodate.
REM  PAPER STRICT : 0 ordre reel, 0 cle privee, 0 signature, aucun endpoint d ordre reel.
REM ============================================================
cd /d "%~dp0"
REM MEME Python que le runtime (portable), ERRORLEVEL verifie immediatement, aucun repli systeme.
call "%~dp0tools\portable_env.cmd"
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
call "%~dp0tools\hyperlab_env.cmd"
echo.
echo ============================================================
echo   SUITE D'ANALYSE HISTORIQUE COMPLETE - paper strict (0 ordre reel)
echo ============================================================
echo.
set "OPT_MODE=--full"
if /I "%~1"=="deep" set "OPT_MODE=--deep"
"%HYPERSMART_PYTHON%" -m hl_observer.ops.historical_analysis_suite --root "%~dp0." %OPT_MODE%
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" (
  echo   [ANALYSE] Suite historique terminee : toutes les etapes PASSED. Rapport dans runtime\reports.
) else (
  echo   [ANALYSE] Suite historique RC=%RC% ^(voir le rapport horodate pour le detail^).
)
if /I not "%HYPERSMART_NO_PAUSE%"=="1" pause
endlocal ^& exit /b %RC%
