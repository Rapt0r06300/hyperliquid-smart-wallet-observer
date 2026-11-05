@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem ALINA_SYNC_COMPLETE.cmd : alias historique.
rem Le lanceur unifie est maintenant POUSSER-GITHUB-FORCE.cmd.
rem AlinaSync est integree comme PHASE B de ce lanceur unique.
rem
rem Compatibilite preservee :
rem   - sans argument            -> shards-only preflight (comportement historique)
rem   - --download-safe          -> telecharge SAFE (plafond 256 GiB)
rem   - --all-safe               -> telecharge tout SAFE sans plafond
rem   - --unpack-safe            -> telecharge + decompresse JSONL
rem   - --prune-cache-only       -> supprime le cache verifie inutilise
rem   - tout autre flag avance   -> appeler directement tools/sync_complete_clone.py

set "ALINA_ROOT=%~dp0"
set "UNIFIED=%ALINA_ROOT%POUSSER-GITHUB-FORCE.cmd"
if not exist "%UNIFIED%" (
  echo [NO_GO] Le lanceur unifie est introuvable : %UNIFIED%
  exit /b 2
)

echo [ALIAS] ALINA_SYNC_COMPLETE.cmd redirige vers POUSSER-GITHUB-FORCE.cmd (lanceur unifie).

if "%~1"=="" (
  call "%UNIFIED%" --shards-only
  set "RC=%ERRORLEVEL%"
  endlocal & exit /b %RC%
)

if /I "%~1"=="--download-safe" (
  call "%UNIFIED%" --shards-only --download-safe
  set "RC=%ERRORLEVEL%"
  endlocal & exit /b %RC%
)

if /I "%~1"=="--all-safe" (
  call "%UNIFIED%" --shards-only --all-safe
  set "RC=%ERRORLEVEL%"
  endlocal & exit /b %RC%
)

if /I "%~1"=="--unpack-safe" (
  call "%UNIFIED%" --shards-only --unpack-safe
  set "RC=%ERRORLEVEL%"
  endlocal & exit /b %RC%
)

if /I "%~1"=="--prune-cache-only" (
  call "%UNIFIED%" --shards-only --prune-cache
  set "RC=%ERRORLEVEL%"
  endlocal & exit /b %RC%
)

if /I "%~1"=="--preflight-only" (
  call "%UNIFIED%" --shards-only
  set "RC=%ERRORLEVEL%"
  endlocal & exit /b %RC%
)

echo [INFO] Flag avance "%~1" non traduit par l'alias ; forward direct a sync_complete_clone.py.
set "HYPERSMART_PYTHON="
set "HYPERSMART_PY_ARGS="
if exist "%ALINA_ROOT%tools\python\python.exe" set "HYPERSMART_PYTHON=%ALINA_ROOT%tools\python\python.exe"
if not defined HYPERSMART_PYTHON (
  where py.exe >nul 2>nul
  if not errorlevel 1 (
    set "HYPERSMART_PYTHON=py"
    set "HYPERSMART_PY_ARGS=-3"
  )
)
if not defined HYPERSMART_PYTHON (
  where python.exe >nul 2>nul
  if not errorlevel 1 set "HYPERSMART_PYTHON=python"
)
if not defined HYPERSMART_PYTHON (
  echo [NO_GO] Python 3.11 ou plus introuvable.
  endlocal & exit /b 31
)
set "GIT_LFS_SKIP_SMUDGE=1"
"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% "%ALINA_ROOT%tools\sync_complete_clone.py" %*
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
