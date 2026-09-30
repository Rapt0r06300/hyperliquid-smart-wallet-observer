@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM  Diagnostic : un VRAI run tres court (~90 s) pour voir s'il "saute" ou "bug".
REM  Tout (stdout + stderr + traceback) va dans le rapport. Aucune cle -> 60 req/h,
REM  mais assez pour exercer canari + index + phase A + production du .md.
python -X faulthandler tools\moissonner_10h.py --heures 0.07 --repartir-de-zero > "%~dp0rapports\run_court_diag.txt" 2>&1
echo ---- CODE DE SORTIE : %errorlevel% ---- >> "%~dp0rapports\run_court_diag.txt"
exit /b 0
