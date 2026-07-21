@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   GH-01 - L'INVARIANT SUR LES INTERRUPTEURS (celui qui manquait depuis le debut).
REM   + le CLIQUET de cablage : le nouveau module ne doit pas etre MORT.
REM   ASCII PUR, pas de "chcp", pas de pause -> "%~dp0rapports\gh01_interrupteurs.txt"
REM ==================================================================================
(
  echo === [1/3] L'invariant : tout interrupteur est ALLUME ou DECLARE ETEINT ===
  python -m pytest -q --tb=short -p no:cacheprovider tests\test_interrupteurs.py
  echo.
  echo === [2/3] Le cliquet de cablage : aucun module nouveau ne doit etre MORT ===
  python -m pytest -q --tb=short -p no:cacheprovider ^
    tests\test_risk_guards_no_limbo.py tests\test_audit_cablage.py
  echo.
  echo === [3/3] Non-regression : les protections + les vetos V26 ===
  python -m pytest -q --tb=short -p no:cacheprovider ^
    tests\test_overfit_selection.py tests\test_lookahead_differential.py ^
    tests\test_signal_taxonomy.py tests\test_edge_source_q1.py
) > "%~dp0rapports\gh01_interrupteurs.txt" 2>&1
exit /b 0
