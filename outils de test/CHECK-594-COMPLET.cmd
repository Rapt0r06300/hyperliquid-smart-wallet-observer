@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #594 -- LA SUITE COMPLETE. Une sous-suite verte a deja cache 8 rouges (G2, 13/07).
REM   ASCII PUR, pas de pause -> "%~dp0rapports\check_594_complet.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_594_complet.txt"
echo === LA SUITE COMPLETE (rien ne se cache) === >> "%~dp0rapports\check_594_complet.txt"
python -m pytest -q --tb=line -p no:cacheprovider tests >> "%~dp0rapports\check_594_complet.txt" 2>&1
echo. >> "%~dp0rapports\check_594_complet.txt"
echo === safety-audit === >> "%~dp0rapports\check_594_complet.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\check_594_complet.txt" 2>&1
echo === doctor === >> "%~dp0rapports\check_594_complet.txt"
python -m hl_observer doctor >> "%~dp0rapports\check_594_complet.txt" 2>&1
echo FIN >> "%~dp0rapports\check_594_complet.txt"
exit /b 0
