@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   131 : la CAPACITE d'executer un ordre reel n'est PAS installee.
REM   130 : une pierre tombale ne peut citer qu'un remplacant VIVANT.
REM   ASCII PUR, pas de pause -> "%~dp0rapports\check_130_131.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_130_131.txt"
echo === 1 sur 3 : aucun paquet capable d executer === >> "%~dp0rapports\check_130_131.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_dependances_execution.py >> "%~dp0rapports\check_130_131.txt" 2>&1
echo. >> "%~dp0rapports\check_130_131.txt"
echo === 2 sur 3 : les tombes citent-elles des remplacants VIVANTS === >> "%~dp0rapports\check_130_131.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_tombes_remplacants_vivants.py >> "%~dp0rapports\check_130_131.txt" 2>&1
echo. >> "%~dp0rapports\check_130_131.txt"
echo === 3 sur 3 : safety-audit complet === >> "%~dp0rapports\check_130_131.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\check_130_131.txt" 2>&1
echo FIN >> "%~dp0rapports\check_130_131.txt"
exit /b 0
