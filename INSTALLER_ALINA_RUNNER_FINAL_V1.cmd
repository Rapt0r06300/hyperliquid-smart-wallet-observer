@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Installation ALINA SMARTFLOW FINAL V1

if /I not "%GO_SELF_HOSTED%"=="TRUE" (
  echo [REFUS] GO_SELF_HOSTED=TRUE est obligatoire avant toute installation du runner final.
  echo Aucun service, token ou fichier runner ne sera modifie.
  exit /b 9
)

net session >nul 2>&1
if %errorlevel%==0 goto :ADMIN

echo Demande des droits administrateur...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; try { $arg='-NoLogo -NoProfile -ExecutionPolicy Bypass -File ""%~dp0tools\INSTALLER_ALINA_RUNNER_FINAL_V1.ps1"" -ConfirmSelfHosted'; $p=Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $arg -Wait -PassThru; exit $p.ExitCode } catch { Write-Error $_; exit 1223 }"
set RC=%ERRORLEVEL%
goto :END

:ADMIN
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\INSTALLER_ALINA_RUNNER_FINAL_V1.ps1" -ConfirmSelfHosted
set RC=%ERRORLEVEL%

:END
echo.
if "%RC%"=="0" (
  echo Runner FINAL V1 installe et demarre.
) else (
  echo Installation FINAL V1 en echec avec le code %RC%.
)
exit /b %RC%
