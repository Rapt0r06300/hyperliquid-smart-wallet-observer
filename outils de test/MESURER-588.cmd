@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   T2b (#588) -- la jambe perp du carry HYPE peut-elle etre LIQUIDEE ?
REM   Lecture seule (endpoint /info public). ASCII PUR, pas de pause -> "%~dp0rapports\mesure_588.txt"
REM   La suite COMPLETE en dernier : la suite ciblee cache des rouges (lecon de G2).
REM ==================================================================================
echo DEBUT > "%~dp0rapports\mesure_588.txt"
echo === TESTS DU MODULE + DU VERROU CABLE === >> "%~dp0rapports\mesure_588.txt"
python -m pytest -q -p no:cacheprovider --tb=line tests\test_carry_liquidation_risk.py tests\test_delta_neutral_carry.py >> "%~dp0rapports\mesure_588.txt" 2>&1
echo. >> "%~dp0rapports\mesure_588.txt"
echo === MESURE SUR PRIX REELS (HYPE) === >> "%~dp0rapports\mesure_588.txt"
python tools\mesurer_risque_liquidation_carry.py >> "%~dp0rapports\mesure_588.txt" 2>&1
echo. >> "%~dp0rapports\mesure_588.txt"
echo === SUITE COMPLETE === >> "%~dp0rapports\mesure_588.txt"
python -m pytest -q -p no:cacheprovider --tb=line >> "%~dp0rapports\mesure_588.txt" 2>&1
echo. >> "%~dp0rapports\mesure_588.txt"
echo === SAFETY (no-real-trade) === >> "%~dp0rapports\mesure_588.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\mesure_588.txt" 2>&1
echo FIN >> "%~dp0rapports\mesure_588.txt"
exit /b 0
