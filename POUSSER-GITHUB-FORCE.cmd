@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

set "HYPERSMART_GIT=%~dp0tools\git\cmd\git.exe"
if not exist "%HYPERSMART_GIT%" set "HYPERSMART_GIT="
if not defined HYPERSMART_GIT for /f "delims=" %%G in ('where git.exe 2^>nul') do if not defined HYPERSMART_GIT set "HYPERSMART_GIT=%%G"
if not defined HYPERSMART_GIT (
  echo   [ERREUR] Git est introuvable.
  echo   Lance PREPARER_GIT_PORTABLE.cmd une fois, puis relance ce bouton.
  set "RC=2"
  goto :echec_code
)

set "PUSH_OPTION="
if /I "%~1"=="--dry-run" set "PUSH_OPTION=-DryRun"
if /I "%~1"=="dry-run" set "PUSH_OPTION=-DryRun"

echo ============================================================
echo   POUSSER vers GitHub - synchronisation sure de main
echo   Integre GitHub et les anciens bundles sans ecraser de commit.
echo   Aucun --force, aucun reset, aucun FETCH_HEAD pousse.
echo ============================================================
echo.

where powershell.exe >nul 2>nul
if errorlevel 1 (
  echo   [ERREUR] Windows PowerShell est introuvable.
  goto :echec
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass ^
  -File "%~dp0tools\push_github_safe.ps1" ^
  -ProjectRoot "%~dp0." ^
  -GitExecutable "%HYPERSMART_GIT%" ^
  %PUSH_OPTION%
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" goto :echec_code
echo.
if defined PUSH_OPTION (
  echo   [TERMINE] Controle dry-run reussi. Aucun merge et aucun push effectues.
  echo   Relance ce bouton sans --dry-run pour synchroniser main avec GitHub.
) else (
  echo   [TERMINE] La branche main locale et GitHub sont synchronisees.
)
goto :fin

:echec
set "RC=1"
:echec_code
echo.
echo   [ECHEC] Rien n'a ete force ni ecrase. Code retour : %RC%

:fin
if /I not "%HYPERSMART_PUSH_NO_PAUSE%"=="1" pause
endlocal & exit /b %RC%
