@echo off
title ALINA SMARTFLOW - Cockpit du laboratoire autonome
setlocal EnableExtensions

if "%ALINA_RESEARCH_HOME%"=="" (
  for /f "usebackq delims=" %%R in (`powershell.exe -NoLogo -NoProfile -Command "[Environment]::GetEnvironmentVariable('ALINA_RESEARCH_HOME','Machine')"`) do set "ALINA_RESEARCH_HOME=%%R"
)

if "%ALINA_RESEARCH_HOME%"=="" (
  echo ALINA_RESEARCH_HOME est absent.
  echo Lance d abord PREPARER_PC_ALINA.cmd.
  pause
  exit /b 2
)

if not exist "%ALINA_RESEARCH_HOME%\status" (
  echo Dossier laboratoire invalide : %ALINA_RESEARCH_HOME%
  pause
  exit /b 3
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\ALINA_RESEARCH_COCKPIT.ps1" -LabRoot "%ALINA_RESEARCH_HOME%" -RefreshSeconds 1
set RC=%ERRORLEVEL%
if not "%RC%"=="0" pause
exit /b %RC%
