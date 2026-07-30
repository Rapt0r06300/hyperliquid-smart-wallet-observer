@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo   HyperSmart : COMMIT de tout le travail + PUSH FORCE GitHub
echo ============================================================
echo.

REM Nettoie un eventuel verrou git orphelin (le pont cloud ne peut pas le supprimer ; git natif oui).
if exist ".git\index.lock" del /f /q ".git\index.lock"

REM 1) Tout mettre en index (les helpers .patch sont ignores via .gitignore).
git add -A

REM 2) Commit. Message optionnel en 1er argument, sinon message par defaut date-libre.
set "MSG=%~1"
if "%MSG%"=="" set "MSG=hypersmart: avancement V3 (Claude Cowork)"
git commit -m "%MSG%"
if errorlevel 1 echo (rien de neuf a committer, ou commit deja fait - on pousse quand meme)

echo.
echo === PUSH FORCE vers origin/main ===
git push -u origin main --force
echo.
if %ERRORLEVEL%==0 (
  echo OK : pousse sur https://github.com/Rapt0r06300/hyperliquid-smart-wallet-observer
) else (
  echo ECHEC push : lis le message ci-dessus.
)
echo.
echo === 6 derniers commits ===
git log --oneline -6
echo.
pause
