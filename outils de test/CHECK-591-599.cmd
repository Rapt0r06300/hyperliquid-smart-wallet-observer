@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #591 -- le GARDE-FOU AFFAME : l'estimateur de vol n'etait nourri que si une
REM           position etait DEJA ouverte -- alors que le veto d'ENTREE le consomme.
REM   #599 -- les 16 % de lignes non executees : 97 modules a 0 % + cliquet.
REM   ASCII PUR, pas de pause -> "%~dp0rapports\check_591_599.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_591_599.txt"
echo === 1. #591 + #599 (cibles) === >> "%~dp0rapports\check_591_599.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_garde_fou_affame_591.py tests\test_v26_l2_vol_barriers.py tests\test_v26_l1_entry_vetos.py tests\test_v26_l3_to_l9.py tests\test_couverture_refuse_une_suite_tronquee.py tests\test_cliquet_modules_jamais_executes.py >> "%~dp0rapports\check_591_599.txt" 2>&1
echo. >> "%~dp0rapports\check_591_599.txt"
echo === 2. LA SUITE COMPLETE === >> "%~dp0rapports\check_591_599.txt"
python -m pytest -q --tb=line -p no:cacheprovider tests >> "%~dp0rapports\check_591_599.txt" 2>&1
echo. >> "%~dp0rapports\check_591_599.txt"
echo === 3. safety-audit === >> "%~dp0rapports\check_591_599.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\check_591_599.txt" 2>&1
echo FIN >> "%~dp0rapports\check_591_599.txt"
exit /b 0
