@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   FALSIFIER-CASHCAT - essayer de DETRUIRE le seul candidat positif du projet.
REM   ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py).
REM
REM   Un resultat positif est une raison de DOUBLER la severite, pas de se rejouir.
REM   Deux attaques : la file est-elle atteignable ? le markout tient-il dans le temps ?
REM
REM   Lecture seule. Aucun ordre, aucune cle, aucune signature.
REM ==================================================================================
python tools\falsifier_cashcat.py %1 > falsification.txt 2>&1
type falsification.txt
pause
