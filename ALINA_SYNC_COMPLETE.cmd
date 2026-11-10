@echo off
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
    python "%ALINA_ROOT%tools\sync_complete_clone.py" --prune-cache-only
    endlocal & exit /b !ERRORLEVEL!
)

echo Option AlinaSync inconnue : %MODE%
echo Options valides : --download-safe ^| --all-safe ^| --unpack-safe ^| --prune-only
endlocal & exit /b 2

:run
if defined DEFAULT_SAFE_ARGS (
    python "%ALINA_ROOT%tools\sync_complete_clone.py" !DEFAULT_SAFE_ARGS!
) else (
    python "%ALINA_ROOT%tools\sync_complete_clone.py" %*
)
set "RC=!ERRORLEVEL!"
rem AlinaSync : rapatrie aussi les fills des lanes GitHub (fail-soft, non bloquant).
python "%ALINA_ROOT%tools\telecharger_fills_lanes_github.py" --root "%ALINA_ROOT%." 2>nul
rem AlinaSync : rapatrie aussi les fills LIVE_WS des lanes WS (fail-soft).
python "%ALINA_ROOT%tools/telecharger_fills_ws_lanes_github.py" --root "%ALINA_ROOT%." 2>nul
rem AlinaSync : rapatrie aussi les carnets L2 des lanes L2 (fail-soft).
python "%ALINA_ROOT%tools/telecharger_l2_lanes_github.py" --root "%ALINA_ROOT%." 2>nul
rem AlinaSync : rapatrie aussi le feed explorer (activite + decouverte leaders, fail-soft).
python "%ALINA_ROOT%tools/telecharger_explorer_github.py" --root "%ALINA_ROOT%." 2>nul
for /f "delims=" %%R in ("!RC!") do set "RC=%%R"
endlocal & exit /b %RC%
