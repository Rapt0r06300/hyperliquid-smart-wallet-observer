@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #598 -- QUI refuse le cluster frais ? On LIT le motif, on ne le devine pas.
REM   ASCII PUR, pas de pause -> diag_598.txt
REM ==================================================================================
echo DEBUT > diag_598.txt
python -m pytest -q -s --tb=short -p no:cacheprovider tests\test_diag_598_qui_refuse.py >> diag_598.txt 2>&1
echo FIN >> diag_598.txt
exit /b 0
