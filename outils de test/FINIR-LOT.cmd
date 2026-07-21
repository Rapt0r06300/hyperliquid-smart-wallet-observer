@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   LOT #242 / #249 / #250 / #251 / #254
REM     1. cointegration MESUREE sur donnees reelles (#242)
REM     2. mutation testing : « un garde-fou qui ne peut pas echouer ne garde rien » (#250)
REM     3. suite COMPLETE + safety (la ciblee cache des rouges -- lecon G2)
REM   ASCII PUR, pas de pause -> "%~dp0rapports\finir_lot.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\finir_lot.txt"

echo === 1. COINTEGRATION MESUREE (#242) === >> "%~dp0rapports\finir_lot.txt"
python tools\mesurer_cointegration.py >> "%~dp0rapports\finir_lot.txt" 2>&1

echo. >> "%~dp0rapports\finir_lot.txt"
echo === 2. MUTATION TESTING (#250) === >> "%~dp0rapports\finir_lot.txt"
python tools\muter.py --max-par-fichier 10 >> "%~dp0rapports\finir_lot.txt" 2>&1

echo. >> "%~dp0rapports\finir_lot.txt"
echo === 3. SUITE COMPLETE === >> "%~dp0rapports\finir_lot.txt"
python -m pytest -q -p no:cacheprovider --tb=short >> "%~dp0rapports\finir_lot.txt" 2>&1

echo. >> "%~dp0rapports\finir_lot.txt"
echo === 4. SAFETY (no-real-trade) === >> "%~dp0rapports\finir_lot.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\finir_lot.txt" 2>&1

echo FIN >> "%~dp0rapports\finir_lot.txt"
exit /b 0
