@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   131 : la CAPACITE d'executer un ordre reel n'est PAS installee.
REM   130 : une pierre tombale ne peut citer qu'un remplacant VIVANT.
REM   ASCII PUR, pas de pause -> check_130_131.txt
REM ==================================================================================
echo DEBUT > check_130_131.txt
echo === 1 sur 3 : aucun paquet capable d executer === >> check_130_131.txt
python -m pytest -q --tb=short -p no:cacheprovider tests\test_dependances_execution.py >> check_130_131.txt 2>&1
echo. >> check_130_131.txt
echo === 2 sur 3 : les tombes citent-elles des remplacants VIVANTS === >> check_130_131.txt
python -m pytest -q --tb=short -p no:cacheprovider tests\test_tombes_remplacants_vivants.py >> check_130_131.txt 2>&1
echo. >> check_130_131.txt
echo === 3 sur 3 : safety-audit complet === >> check_130_131.txt
python -m hl_observer safety-audit >> check_130_131.txt 2>&1
echo FIN >> check_130_131.txt
exit /b 0
