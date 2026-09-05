@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   TOUT-VERIFIER ? **le point d'entree unique** des outils qui comptent ENCORE.
REM
REM   Flo demandait de ? fusionner les tous ?. Je ne fusionne PAS les 104 :
REM   la plupart sont des ENQUETES CLOSES (CHECK-59x, Q1-Q3, T1/T2/T3, H181...).
REM   Les relancer prendrait des heures pour un mur de texte sans valeur.
REM   ***Un script qui fait tout ne dit plus rien.***
REM
REM   -> celui-ci lance les 8 verifications VIVANTES, dans l'ordre.
REM      Les autres restent la, classees ? enquete close ? (voir README.md).
REM
REM   Lecture seule. Paper-only. ASCII PUR, pas de pause.
REM ==================================================================================

echo.
echo ============ 1/8  SECURITE : 0 ordre reel, 0 cle, 0 signature ============
call "%~dp0CHECK-SAFETY.cmd"
echo.
echo ============ 2/8  les garde-fous sont-ils DANS la porte ? (audit AST) ============
call "%~dp0VERIFIER-BRANCHEMENTS.cmd"
echo.
echo ============ 3/8  tous les leviers pour ouvrir plus -- calcules, pas opines ============
call "%~dp0LES-LEVIERS.cmd"
echo.
echo ============ 4/8  le carnet porte-t-il notre taille ? (4 jambes) ============
call "%~dp0LA-PROFONDEUR.cmd"
echo.
echo ============ 5/8  nos carrys battent-ils un depot passif dans HLP ? ============
call "%~dp0LE-VERDICT.cmd"
echo.
echo ============ 6/8  la couverture REELLE des tests ============
call "%~dp0COUVERTURE-LIGNES.cmd"
echo.
echo ============ 7/8  l'etat des taches ============
call "%~dp0VERIFIER-TASKLIST.cmd"
echo.
echo ============ 8/8  ce que le projet a appris ============
call "%~dp0CONSULTER-MEMOIRE.cmd"

echo.
echo ==================================================================================
echo   TERMINE. Chaque rapport est dans : outils de test\rapports\
echo   SECURITE : 0 ordre reel - 0 argent reel - 0 cle privee - 0 signature
echo ==================================================================================
exit /b 0
