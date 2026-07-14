@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #587 / T1b -- coter DANS le spread : la derniere porte ouverte du market making.
REM   Mesure + suite COMPLETE + safety. ASCII PUR, pas de pause -> check_t1b.txt
REM ==================================================================================
echo DEBUT > check_t1b.txt
echo === 1. MESURE T1b (#587) === >> check_t1b.txt
python tools\mesurer_t1b_inside.py >> check_t1b.txt 2>&1
echo. >> check_t1b.txt
echo === 2. SUITE COMPLETE === >> check_t1b.txt
python -m pytest -q -p no:cacheprovider --tb=short >> check_t1b.txt 2>&1
echo. >> check_t1b.txt
echo === 3. SAFETY (no-real-trade) === >> check_t1b.txt
python -m hl_observer safety-audit >> check_t1b.txt 2>&1
echo FIN >> check_t1b.txt
exit /b 0
