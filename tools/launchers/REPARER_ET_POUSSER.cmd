@echo off
setlocal
for %%I in ("%~dp0..\..") do set "ALINA_PROJECT_ROOT=%%~fI"
cd /d "%ALINA_PROJECT_ROOT%" || exit /b 1
call "%ALINA_PROJECT_ROOT%\POUSSER-GITHUB-FORCE.cmd"
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
