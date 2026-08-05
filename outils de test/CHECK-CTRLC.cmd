@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   L'INVARIANT anti-Ctrl-C : un outil qui lance pytest ne doit pas mourir de son
REM   Ctrl-C. Rapide. ASCII PUR, pas de pause -> "%~dp0rapports\check_ctrlc.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_ctrlc.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_outils_isoles_du_ctrl_c.py >> "%~dp0rapports\check_ctrlc.txt" 2>&1
echo. >> "%~dp0rapports\check_ctrlc.txt"
echo === non-regression des outils (megatest / audit_report modifies) === >> "%~dp0rapports\check_ctrlc.txt"
python -c "import ast,pathlib;[ast.parse(pathlib.Path(p).read_text(encoding='utf-8',errors='replace')) for p in ['tools/megatest.py','tools/audit_report.py','tools/couverture_de_lignes.py','tools/sous_processus_isole.py']];print('les 4 outils compilent')" >> "%~dp0rapports\check_ctrlc.txt" 2>&1
echo FIN >> "%~dp0rapports\check_ctrlc.txt"
exit /b 0
