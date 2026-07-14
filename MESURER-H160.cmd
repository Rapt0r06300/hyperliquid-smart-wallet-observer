@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   H-160 / GH-02 -- LE BIAIS RECURSIF : nos features changent-elles selon la
REM   QUANTITE d'historique fournie ? (backtest = tout ; live = buffer borne)
REM   ASCII PUR, pas de pause -> mesure_h160.txt
REM ==================================================================================
echo DEBUT > mesure_h160.txt
echo === 1. les tests de la sonde (bornees=stables / recursives=instables) === >> mesure_h160.txt
python -m pytest -q --tb=short -p no:cacheprovider tests\test_biais_recursif_h160.py >> mesure_h160.txt 2>&1
echo. >> mesure_h160.txt
echo === 2. LA MESURE sur les MIDS REELS === >> mesure_h160.txt
python tools\mesurer_biais_recursif.py >> mesure_h160.txt 2>&1
echo FIN >> mesure_h160.txt
exit /b 0
