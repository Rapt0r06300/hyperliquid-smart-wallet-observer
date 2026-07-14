@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   TEST-T1 - le moteur de verdict SANS le nombre invente.
REM   ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py).
REM   Lecture seule. Aucun ordre, aucune cle.
REM ==================================================================================
echo.
echo =============================================================
echo   TEST-T1 - trancher sans le "10 %% du flux" invente
echo =============================================================
echo.
echo [1/3] Les bornes de file + l'IC bootstrap
python -m pytest -q --tb=short -p no:cacheprovider ^
  tests\test_market_making_bornes_de_file.py
echo.
echo [2/3] Non-regression : les tests MM existants (recorder inclus)
python -m pytest -q --tb=short -p no:cacheprovider ^
  tests\test_market_making_flow.py
echo.
echo [3/3] Verdict a blanc sur la donnee DEJA captee (l'ecoute 4h continue en parallele)
python tools\mesurer_flux_market_making.py --verdict-seulement --inclure KAITO
echo.
pause
