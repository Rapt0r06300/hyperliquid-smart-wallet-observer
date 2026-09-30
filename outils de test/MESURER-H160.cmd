@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   H-160 / GH-02 -- LE BIAIS RECURSIF : nos features changent-elles selon la
REM   QUANTITE d'historique fournie ? (backtest = tout ; live = buffer borne)
REM   ASCII PUR, pas de pause -> "%~dp0rapports\mesure_h160.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\mesure_h160.txt"
echo === 1. les tests de la sonde (bornees=stables / recursives=instables) === >> "%~dp0rapports\mesure_h160.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_biais_recursif_h160.py >> "%~dp0rapports\mesure_h160.txt" 2>&1
echo. >> "%~dp0rapports\mesure_h160.txt"
echo === 2. LA MESURE sur les MIDS REELS === >> "%~dp0rapports\mesure_h160.txt"
python tools\mesurer_biais_recursif.py >> "%~dp0rapports\mesure_h160.txt" 2>&1
echo FIN >> "%~dp0rapports\mesure_h160.txt"
exit /b 0
