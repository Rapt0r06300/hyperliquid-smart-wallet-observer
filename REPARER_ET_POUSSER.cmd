@echo off
setlocal
call "%~dp0POUSSER-GITHUB-FORCE.cmd"
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
