@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Preparation du PC - ALINA SMARTFLOW

echo ================================================================================
echo  ALINA SMARTFLOW - MISE A JOUR MAIN + VERIFICATION + INSTALLATION RUNNER
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

echo [1/4] Recuperation de main depuis GitHub...
git fetch origin main
if errorlevel 1 goto :GIT_FAIL

echo [2/4] Mise a jour fast-forward uniquement...
git pull --ff-only origin main
if errorlevel 1 goto :GIT_FAIL

echo [3/4] Validation PowerShell 5.1 de l installateur...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$p=Resolve-Path '.\tools\INSTALLER_ALINA_RUNNER_WINDOWS.ps1'; $t=$null; $e=$null; [System.Management.Automation.Language.Parser]::ParseFile($p,[ref]$t,[ref]$e) ^| Out-Null; if($e.Count -gt 0){$e ^| Format-List; exit 5}; Write-Host 'INSTALLATEUR POWERSHELL 5.1 : OK' -ForegroundColor Green"
if errorlevel 1 (
  echo [ECHEC] Installateur invalide. Rien n est lance.
  pause
  exit /b 5
)

echo [4/4] Lancement de l installation self-hosted avec elevation administrateur...
call "%~dp0INSTALLER_ALINA_RUNNER_WINDOWS.cmd"
exit /b %ERRORLEVEL%

:GIT_FAIL
echo [ECHEC] Git n a pas pu mettre main a jour proprement.
echo Aucun reset ni clean destructeur n a ete execute.
pause
exit /b 6
