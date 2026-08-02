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
call "%~dp0tools\portable_env.cmd"
if errorlevel 1 (
  echo [ERREUR] Runtime portable tools\python indisponible.
  endlocal & exit /b 30
)
if not defined HYPERSMART_PYTHON (
  echo [ERREUR] HYPERSMART_PYTHON non defini.
  endlocal & exit /b 31
)
set "PYTHONPATH=%~dp0src;%~dp0tools;%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
set "REAL_MAINNET_TRADING=false"
set "TESTNET_ONLY=true"

REM Validation de release : chemin court, borne, non interactif, sans reseau.
if /I "%~1"=="portable-smoke" (
  "%HYPERSMART_PYTHON%" -m hl_observer.ops.portable_smoke --root "%~dp0." --json
  set "RC=%ERRORLEVEL%"
  endlocal & exit /b %RC%
)

echo.
echo ============================================================
echo   LABORATOIRE ALPHA - paper strict (0 ordre reel)
echo   Le tableau de bord et l ETA vont s afficher en direct.
echo ============================================================
echo.
"%HYPERSMART_PYTHON%" -m hl_observer.ops.lab_alpha --root "%~dp0." --budget 48 --source REEL
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
