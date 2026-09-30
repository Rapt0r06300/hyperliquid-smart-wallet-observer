@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   Q3 + Z1 - LA ZONE MORTE EST DANS LE CODE, PAS SEULEMENT DANS UN .MD.
REM   + le CLIQUET de cablage : un nouveau module MORT doit faire ECHOUER la suite.
REM   ASCII PUR, pas de "chcp", pas de pause -> "%~dp0rapports\q3_tests.txt"
REM ==================================================================================
(
  echo === [1/3] Q3 + Z1 : la taxonomie des signaux ===
  python -m pytest -q --tb=short -p no:cacheprovider tests\test_signal_taxonomy.py
  echo.
  echo === [2/3] Q1 + Q2 : non-regression ===
  python -m pytest -q --tb=short -p no:cacheprovider ^
    tests\test_measured_edge_table.py tests\test_edge_source_q1.py tests\test_executable_legs.py
  echo.
  echo === [3/3] LE CLIQUET : aucun module nouveau ne doit etre MORT ===
  python -m pytest -q --tb=short -p no:cacheprovider ^
    tests\test_risk_guards_no_limbo.py tests\test_audit_cablage.py
) > "%~dp0rapports\q3_tests.txt" 2>&1
exit /b 0
