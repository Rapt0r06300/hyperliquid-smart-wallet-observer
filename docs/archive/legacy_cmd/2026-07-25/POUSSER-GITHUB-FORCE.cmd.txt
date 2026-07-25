@echo off
chcp 65001 >nul
REM Push FORCE : remplace le contenu initial (README auto) du depot par TON projet complet.
REM A utiliser quand le push normal est rejete "fetch first" (le depot a un commit initial).
REM C'est TON depot ; seul le README auto-genere est ecrase. Aucun identifiant manipule par Claude.
cd /d "%~dp0"
echo === Envoi FORCE de la branche main vers GitHub ===
git push -u origin main --force
echo.
if %ERRORLEVEL%==0 (
  echo OK : projet complet pousse sur https://github.com/Rapt0r06300/hyperliquid-smart-wallet-observer
) else (
  echo ECHEC : lis le message ci-dessus.
)
echo.
pause
