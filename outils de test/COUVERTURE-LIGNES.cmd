@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #596 -- LA VRAIE COUVERTURE : celle des LIGNES EXECUTEES.
REM
REM   ATTENTION : relance TOUTE la suite sous `coverage`. Compter PLUSIEURS MINUTES.
REM   Ne pas fermer la fenetre : le cliquet ne s'ecrit qu'a la fin.
REM
REM   A lire A COTE de tools/couverture_baseline.json (#121), qui mesure seulement
REM   « importe par un test » -- une borne OPTIMISTE. Deux chiffres, deux questions.
REM   ASCII PUR, pas de pause -> "%~dp0rapports\couverture_lignes.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\couverture_lignes.txt"
python tools\couverture_de_lignes.py >> "%~dp0rapports\couverture_lignes.txt" 2>&1
echo FIN >> "%~dp0rapports\couverture_lignes.txt"
exit /b 0
