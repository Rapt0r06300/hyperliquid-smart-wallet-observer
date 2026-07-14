@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   Q2 - L'ARBITRAGE SE JUGE SUR DES JAMBES EXECUTABLES, JAMAIS SUR LE MID.
REM
REM   Tests de Q2 + les suites qui touchent l'arbitrage et le carnet (non-regression).
REM   ASCII PUR, pas de "chcp", pas de pause -> q2_jambes.txt
REM   Lecture seule. Aucun ordre, aucune cle, aucune signature.
REM ==================================================================================
(
  echo === [1/2] Les tests de Q2 ===
  python -m pytest -q --tb=short -p no:cacheprovider tests\test_executable_legs.py
  echo.
  echo === [2/2] Non-regression : arbitrage, carnet, fusion, ws ===
  python -m pytest -q --tb=short -p no:cacheprovider ^
    tests\test_ws_price_discrepancy_detector.py ^
    tests\test_v14_portage_framework_modules.py ^
    tests\test_live_book_costs.py ^
    tests\test_v26_l3_to_l9.py ^
    tests\test_risk_liquidity_orphans_wired.py ^
    tests\test_coin_universe.py ^
    tests\test_book_poller_starts.py
) > q2_jambes.txt 2>&1
exit /b 0
