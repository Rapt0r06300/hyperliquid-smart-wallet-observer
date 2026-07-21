@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   T3b - BRANCHER ou ENTERRER les 21 gardes-fous de risk/. Rien dans l'entre-deux.
REM   ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py). Sans pause : tout va
REM   dans t3b_gardes.txt (le cmd est tier-click, on ne peut pas lui envoyer de touche).
REM
REM   Lecture seule. Aucun ordre, aucune cle, aucune signature.
REM ==================================================================================
(
  echo === [1/3] L'invariant : aucun garde-fou dans l'entre-deux ===
  python -m pytest -q --tb=short -p no:cacheprovider tests\test_risk_guards_no_limbo.py
  echo.
  echo === [2/3] Non-regression du moteur d'audit ===
  python -m pytest -q --tb=short -p no:cacheprovider tests\test_audit_cablage.py
  echo.
  echo === [3/3] Les gardes-fous existants ne doivent pas casser ===
  python -m pytest -q --tb=short -p no:cacheprovider tests\test_directional_exposure.py tests\test_no_real_trade_foundations.py
) > "%~dp0rapports\t3b_gardes.txt" 2>&1
exit /b 0
