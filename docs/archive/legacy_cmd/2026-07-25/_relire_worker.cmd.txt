@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   LE TRAVAILLEUR DU MODE RELIRE  (lance par RELIRE-LA-MOISSON.cmd)
REM
REM   Il NE RE-SCANNE PAS. Il reprend les depots deja trouves (data\reports\
REM   moisson_10h_etat.json) et les RELIT intelligemment : les depots de NOTRE
REM   domaine d'abord, puis il ouvre le code des meilleurs. Rentabilise un scan
REM   deja fait sans attendre 8 h de plus.
REM
REM   Son journal detaille va dans moisson_console.txt. A la fin -> moisson-termine.flag.
REM ==================================================================================
python tools\moissonner_10h.py --heures 3 --relire > "%~dp0moisson_console.txt" 2>&1
echo done> "%~dp0moisson-termine.flag"
exit /b 0
