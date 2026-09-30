@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   T3 - AUDIT DE CABLAGE, version SANS PAUSE (le cmd est tier-click : on ne peut pas
REM   lui envoyer de touche, un `pause` bloquerait la boucle).
REM
REM   Regenere data/reports/audit_cablage.json avec le filtre CORRIGE (T3c) : l'ancien
REM   filtrait par SOUS-CHAINE et effacait tout le paquet de production
REM   src/hl_observer/runtime/ -- 8 modules invisibles, dont le hot path.
REM
REM   ASCII PUR, pas de "chcp". Lecture seule. Aucun ordre, aucune cle, aucune signature.
REM ==================================================================================
(
  python tools\auditer_cablage.py
  echo.
  echo === registre des flags ===
  python tools\gen_config_flags.py
) > "%~dp0rapports\t3_cablage.txt" 2>&1
exit /b 0
