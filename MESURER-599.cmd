@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #599 -- RE-MESURER la couverture sur la suite COMPLETE.
REM   Celle du 13/07 14:07 (83,83 %) a ete calculee sur une suite TRONQUEE a 70 % par
REM   le Ctrl-C fantome : 6 modules apparaissaient a 0 % alors que leurs tests
REM   n'avaient simplement jamais tourne. Une mesure fausse ne se trompe pas : elle ACCUSE.
REM   ASCII PUR, pas de pause -> mesure_599.txt
REM ==================================================================================
echo DEBUT > mesure_599.txt
echo === 1. le garde-fou anti-mesure-tronquee === >> mesure_599.txt
python -m pytest -q --tb=short -p no:cacheprovider tests\test_couverture_refuse_une_suite_tronquee.py >> mesure_599.txt 2>&1
echo. >> mesure_599.txt
echo === 2. LA MESURE (suite complete, ~5 min) === >> mesure_599.txt
python tools\couverture_de_lignes.py >> mesure_599.txt 2>&1
echo FIN >> mesure_599.txt
exit /b 0
