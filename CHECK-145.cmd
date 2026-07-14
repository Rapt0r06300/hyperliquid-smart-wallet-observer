@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #145 : le panneau d'arbitrage affichait un spread INVENTE sans le dire.
REM   ASCII PUR, pas de pause -> check_145.txt
REM ==================================================================================
echo DEBUT > check_145.txt
echo === 1 sur 2 : le panneau DECLARE ses donnees fabriquees === >> check_145.txt
python -m pytest -q --tb=short -p no:cacheprovider tests\test_arbitrage_panel_donnees_fabriquees.py >> check_145.txt 2>&1
echo. >> check_145.txt
echo === 2 sur 2 : non-regression arbitrage + dashboard + safety === >> check_145.txt
python -m pytest -q --tb=short -p no:cacheprovider tests\test_hyperliquid_cex_spread_scanner.py tests\test_refactor_fusion_dashboard_e2e.py >> check_145.txt 2>&1
python -m hl_observer safety-audit >> check_145.txt 2>&1
echo FIN >> check_145.txt
exit /b 0
