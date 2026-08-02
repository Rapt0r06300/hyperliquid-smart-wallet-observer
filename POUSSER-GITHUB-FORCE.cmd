@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

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
  -ProjectRoot "%~dp0"
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" goto :echec_code
echo.
echo   [TERMINE] La branche main locale et GitHub sont synchronisees.
goto :fin

:echec
set "RC=1"
:echec_code
echo.
echo   [ECHEC] Rien n'a ete force ni ecrase. Code retour : %RC%

:fin
if /I not "%HYPERSMART_PUSH_NO_PAUSE%"=="1" pause
endlocal & exit /b %RC%
