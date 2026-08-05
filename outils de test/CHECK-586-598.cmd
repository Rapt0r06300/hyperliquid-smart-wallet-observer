@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #586 (H-181) : le bug de signe est-il corrige ? + la mesure REJOUEE.
REM   #598          : QUI refuse le cluster frais ? (on LIT le motif)
REM   ASCII PUR, pas de pause -> "%~dp0rapports\check_586_598.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_586_598.txt"
echo === 1 sur 3 : H-181 -- le bug de SIGNE est-il verrouille ? === >> "%~dp0rapports\check_586_598.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_overfit_selection.py >> "%~dp0rapports\check_586_598.txt" 2>&1
echo. >> "%~dp0rapports\check_586_598.txt"
echo === 2 sur 3 : la MESURE rejouee avec le verdict corrige === >> "%~dp0rapports\check_586_598.txt"
python tools\h181_malediction_du_vainqueur.py >> "%~dp0rapports\check_586_598.txt" 2>&1
echo. >> "%~dp0rapports\check_586_598.txt"
echo === 3 sur 3 : #598 -- QUI refuse ? === >> "%~dp0rapports\check_586_598.txt"
python -m pytest -q -s --tb=short -p no:cacheprovider tests\test_diag_598_qui_refuse.py >> "%~dp0rapports\check_586_598.txt" 2>&1
echo FIN >> "%~dp0rapports\check_586_598.txt"
exit /b 0
