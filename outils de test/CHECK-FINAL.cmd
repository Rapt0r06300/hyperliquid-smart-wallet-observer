@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   1) QUI est le 304e module mort ? (on ne releve pas le plafond, on l'identifie)
REM   2) Le defaut SL/TP n'est plus une perte garantie
REM   3) Les 2 tests UI + le cliquet de cablage
REM   ASCII PUR, pas de pause -> "%~dp0rapports\check_final.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_final.txt"
echo === 1 : QUI est le 304e mort === >> "%~dp0rapports\check_final.txt"
python tools\qui_est_le_304e_mort.py >> "%~dp0rapports\check_final.txt" 2>&1
echo. >> "%~dp0rapports\check_final.txt"
echo === 2 : le defaut SL/TP est-il jouable ? === >> "%~dp0rapports\check_final.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_defaut_sltp_pas_perdant.py >> "%~dp0rapports\check_final.txt" 2>&1
echo. >> "%~dp0rapports\check_final.txt"
echo === 3 : les 2 tests UI + le cliquet de cablage === >> "%~dp0rapports\check_final.txt"
python -m pytest -q --tb=line -p no:cacheprovider tests\test_ui_simulation_persistence.py tests\test_ui_simulation_v9_filters.py tests\test_risk_guards_no_limbo.py >> "%~dp0rapports\check_final.txt" 2>&1
echo FIN >> "%~dp0rapports\check_final.txt"
exit /b 0
