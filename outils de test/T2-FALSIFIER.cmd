@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   T2-FALSIFIER - essayer de DETRUIRE le carry delta-neutre avant d'y croire.
REM   ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py).
REM
REM   5 attaques : collision de ticker, funding REEL (pas modelise), la base comme
REM   RISQUE, le carnet spot REEL, et la liquidation de la jambe perp.
REM
REM   Lecture seule. Endpoints /info PUBLICS. Aucune cle, aucune signature, aucun ordre.
REM ==================================================================================
python tools\falsifier_carry.py > "%~dp0rapports\t2_falsification.txt" 2>&1
type t2_falsification.txt
pause
