@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #587 / T1b -- coter DANS le spread : la derniere porte ouverte du market making.
REM   Mesure + suite COMPLETE + safety. ASCII PUR, pas de pause -> "%~dp0rapports\check_t1b.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_t1b.txt"
echo === 1. MESURE T1b (#587) === >> "%~dp0rapports\check_t1b.txt"
python tools\mesurer_t1b_inside.py >> "%~dp0rapports\check_t1b.txt" 2>&1
echo. >> "%~dp0rapports\check_t1b.txt"
echo === 2. SUITE COMPLETE === >> "%~dp0rapports\check_t1b.txt"
python -m pytest -q -p no:cacheprovider --tb=short >> "%~dp0rapports\check_t1b.txt" 2>&1
echo. >> "%~dp0rapports\check_t1b.txt"
echo === 3. SAFETY (no-real-trade) === >> "%~dp0rapports\check_t1b.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\check_t1b.txt" 2>&1
echo FIN >> "%~dp0rapports\check_t1b.txt"
exit /b 0
