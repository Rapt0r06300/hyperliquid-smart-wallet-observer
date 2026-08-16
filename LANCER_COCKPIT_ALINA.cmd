@echo off
title ALINA SMARTFLOW - Cockpit du laboratoire autonome
setlocal
if "%ALINA_RESEARCH_HOME%"=="" (
  echo ALINA_RESEARCH_HOME est absent.
  echo Lance d abord tools\INSTALLER_ALINA_RUNNER_WINDOWS.ps1 en administrateur.
  pause
  exit /b 2
)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\ALINA_RESEARCH_COCKPIT.ps1" -LabRoot "%ALINA_RESEARCH_HOME%" -RefreshSeconds 1
set RC=%ERRORLEVEL%
if not "%RC%"=="0" pause
exit /b %RC%
