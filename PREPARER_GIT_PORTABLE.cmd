@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================================
echo   PREPARER GIT PORTABLE - HyperSmart
echo   Installe MinGit officiel dans tools\git.
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass ^
  -File "%~dp0tools\install_portable_git.ps1" ^
  -ProjectRoot "%~dp0."
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" echo [ECHEC] Git portable n'a pas ete installe. Code %RC%.
if /I not "%HYPERSMART_NO_PAUSE%"=="1" pause
endlocal & exit /b %RC%
