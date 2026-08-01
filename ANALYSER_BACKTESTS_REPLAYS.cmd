@echo off
setlocal EnableExtensions
REM ============================================================
REM  ANALYSER_BACKTESTS_REPLAYS.cmd
REM  Laboratoire automatique de recherche d alpha / PnL net.
REM  Double-clic => inventaire des donnees -> feed_adapter -> MegaCablage
REM  (Copy-Vault + Cross-Venue 2 jambes + Lead-Lag) -> netting/routing ->
REM  risk gates -> fills paper -> PaperLedger -> PnL -> IS/OOS/FORWARD -> rapport.
REM  PAPER STRICT : 0 ordre reel, 0 cle privee, 0 signature, aucun /exchange.
REM ============================================================
cd /d "%~dp0"
set "PYTHONPATH=src;tools"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
set "REAL_MAINNET_TRADING=false"
set "TESTNET_ONLY=true"

set "PY=python"
where py >nul 2>nul && set "PY=py -3"

echo.
echo ============================================================
echo   LABORATOIRE ALPHA - paper strict (0 ordre reel)
echo   Le tableau de bord et l ETA vont s afficher en direct.
echo ============================================================
echo.
%PY% -m hl_observer.ops.lab_alpha --root "%~dp0." --budget 48 --source REEL
set "RC=%ERRORLEVEL%"

set "RAP=%~dp0runtime\reports\backtest_replay\RAPPORT_LATEST.md"
if exist "%RAP%" (
  echo.
  echo Rapport genere : "%RAP%"
  start "" "%RAP%"
) else (
  echo ATTENTION: rapport introuvable. Voir runtime\reports\backtest_replay\journal_lab.log
)
echo.
echo Termine (code %RC%). Appuyez sur une touche pour fermer.
pause >nul
endlocal
