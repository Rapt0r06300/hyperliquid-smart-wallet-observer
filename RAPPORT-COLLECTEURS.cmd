@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title RAPPORT COLLECTEURS - erreurs + ameliorations
set "LOGS_ONLY=0"
if /I "%~1"=="--logs-only" set "LOGS_ONLY=1"
set "PYTHONPATH=src"
set "CV_PYTHON="
set "CV_PY_ARGS="
if exist "tools\python\python.exe" set "CV_PYTHON=tools\python\python.exe"
if not defined CV_PYTHON if exist ".venv\Scripts\python.exe" set "CV_PYTHON=.venv\Scripts\python.exe"
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
set "ALINA_LAUNCH_RUN_ID=%DATE%_%TIME%_%RANDOM%_%RANDOM%"
if "%LOGS_ONLY%"=="1" (set "ALINA_LAUNCH_MODE=report-launcher-logs") else set "ALINA_LAUNCH_MODE=report-collectors"
set "ALINA_LAUNCH_PYTHON=%CV_PYTHON% %CV_PY_ARGS%"
set "ALINA_LAUNCH_OUTPUT_LOG=runtime/logs/rapport_collecteurs.log;runtime/reports/launchers/IMPROVEMENT_REPORT.md"
if not defined CV_PYTHON (
  set "ALINA_LAUNCH_PYTHON=unresolved"
  call "%~dp0tools\launcher_log.cmd" "RAPPORT-COLLECTEURS" EXIT preflight "python-3-not-found" "30"
  echo [NO_GO] Python 3 introuvable. Aucun rapport n'a ete genere.
  if /I not "%CV_NO_PAUSE%"=="1" pause
  endlocal & exit /b 30
)
call "%~dp0tools\launcher_log.cmd" "RAPPORT-COLLECTEURS" START preflight "generate-diagnostics" ""
set "RC=0"
if "%LOGS_ONLY%"=="1" goto :improvement_analysis
echo.
echo Generation du rapport detaille de tous les collecteurs...
"%CV_PYTHON%" %CV_PY_ARGS% "tools\rapport_collecteurs.py" --root "%~dp0."
set "RC=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "RAPPORT-COLLECTEURS" RESULT report "rapport_collecteurs.py" "%RC%"

:improvement_analysis
call "%~dp0tools\launcher_log.cmd" "RAPPORT-COLLECTEURS" STEP improvement-analysis "analyser_logs_lanceurs.py" ""
"%CV_PYTHON%" %CV_PY_ARGS% "tools\analyser_logs_lanceurs.py" --root "%~dp0." --ignore-run-id "%ALINA_LAUNCH_RUN_ID%"
set "LOG_REPORT_RC=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "RAPPORT-COLLECTEURS" RESULT improvement-analysis "analyser_logs_lanceurs.py" "%LOG_REPORT_RC%"
echo.
if not "%RC%"=="0" goto :report_failed
if not "%LOG_REPORT_RC%"=="0" (
  set "RC=%LOG_REPORT_RC%"
  goto :report_failed
)
if "%LOGS_ONLY%"=="1" goto :open_improvement_report
if exist "runtime\logs\rapport_collecteurs.log" (
  if /I not "%CV_NO_OPEN%"=="1" (
    echo Ouverture du rapport collecteurs...
    start "" notepad "runtime\logs\rapport_collecteurs.log"
  )
) else (
  echo [ERREUR] Rapport courant non genere; aucun ancien rapport ne sera ouvert comme s'il etait a jour.
  set "RC=2"
)

:open_improvement_report
if exist "runtime\reports\launchers\IMPROVEMENT_REPORT.md" (
  if /I not "%CV_NO_OPEN%"=="1" (
    echo Ouverture du rapport d'amelioration des lanceurs...
    start "" notepad "runtime\reports\launchers\IMPROVEMENT_REPORT.md"
  )
) else (
  echo [ERREUR] Rapport d'amelioration des lanceurs absent.
  set "RC=3"
)
if not "%RC%"=="0" goto :report_failed
goto :report_finish

:report_failed
echo [ERREUR] Generation en echec (code %RC%); aucun ancien rapport ne sera ouvert comme s'il etait a jour.

:report_finish
call "%~dp0tools\launcher_log.cmd" "RAPPORT-COLLECTEURS" EXIT completion "report-finished" "%RC%"
if /I not "%CV_NO_PAUSE%"=="1" pause
endlocal & exit /b %RC%
