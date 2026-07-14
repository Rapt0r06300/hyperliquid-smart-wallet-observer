@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   TEST-EDGE - le cablage de l'edge mesure (Q1), plus les tests qu'il debloque.
REM
REM   ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py).
REM
REM   POURQUOI CE LANCEUR
REM     Le mount du bac a sable TRONQUE realtime_magic_score.py depuis qu'il a grossi :
REM     impossible d'y executer ces tests. Windows lit le vrai fichier. C'est ici que
REM     la verite se mesure.
REM
REM   CE QU'IL VERIFIE
REM     1. tests/test_edge_vient_de_la_table.py    <- le cablage mort est-il repare ?
REM     2. tests/test_edge_reel_est_negatif.py     <- la VRAIE table est-elle toujours negative ?
REM     3. les 9 fichiers qui echouaient            <- combien le correctif en debloque-t-il ?
REM
REM   100%% lecture seule cote marche : aucun ordre, aucune cle.
REM ==================================================================================
echo.
echo =============================================================
echo   TEST-EDGE - le cablage de l'edge mesure (Q1)
echo =============================================================
echo.

if not exist "runtime\audit" mkdir "runtime\audit"
set "SORTIE=%~dp0runtime\audit\test_edge.txt"
set "RAPPORT=%~dp0POURQUOI-CA-CASSE.md"

echo [1/2] Le cablage lui-meme (le correctif est-il vraiment branche ?)
python -m pytest -q --tb=short -p no:cacheprovider ^
  tests\test_edge_vient_de_la_table.py ^
  tests\test_edge_reel_est_negatif.py ^
  tests\test_deux_compteurs_un_seul_verdict.py ^
  tests\test_eval_trades_by_coin_invariant.py ^
  tests\test_grouper_echecs.py ^
  tests\test_garde_cmd_ascii.py
echo.

echo [2/2] Les tests qui echouaient - combien sont debloques ?
python -m pytest -q --tb=short -p no:cacheprovider ^
  tests\test_env_hermetique.py ^
  tests\test_ui_simulation_persistence.py ^
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
echo   Rapport : %RAPPORT%
echo.
pause
