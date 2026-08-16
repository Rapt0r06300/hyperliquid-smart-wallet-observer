@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Preparation du PC - ALINA SMARTFLOW

echo ================================================================================
echo  ALINA SMARTFLOW - MAIN + INSTALLATION + VERIFICATION + COCKPIT
echo ================================================================================
echo.

where git >nul 2>&1
if errorlevel 1 (
  echo [ECHEC] git.exe introuvable.
  pause
  exit /b 2
)

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set BRANCH=%%B
if /I not "%BRANCH%"=="main" (
  echo [ECHEC] Branche locale actuelle : %BRANCH%
  echo Cette procedure refuse de travailler ailleurs que sur main.
  pause
  exit /b 3
)

set STATUSFILE=%TEMP%\alina_git_status_%RANDOM%_%RANDOM%.txt
git status --porcelain > "%STATUSFILE%"
for %%Z in ("%STATUSFILE%") do if %%~zZ GTR 0 (
  echo [ECHEC] Le dossier Git contient des modifications locales.
  echo Aucun reset, clean ou ecrasement automatique ne sera fait.
  type "%STATUSFILE%"
  del "%STATUSFILE%" >nul 2>&1
  pause
  exit /b 4
)
del "%STATUSFILE%" >nul 2>&1

echo [1/6] Recuperation de main depuis GitHub...
git fetch origin main
if errorlevel 1 goto :GIT_FAIL

echo [2/6] Mise a jour fast-forward uniquement...
git pull --ff-only origin main
if errorlevel 1 goto :GIT_FAIL

echo [3/6] Validation PowerShell 5.1 de l installateur et du diagnostic...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$paths=@('.\tools\INSTALLER_ALINA_RUNNER_WINDOWS.ps1','.\tools\VERIFIER_ALINA_RUNNER_WINDOWS.ps1','.\tools\ALINA_RESEARCH_COCKPIT.ps1'); foreach($raw in $paths){$p=Resolve-Path $raw; $t=$null; $e=$null; [System.Management.Automation.Language.Parser]::ParseFile($p,[ref]$t,[ref]$e) ^| Out-Null; if($e.Count -gt 0){$e ^| Format-List; exit 5}}; Write-Host 'POWERSHELL 5.1 : OK' -ForegroundColor Green"
if errorlevel 1 (
  echo [ECHEC] Un script Alina est invalide. Rien n est installe.
  pause
  exit /b 5
)

echo [4/6] Installation ou revalidation du runner self-hosted...
call "%~dp0INSTALLER_ALINA_RUNNER_WINDOWS.cmd"
if errorlevel 1 (
  echo [ECHEC] Installation du runner interrompue ou refusee.
  pause
  exit /b 6
)

echo [5/6] Diagnostic complet du service et du laboratoire...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\VERIFIER_ALINA_RUNNER_WINDOWS.ps1"
if errorlevel 1 (
  echo [ECHEC] Le diagnostic runner n est pas vert. Le cockpit ne sera pas ouvert automatiquement.
  pause
  exit /b 7
)

echo [6/6] Ouverture du cockpit temps reel...
start "ALINA SMARTFLOW - Cockpit" "%~dp0LANCER_COCKPIT_ALINA.cmd"

echo.
echo ================================================================================
echo  PC ALINA PRET : le runner peut maintenant recevoir les gros jobs depuis GitHub.
echo ================================================================================
echo Le cockpit se rafraichit chaque seconde. Fermer le cockpit ne coupe pas le runner.
exit /b 0

:GIT_FAIL
echo [ECHEC] Git n a pas pu mettre main a jour proprement.
echo Aucun reset ni clean destructeur n a ete execute.
pause
exit /b 8
