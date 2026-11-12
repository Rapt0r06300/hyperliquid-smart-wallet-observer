@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
rem ============================================================================
rem ALINA_SYNC_COMPLETE.cmd  -  Entree officielle OFFICIAL_DATA_SYNC (Windows).
rem PAPER / LECTURE SEULE : reprise apres sinistre et synchronisation du corpus
rem SAFE. Aucun ordre, aucune cle, aucune execution reelle. Jumeau de
rem ALINA_SYNC_COMPLETE.sh (meme moteur tools/sync_complete_clone.py).
rem
rem Sans argument : restauration SAFE complete et decompressee (opt-in par lancement).
rem   --download-safe           : telecharge le corpus SAFE (borne par defaut).
rem   --all-safe                : DOWNLOAD_AND_UNPACK_ALL_SAFE, corpus complet.
rem   --unpack-safe             : decompresse les conteneurs SAFE deja presents.
rem   --prune-only              : purge le cache sans telecharger.
rem ============================================================================
set "ALINA_ROOT=%~dp0"
set "UNIFIED=%ALINA_ROOT%POUSSER-GITHUB-FORCE.cmd"
set "GIT_LFS_SKIP_SMUDGE=1"
set "ALINA_LAUNCH_RUN_ID=%DATE%_%TIME%_%RANDOM%_%RANDOM%"
set "ALINA_SYNC_PYTHON="
set "ALINA_SYNC_PY_ARGS="
if exist "%ALINA_ROOT%tools\python\python.exe" set "ALINA_SYNC_PYTHON=%ALINA_ROOT%tools\python\python.exe"
if not defined ALINA_SYNC_PYTHON if exist "%ALINA_ROOT%.venv\Scripts\python.exe" set "ALINA_SYNC_PYTHON=%ALINA_ROOT%.venv\Scripts\python.exe"
if not defined ALINA_SYNC_PYTHON (
    where py >nul 2>nul
    if not errorlevel 1 (
        set "ALINA_SYNC_PYTHON=py"
        set "ALINA_SYNC_PY_ARGS=-3"
    )
)
if not defined ALINA_SYNC_PYTHON (
    where python >nul 2>nul
    if not errorlevel 1 set "ALINA_SYNC_PYTHON=python"
)
set "ALINA_LAUNCH_PYTHON=!ALINA_SYNC_PYTHON! !ALINA_SYNC_PY_ARGS!"
set "ALINA_LAUNCH_OUTPUT_LOG=runtime/logs/launchers/ALINA_SYNC_COMPLETE.output.log"
set "ALINA_LAUNCH_MODE=argument-dispatch"
if not defined ALINA_SYNC_PYTHON goto :missing_python

if "%~1"=="" (
    rem The explicit operator launch requests every selected SAFE asset, SHA-verified.
    rem Never invoke POUSSER-GITHUB-FORCE here; this entrypoint is data-only.
    set "DEFAULT_SAFE_ARGS=--download-safe --all-safe --unpack-safe"
    goto :run
)

set "MODE=%~1"
if /i "%MODE%"=="--help" goto :run
if /i "%MODE%"=="--preflight-only" goto :run
if /i "%MODE%"=="--catalog-budget" goto :run
if /i "%MODE%"=="--prune-cache-only" goto :run
if /i "%MODE%"=="--download-safe" goto :run
if /i "%MODE%"=="--all-safe" goto :run
if /i "%MODE%"=="--unpack-safe" goto :run
if /i "%MODE%"=="--prune-only" (
    set "ALINA_LAUNCH_MODE=prune-only"
    call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" START preflight "prune-cache-only" ""
    "!ALINA_SYNC_PYTHON!" !ALINA_SYNC_PY_ARGS! "%ALINA_ROOT%tools\sync_complete_clone.py" --prune-cache-only
    set "RC=!ERRORLEVEL!"
    call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" EXIT completion "prune-cache-only" "!RC!"
    endlocal & exit /b !RC!
)

echo Option AlinaSync inconnue : %MODE%
echo Options valides : --download-safe ^| --all-safe ^| --unpack-safe ^| --prune-only
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" EXIT argument-validation "unknown-option" "2"
endlocal & exit /b 2

