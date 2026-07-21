@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #145 : le panneau d'arbitrage affichait un spread INVENTE sans le dire.
REM   ASCII PUR, pas de pause -> "%~dp0rapports\check_145.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_145.txt"
echo === 1 sur 2 : le panneau DECLARE ses donnees fabriquees === >> "%~dp0rapports\check_145.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_arbitrage_panel_donnees_fabriquees.py >> "%~dp0rapports\check_145.txt" 2>&1
echo. >> "%~dp0rapports\check_145.txt"
echo === 2 sur 2 : non-regression arbitrage + dashboard + safety === >> "%~dp0rapports\check_145.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_hyperliquid_cex_spread_scanner.py tests\test_refactor_fusion_dashboard_e2e.py >> "%~dp0rapports\check_145.txt" 2>&1
python -m hl_observer safety-audit >> "%~dp0rapports\check_145.txt" 2>&1
echo FIN >> "%~dp0rapports\check_145.txt"
exit /b 0
