@echo off
chcp 65001 >nul
setlocal EnableExtensions
for %%I in ("%~dp0..\..") do set "ALINA_PROJECT_ROOT=%%~fI"
cd /d "%ALINA_PROJECT_ROOT%" || exit /b 1
cd /d "%ALINA_PROJECT_ROOT%\"

echo ============================================================
echo   PREPARER GIT PORTABLE - HyperSmart
echo   Installe MinGit officiel dans tools\git.
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass ^
  -File "%ALINA_PROJECT_ROOT%\tools\install_portable_git.ps1" ^
  -ProjectRoot "%ALINA_PROJECT_ROOT%\."
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" echo [ECHEC] Git portable n'a pas ete installe. Code %RC%.
if /I not "%HYPERSMART_NO_PAUSE%"=="1" pause
endlocal & exit /b %RC%
