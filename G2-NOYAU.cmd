@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   G2 - LE NOYAU UNIQUE. Un seul endroit decide, et il POSSEDE l'edge.
REM   + l'invariant : aucun module de production ne FABRIQUE un edge d'entree.
REM   + le cliquet de cablage : le nouveau module ne doit pas etre MORT.
REM   ASCII PUR, pas de "chcp", pas de pause -> g2_noyau.txt
REM ==================================================================================
(
  echo === [1/4] Le noyau : 4 questions, et il REFUSE l'edge de l'appelant ===
  python -m pytest -q --tb=short -p no:cacheprovider tests\test_noyau_unique.py
  echo.
  echo === [2/4] Le CABLAGE : LocalDecisionEngine passe-t-il vraiment par le noyau ? ===
  python -m pytest -q --tb=short -p no:cacheprovider ^
    tests\test_testnet_pipeline_slice.py tests\test_loop_candidate_factory.py ^
    tests\test_loop_engineering.py
  echo.
  echo === [3/4] Le cliquet de cablage + l'invariant des interrupteurs ===
  python -m pytest -q --tb=short -p no:cacheprovider ^
    tests\test_risk_guards_no_limbo.py tests\test_audit_cablage.py tests\test_interrupteurs.py
  echo.
  echo === [4/4] Non-regression Q1/Q2/Q3/G1/H-181 ===
  python -m pytest -q --tb=short -p no:cacheprovider ^
    tests\test_edge_source_q1.py tests\test_executable_legs.py tests\test_signal_taxonomy.py ^
    tests\test_lookahead_differential.py tests\test_overfit_selection.py
) > g2_noyau.txt 2>&1
exit /b 0
