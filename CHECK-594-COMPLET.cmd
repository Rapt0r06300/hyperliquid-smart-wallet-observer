@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #594 -- LA SUITE COMPLETE. Une sous-suite verte a deja cache 8 rouges (G2, 13/07).
REM   ASCII PUR, pas de pause -> check_594_complet.txt
REM ==================================================================================
echo DEBUT > check_594_complet.txt
echo === LA SUITE COMPLETE (rien ne se cache) === >> check_594_complet.txt
python -m pytest -q --tb=line -p no:cacheprovider tests >> check_594_complet.txt 2>&1
echo. >> check_594_complet.txt
echo === safety-audit === >> check_594_complet.txt
python -m hl_observer safety-audit >> check_594_complet.txt 2>&1
echo === doctor === >> check_594_complet.txt
python -m hl_observer doctor >> check_594_complet.txt 2>&1
echo FIN >> check_594_complet.txt
exit /b 0
