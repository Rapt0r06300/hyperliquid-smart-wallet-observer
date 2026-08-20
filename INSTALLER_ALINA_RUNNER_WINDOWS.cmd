@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Installation ALINA SMARTFLOW - Runner HyperSmart

if /I not "%GO_SELF_HOSTED%"=="TRUE" (
  echo [REFUS] GO_SELF_HOSTED=TRUE est obligatoire avant toute installation du runner.
  echo Aucun service, token ou fichier runner ne sera modifie.
  exit /b 9
)

net session >nul 2>&1
if %errorlevel%==0 goto :ADMIN

echo Demande des droits administrateur...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$arg='-NoLogo -NoProfile -ExecutionPolicy Bypass -File ""%~dp0tools\INSTALLER_ALINA_RUNNER_WINDOWS.ps1""'; $p=Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $arg -Wait -PassThru; exit $p.ExitCode"
set RC=%ERRORLEVEL%
goto :END

:ADMIN
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\INSTALLER_ALINA_RUNNER_WINDOWS.ps1"
set RC=%ERRORLEVEL%

:END
echo.
if "%RC%"=="0" (
  echo Installation terminee et service runner configure.
) else (
  echo Installation en echec avec le code %RC%.
)
exit /b %RC%
