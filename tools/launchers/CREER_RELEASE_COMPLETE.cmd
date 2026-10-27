@echo off
setlocal
for %%I in ("%~dp0..\..") do set "ALINA_PROJECT_ROOT=%%~fI"
cd /d "%ALINA_PROJECT_ROOT%" || exit /b 1
cd /d "%ALINA_PROJECT_ROOT%\"
echo Creation de la release complete Alina SmartFlow.
echo Les fichiers sont crees uniquement dans runtime\portable-build.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ALINA_PROJECT_ROOT%\tools\build_full_folder_release.ps1"
set "ALINA_RC=%ERRORLEVEL%"
if not "%ALINA_RC%"=="0" echo ECHEC - code %ALINA_RC%
if "%ALINA_RC%"=="0" echo TERMINE - consultez runtime\portable-build.
pause
exit /b %ALINA_RC%
