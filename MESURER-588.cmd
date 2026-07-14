@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   T2b (#588) -- la jambe perp du carry HYPE peut-elle etre LIQUIDEE ?
REM   Lecture seule (endpoint /info public). ASCII PUR, pas de pause -> mesure_588.txt
REM   La suite COMPLETE en dernier : la suite ciblee cache des rouges (lecon de G2).
REM ==================================================================================
echo DEBUT > mesure_588.txt
echo === TESTS DU MODULE + DU VERROU CABLE === >> mesure_588.txt
python -m pytest -q -p no:cacheprovider --tb=line tests\test_carry_liquidation_risk.py tests\test_delta_neutral_carry.py >> mesure_588.txt 2>&1
echo. >> mesure_588.txt
echo === MESURE SUR PRIX REELS (HYPE) === >> mesure_588.txt
python tools\mesurer_risque_liquidation_carry.py >> mesure_588.txt 2>&1
echo. >> mesure_588.txt
echo === SUITE COMPLETE === >> mesure_588.txt
python -m pytest -q -p no:cacheprovider --tb=line >> mesure_588.txt 2>&1
echo. >> mesure_588.txt
echo === SAFETY (no-real-trade) === >> mesure_588.txt
python -m hl_observer safety-audit >> mesure_588.txt 2>&1
echo FIN >> mesure_588.txt
exit /b 0
