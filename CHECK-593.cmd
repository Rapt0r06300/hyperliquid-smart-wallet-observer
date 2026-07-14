@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   T3e (#593) -- P4/P5 : le coeur n'est appele par PERSONNE.
REM   L'invariant « brancher ou enterrer » etendu a runtime/.
REM   ASCII PUR, pas de pause -> check_593.txt
REM ==================================================================================
echo DEBUT > check_593.txt
echo === l'invariant runtime (montre les LIMBES s'il y en a) === >> check_593.txt
python -m pytest -q --tb=long -p no:cacheprovider tests\test_runtime_no_limbo.py >> check_593.txt 2>&1
echo FIN >> check_593.txt
exit /b 0
