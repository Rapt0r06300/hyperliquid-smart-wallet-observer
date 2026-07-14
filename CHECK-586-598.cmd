@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #586 (H-181) : le bug de signe est-il corrige ? + la mesure REJOUEE.
REM   #598          : QUI refuse le cluster frais ? (on LIT le motif)
REM   ASCII PUR, pas de pause -> check_586_598.txt
REM ==================================================================================
echo DEBUT > check_586_598.txt
echo === 1 sur 3 : H-181 -- le bug de SIGNE est-il verrouille ? === >> check_586_598.txt
python -m pytest -q --tb=short -p no:cacheprovider tests\test_overfit_selection.py >> check_586_598.txt 2>&1
echo. >> check_586_598.txt
echo === 2 sur 3 : la MESURE rejouee avec le verdict corrige === >> check_586_598.txt
python tools\h181_malediction_du_vainqueur.py >> check_586_598.txt 2>&1
echo. >> check_586_598.txt
echo === 3 sur 3 : #598 -- QUI refuse ? === >> check_586_598.txt
python -m pytest -q -s --tb=short -p no:cacheprovider tests\test_diag_598_qui_refuse.py >> check_586_598.txt 2>&1
echo FIN >> check_586_598.txt
exit /b 0
