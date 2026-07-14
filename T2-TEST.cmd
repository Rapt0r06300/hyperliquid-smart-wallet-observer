@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   T2-TEST - le moteur du carry doit etre sain AVANT de trancher.
REM   ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py).
REM ==================================================================================
python -m pytest -q --tb=short -p no:cacheprovider ^
  tests\test_delta_neutral_carry.py ^
  tests\test_funding_carry_economics.py
pause
