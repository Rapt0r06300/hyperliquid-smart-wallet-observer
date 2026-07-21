@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #601 -- les 5 rouges que la suite COMPLETE a enfin criees (le Ctrl-C la coupait
REM   a 70 %, donc 1270 tests n'avaient JAMAIS tourne).
REM     1. l'invariant #600 attrapait MON PROPRE repli POSIX  -> code restructure
REM     2/3. test_strict_md tirait sur la 2e table (debranchee par #594) -> porte Q1
REM     4/5. test_v9_bias exigeait qu'un biais INVENTE deplace un edge MESURE -> refuse
REM   ASCII PUR, pas de pause -> "%~dp0rapports\check_601.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_601.txt"
echo === 1. les 4 fichiers reecrits === >> "%~dp0rapports\check_601.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_aucun_ctrl_c_deguise_en_test_d_existence.py tests\test_runtime_guards.py tests\test_strict_md_accept_path.py tests\test_v9_scorer_bias_wiring.py >> "%~dp0rapports\check_601.txt" 2>&1
echo. >> "%~dp0rapports\check_601.txt"
echo === 2. LA SUITE COMPLETE (doit finir SANS Ctrl-C et SANS rouge) === >> "%~dp0rapports\check_601.txt"
python -m pytest -q --tb=line -p no:cacheprovider tests >> "%~dp0rapports\check_601.txt" 2>&1
echo. >> "%~dp0rapports\check_601.txt"
echo === 3. safety-audit === >> "%~dp0rapports\check_601.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\check_601.txt" 2>&1
echo. >> "%~dp0rapports\check_601.txt"
echo === 4. doctor === >> "%~dp0rapports\check_601.txt"
python -m hl_observer doctor >> "%~dp0rapports\check_601.txt" 2>&1
echo FIN >> "%~dp0rapports\check_601.txt"
exit /b 0
