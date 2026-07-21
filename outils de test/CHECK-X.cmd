@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   X-04 (#365) : funding arb PERP<->PERP -- la voie de reouverture DESIGNEE.
REM   X-11 (#372) : la carte des liquidations (liquidationPx qu'on JETAIT).
REM   X-01 (#362) : les depots Arbitrum (refus d'inventer l'adresse du pont).
REM   ASCII PUR, pas de pause -> "%~dp0rapports\check_x.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_x.txt"
echo === 1. FUNDING PERP-PERP (X-04) === >> "%~dp0rapports\check_x.txt"
python tools\mesurer_funding_perp_perp.py >> "%~dp0rapports\check_x.txt" 2>&1
echo. >> "%~dp0rapports\check_x.txt"
echo === 2. SUITE COMPLETE === >> "%~dp0rapports\check_x.txt"
python -m pytest -q -p no:cacheprovider --tb=short >> "%~dp0rapports\check_x.txt" 2>&1
echo. >> "%~dp0rapports\check_x.txt"
echo === 3. SAFETY (no-real-trade) === >> "%~dp0rapports\check_x.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\check_x.txt" 2>&1
echo FIN >> "%~dp0rapports\check_x.txt"
exit /b 0
