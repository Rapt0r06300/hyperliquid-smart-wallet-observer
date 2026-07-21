@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   H-181 (#586) -- LA MESURE SUR LES VRAIES DONNEES, SEULE.
REM
REM   Le 13/07 a 14:20, cette mesure est morte sur un "^C" -- exactement le bug du
REM   Ctrl-C de pytest qui remonte a TOUTE la console. L'ancien H181-VAINQUEUR.cmd
REM   lancait pytest JUSTE AVANT : le Ctrl-C de pytest tuait la mesure qui suivait.
REM   Ici : AUCUN pytest devant. Rien ne peut plus la tuer.
REM
REM   Lecture seule. Aucun ordre, aucune cle, aucune signature.
REM   ASCII PUR, pas de pause -> "%~dp0rapports\h181_mesure.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\h181_mesure.txt"
python tools\h181_malediction_du_vainqueur.py >> "%~dp0rapports\h181_mesure.txt" 2>&1
echo FIN >> "%~dp0rapports\h181_mesure.txt"
exit /b 0
