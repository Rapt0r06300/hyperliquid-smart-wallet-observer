@echo off
setlocal EnableDelayedExpansion
rem ============================================================================
rem ALINA_SYNC_COMPLETE.cmd  -  Entree officielle OFFICIAL_DATA_SYNC (Windows).
rem PAPER / LECTURE SEULE : reprise apres sinistre et synchronisation du corpus
rem SAFE. Aucun ordre, aucune cle, aucune execution reelle. Jumeau de
rem ALINA_SYNC_COMPLETE.sh (meme moteur tools/sync_complete_clone.py).
rem
rem Sans argument : preflight uniquement, aucun telechargement.
rem   --download-safe           : telecharge le corpus SAFE (borne par defaut).
rem   --all-safe                : DOWNLOAD_AND_UNPACK_ALL_SAFE, corpus complet.
rem   --unpack-safe             : decompresse les conteneurs SAFE deja presents.
rem   --prune-only              : purge le cache sans telecharger.
rem ============================================================================
set "ALINA_ROOT=%~dp0"
set "UNIFIED=%ALINA_ROOT%POUSSER-GITHUB-FORCE.cmd"
set "GIT_LFS_SKIP_SMUDGE=1"

if "%~1"=="" (
    echo [AlinaSync] Preflight seul ^(aucun telechargement^). Utilisez --download-safe pour recuperer le corpus SAFE.
    call "%UNIFIED%" --shards-only --preflight-only --skip-update
    set "RC=!ERRORLEVEL!"
    for /f "delims=" %%R in ("!RC!") do set "RC=%%R"
    endlocal & exit /b %RC%
)

set "MODE=%~1"
if /i "%MODE%"=="--download-safe" goto :run
if /i "%MODE%"=="--all-safe" goto :run
if /i "%MODE%"=="--unpack-safe" goto :run
if /i "%MODE%"=="--prune-only" goto :run

echo Option AlinaSync inconnue : %MODE%
echo Options valides : --download-safe ^| --all-safe ^| --unpack-safe ^| --prune-only
endlocal & exit /b 2

:run
python "%ALINA_ROOT%tools\sync_complete_clone.py" %*
set "RC=!ERRORLEVEL!"
for /f "delims=" %%R in ("!RC!") do set "RC=%%R"
endlocal & exit /b %RC%
