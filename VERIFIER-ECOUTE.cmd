@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   VERIFIER-ECOUTE - chercher la panne AVANT qu'elle ne coute la nuit.
REM   ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py).
REM   Lecture seule : il ne repare rien, il CRIE.
REM ==================================================================================
python -m pytest -q --tb=short -p no:cacheprovider tests\test_verifier_ecoute.py
echo.
python tools\verifier_ecoute.py
pause
