@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #131 -- la CAPACITE d'executer un ordre reel n'est PAS installee.
REM   #130 -- une pierre tombale ne peut citer qu'un remplacant VIVANT (joignable + allume).
REM   ASCII PUR, pas de pause -> "%~dp0rapports\improve_130_131.txt"
REM ==================================================================================
(
  echo === [1/3] #131 : aucun paquet capable d'executer ===
  python -m pytest -q --tb=short -p no:cacheprovider tests\test_dependances_execution.py
  echo.
  echo === [2/3] #130 : les tombes citent-elles des remplacants VIVANTS ? ===
  python -m pytest -q --tb=short -p no:cacheprovider tests\test_tombes_remplacants_vivants.py
  echo.
  echo === [3/3] safety-audit COMPLET (le 8e controle doit apparaitre) ===
  python -m hl_observer safety-audit
) > "%~dp0rapports\improve_130_131.txt" 2>&1
exit /b 0
