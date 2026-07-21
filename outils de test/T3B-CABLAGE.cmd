@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   T3B - meme audit que T3-CABLAGE, mais SANS pause : tout va dans t3_cablage.txt.
REM   ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py).
REM   Lecture seule. Aucun ordre, aucune cle, aucune signature.
REM ==================================================================================
(
  echo === [0/3] fichiers illisibles ===
  python tools\pourquoi_illisible.py
  echo.
  echo === [1/3] tests de l'auditeur ===
  python -m pytest -q --tb=short -p no:cacheprovider tests\test_audit_cablage.py
  echo.
  echo === [2/3] audit du depot ===
  python tools\auditer_cablage.py
  echo.
  echo === [3/3] registre des flags ===
  python tools\gen_config_flags.py
) > "%~dp0rapports\t3_cablage.txt" 2>&1
exit /b 0
