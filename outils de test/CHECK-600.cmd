@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #600 -- os.kill(pid, 0) EST UN CTRL-C SOUS WINDOWS (signal 0 == CTRL_C_EVENT).
REM   LA PREUVE : si ce fichier contient les 3 sections JUSQU'A "FIN", le Ctrl-C n'a
REM   pas eu lieu -- car avant, il TUAIT ce .cmd juste apres pytest.
REM   ASCII PUR, pas de pause -> "%~dp0rapports\check_600.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_600.txt"
echo === 1. l'invariant + le comportement de parent_alive === >> "%~dp0rapports\check_600.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_aucun_ctrl_c_deguise_en_test_d_existence.py tests\test_runtime_guards.py tests\test_outils_isoles_du_ctrl_c.py >> "%~dp0rapports\check_600.txt" 2>&1
echo. >> "%~dp0rapports\check_600.txt"
echo === 2. LA SUITE COMPLETE (doit aller au bout SANS Ctrl-C) === >> "%~dp0rapports\check_600.txt"
python -m pytest -q --tb=line -p no:cacheprovider tests >> "%~dp0rapports\check_600.txt" 2>&1
echo. >> "%~dp0rapports\check_600.txt"
echo === 3. safety-audit (ne s'executait PLUS depuis 2 jours : le Ctrl-C tuait le .cmd ici) === >> "%~dp0rapports\check_600.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\check_600.txt" 2>&1
echo. >> "%~dp0rapports\check_600.txt"
echo === 4. doctor === >> "%~dp0rapports\check_600.txt"
python -m hl_observer doctor >> "%~dp0rapports\check_600.txt" 2>&1
echo FIN >> "%~dp0rapports\check_600.txt"
exit /b 0
