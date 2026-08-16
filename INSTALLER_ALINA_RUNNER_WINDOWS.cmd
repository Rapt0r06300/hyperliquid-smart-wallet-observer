@echo off
setlocal
cd /d "%~dp0"
title Installation ALINA SMARTFLOW - Runner HyperSmart
net session >nul 2>&1
if %errorlevel%==0 goto :ADMIN

echo Demande des droits administrateur...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList '-NoLogo -NoProfile -ExecutionPolicy Bypass -File ""%~dp0tools\INSTALLER_ALINA_RUNNER_WINDOWS.ps1""'"
exit /b 0

:ADMIN
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\INSTALLER_ALINA_RUNNER_WINDOWS.ps1"
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (
  echo Installation terminee. Tu peux lancer LANCER_COCKPIT_ALINA.cmd
) else (
  echo Installation en echec avec le code %RC%.
)
pause
exit /b %RC%
