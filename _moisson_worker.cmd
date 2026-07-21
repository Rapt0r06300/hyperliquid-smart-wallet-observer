@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   LE TRAVAILLEUR DE LA MOISSON  (lance par LANCER-MOISSON-12H.cmd)
REM
REM   Cette fenetre fait le vrai travail pendant 12 h. Elle est reduite : tu n'as
REM   PAS besoin de la regarder -- le tableau de bord est dans l'autre fenetre.
REM   NE FERME PAS cette fenetre (sauf pour arreter la moisson).
REM
REM   Son journal detaille va dans moisson_console.txt.
REM   Quand elle a fini, elle cree moisson-termine.flag (le tableau de bord s'arrete).
REM ==================================================================================
python tools\moissonner_10h.py --heures 12 > "%~dp0moisson_console.txt" 2>&1
echo done> "%~dp0moisson-termine.flag"
exit /b 0
