@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo   HyperSmart : PUSH des commits (faits par Claude) vers GitHub
echo   Ce script POUSSE seulement : aucun git add, aucun commit, aucun --force.
echo ============================================================
echo.
git push origin main
echo.
if %ERRORLEVEL%==0 (
  echo OK : commits pousses sur https://github.com/Rapt0r06300/hyperliquid-smart-wallet-observer
) else (
  echo ECHEC : lis le message ci-dessus.
)
echo.
pause
