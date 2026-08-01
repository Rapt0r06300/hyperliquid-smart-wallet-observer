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
REM ITEM 10 : MEME Python que le runtime (runtime portable relocalisable).
call "%~dp0tools\portable_env.cmd"
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
REM === ITEM 10 : PORTE D'ENTREE — selectionne la DERNIERE session COMPLETE, RECALCULE les checksums,
REM   verifie presence + integrite + ZERO orphelin. Refuse ACTIVE (collecte en cours) et QUARANTINED.
REM   NO_GO => on n'analyse PAS des donnees corrompues/absentes. Ecrit ANALYSE_SESSION.md/.json.
%PY% -m hl_observer.ops.analyser_session --root "%~dp0."
if errorlevel 1 (
  echo.
  echo   [ANALYSE_SESSION] NO_GO : aucune session COMPLETE verifiee a analyser.
  echo   Lance d'abord LANCER_HYPERSMART.cmd, laisse-le collecter, puis arrete-le proprement
  echo   ^(la session passe COMPLETE avec checksums + zero orphelin^). Detail : runtime\reports\backtest_replay\ANALYSE_SESSION.md
  echo.
  pause
  endlocal
  exit /b 5
)
echo   [ANALYSE_SESSION] GO : session COMPLETE verifiee. Lancement du laboratoire sur CETTE session.
echo.
REM Budget MAXIMAL par defaut (plus de plafond arbitraire 48/32 code en dur — item 11) : --budget 0 =
REM grille entiere. Surchargeable : set HYPERSMART_LAB_BUDGET=<n> avant le double-clic pour borner.
set "HYPERSMART_LAB_BUDGET=%HYPERSMART_LAB_BUDGET%"
if "%HYPERSMART_LAB_BUDGET%"=="" set "HYPERSMART_LAB_BUDGET=0"
%PY% -m hl_observer.ops.lab_alpha --root "%~dp0." --source REEL --budget %HYPERSMART_LAB_BUDGET%
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
