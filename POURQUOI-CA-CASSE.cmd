@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   POURQUOI CA CASSE - relance UNIQUEMENT les tests en echec, et les regroupe
REM   par CAUSE RACINE.
REM
REM   ASCII PUR, pas de "chcp" : un seul octet non-ASCII ferait executer ces
REM   commentaires par cmd.exe (bug rencontre 3 fois, cf. tools/garde_cmd_ascii.py).
REM
REM   POURQUOI CET OUTIL
REM     L'audit complet dure ~9 minutes et annonce "30 failed". Trente, ca fait peur.
REM     Mais un verrou qui refuse l'entree fait tomber la position, puis le PnL, puis
REM     l'equity : UN bug, VINGT symptomes. Cet outil compte les CAUSES.
REM
REM   100%% LECTURE SEULE cote marche : aucun ordre, aucune cle, aucun reseau de trading.
REM ==================================================================================
echo.
echo ==================================================================
echo   POURQUOI CA CASSE - les tests en echec, groupes par cause racine
echo   (~30 s, contre ~9 min pour l'audit complet)
echo ==================================================================
echo.

REM   La sortie va dans le PROJET, pas dans %TEMP% : un rapport qu'on ne peut pas
REM   relire n'existe pas. (Rate le 2026-07-12 : ecrit dans Temp, donc illisible.)
if not exist "runtime\audit" mkdir "runtime\audit"
set "SORTIE=%~dp0runtime\audit\echecs_pytest.txt"
set "RAPPORT=%~dp0POURQUOI-CA-CASSE.md"

python -m pytest -q --tb=short -p no:cacheprovider ^
  tests\test_ui_simulation_persistence.py ^
  tests\test_eval_trades_by_coin_invariant.py ^
  tests\test_calibration_no_dead_gates.py ^
  tests\test_directional_exposure.py ^
  tests\test_strict_md_accept_path.py ^
  tests\test_simulation_readiness.py ^
  tests\test_ui_copy_dashboard.py ^
  tests\test_simulation_log_export_forensics.py ^
  tests\test_hypersmart_simulation_diagnostic_logs.py ^
  > "%SORTIE%" 2>&1

type "%SORTIE%" | findstr /C:"passed" /C:"failed"
echo.

python tools\grouper_echecs.py < "%SORTIE%"
python tools\grouper_echecs.py < "%SORTIE%" > "%RAPPORT%"

echo.
echo   Rapport groupe        : %RAPPORT%
echo   Sortie pytest complete: %SORTIE%
echo.
pause