:run
if defined DEFAULT_SAFE_ARGS (set "ALINA_LAUNCH_MODE=default-all-safe") else (set "ALINA_LAUNCH_MODE=%MODE%")
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" START preflight "sync-request" ""
if defined DEFAULT_SAFE_ARGS (
    call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" STEP download "sync_complete_clone.py" ""
    "!ALINA_SYNC_PYTHON!" !ALINA_SYNC_PY_ARGS! "%ALINA_ROOT%tools\sync_complete_clone.py" !DEFAULT_SAFE_ARGS!
) else (
    call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" STEP download "sync_complete_clone.py" ""
    "!ALINA_SYNC_PYTHON!" !ALINA_SYNC_PY_ARGS! "%ALINA_ROOT%tools\sync_complete_clone.py" %*
)
set "RC=!ERRORLEVEL!"
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" RESULT primary-sync "sync_complete_clone.py" "!RC!"
if /I "!MODE!"=="--help" goto :primary_only
if /I "!MODE!"=="--preflight-only" goto :primary_only
if /I "!MODE!"=="--catalog-budget" goto :primary_only
if /I "!MODE!"=="--prune-cache-only" goto :primary_only
rem AlinaSync : rapatrie aussi les fills des lanes GitHub (fail-soft, non bloquant).
set "LANE_FAILURES=0"
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" STEP github-lanes "telecharger_fills_lanes_github.py" ""
"!ALINA_SYNC_PYTHON!" !ALINA_SYNC_PY_ARGS! "%ALINA_ROOT%tools\telecharger_fills_lanes_github.py" --root "%ALINA_ROOT%." >>"%ALINA_ROOT%runtime\logs\launchers\ALINA_SYNC_COMPLETE.output.log" 2>&1
set "LANE_RC=!ERRORLEVEL!"
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" RESULT github-lanes "telecharger_fills_lanes_github.py" "!LANE_RC!"
if not "!LANE_RC!"=="0" set /a LANE_FAILURES+=1
rem AlinaSync : rapatrie aussi les fills LIVE_WS des lanes WS (fail-soft).
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" STEP github-lanes "telecharger_fills_ws_lanes_github.py" ""
"!ALINA_SYNC_PYTHON!" !ALINA_SYNC_PY_ARGS! "%ALINA_ROOT%tools\telecharger_fills_ws_lanes_github.py" --root "%ALINA_ROOT%." >>"%ALINA_ROOT%runtime\logs\launchers\ALINA_SYNC_COMPLETE.output.log" 2>&1
set "LANE_RC=!ERRORLEVEL!"
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" RESULT github-lanes "telecharger_fills_ws_lanes_github.py" "!LANE_RC!"
if not "!LANE_RC!"=="0" set /a LANE_FAILURES+=1
rem AlinaSync : rapatrie aussi les carnets L2 des lanes L2 (fail-soft).
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" STEP github-lanes "telecharger_l2_lanes_github.py" ""
"!ALINA_SYNC_PYTHON!" !ALINA_SYNC_PY_ARGS! "%ALINA_ROOT%tools\telecharger_l2_lanes_github.py" --root "%ALINA_ROOT%." >>"%ALINA_ROOT%runtime\logs\launchers\ALINA_SYNC_COMPLETE.output.log" 2>&1
set "LANE_RC=!ERRORLEVEL!"
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" RESULT github-lanes "telecharger_l2_lanes_github.py" "!LANE_RC!"
if not "!LANE_RC!"=="0" set /a LANE_FAILURES+=1
rem AlinaSync : rapatrie aussi le feed explorer (activite + decouverte leaders, fail-soft).
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" STEP github-lanes "telecharger_explorer_github.py" ""
"!ALINA_SYNC_PYTHON!" !ALINA_SYNC_PY_ARGS! "%ALINA_ROOT%tools\telecharger_explorer_github.py" --root "%ALINA_ROOT%." >>"%ALINA_ROOT%runtime\logs\launchers\ALINA_SYNC_COMPLETE.output.log" 2>&1
set "LANE_RC=!ERRORLEVEL!"
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" RESULT github-lanes "telecharger_explorer_github.py" "!LANE_RC!"
if not "!LANE_RC!"=="0" set /a LANE_FAILURES+=1
rem AlinaSync : rapatrie aussi les lanes marche (transactions, bougies) et contexte (positions des
rem leaders relevees 24h/24, tranches TWAP), validees ligne a ligne par le certificateur (fail-soft).
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" STEP github-lanes "telecharger_lanes_certifiees_github.py" ""
"!ALINA_SYNC_PYTHON!" !ALINA_SYNC_PY_ARGS! "%ALINA_ROOT%tools\telecharger_lanes_certifiees_github.py" --root "%ALINA_ROOT%." >>"%ALINA_ROOT%runtime\logs\launchers\ALINA_SYNC_COMPLETE.output.log" 2>&1
set "LANE_RC=!ERRORLEVEL!"
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" RESULT github-lanes "telecharger_lanes_certifiees_github.py" "!LANE_RC!"
if not "!LANE_RC!"=="0" set /a LANE_FAILURES+=1
for /f "delims=" %%R in ("!RC!") do set "RC=%%R"
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" SUMMARY github-lanes "failed-lanes=!LANE_FAILURES!" "!LANE_FAILURES!"
goto :sync_complete

:primary_only
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" SUMMARY github-lanes "skipped-for-non-download-mode" "0"

:sync_complete
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" EXIT completion "sync-complete" "!RC!"
endlocal & exit /b %RC%

:missing_python
set "ALINA_LAUNCH_PYTHON=unresolved"
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" EXIT preflight "python-3-not-found" "30"
echo [NO_GO] Python 3 introuvable. Aucune synchronisation n'a ete lancee.
endlocal & exit /b 30
