@echo off
setlocal EnableExtensions EnableDelayedExpansion
rem ALINA_SYNC_COMPLETE.cmd : alias historique compatible.
rem La reconciliation code est portee par POUSSER-GITHUB-FORCE.cmd.
rem Ce fichier conserve le chemin AlinaSync SAFE sans lancer de push implicite.

set "ALINA_ROOT=%~dp0"
set "UNIFIED=%ALINA_ROOT%POUSSER-GITHUB-FORCE.cmd"
set "RC=1"
if not exist "%UNIFIED%" (
  echo [NO_GO] Le lanceur unifie est introuvable : %UNIFIED%
  endlocal & exit /b 2
)

if "%~1"=="" (
  call "%UNIFIED%" --shards-only --preflight-only --skip-update
  set "RC=!ERRORLEVEL!"
  goto :alias_return
)

if /I "%~1"=="--preflight-only" (
  call "%UNIFIED%" --shards-only --preflight-only --skip-update
  set "RC=!ERRORLEVEL!"
  goto :alias_return
)

if /I "%~1"=="--download-safe" (
  call "%UNIFIED%" --shards-only --download-safe
  set "RC=!ERRORLEVEL!"
  goto :alias_return
)

if /I "%~1"=="--all-safe" (
  call "%UNIFIED%" --shards-only --all-safe
  set "RC=!ERRORLEVEL!"
  goto :alias_return
)

if /I "%~1"=="--unpack-safe" (
  call "%UNIFIED%" --shards-only --unpack-safe
  set "RC=!ERRORLEVEL!"
  goto :alias_return
)

if /I "%~1"=="--prune-cache-only" (
  call "%UNIFIED%" --shards-only --prune-cache-only
  set "RC=!ERRORLEVEL!"
  goto :alias_return
)

if /I "%~1"=="--catalog-budget" (
  call "%UNIFIED%" --shards-only --catalog-budget
  set "RC=!ERRORLEVEL!"
  goto :alias_return
)

echo [NO_GO] Option AlinaSync inconnue : %~1
echo         Options : --preflight-only, --download-safe, --all-safe, --unpack-safe, --prune-cache-only, --catalog-budget
set "RC=2"

:alias_return
for /f "delims=" %%R in ("!RC!") do endlocal & exit /b %%R
