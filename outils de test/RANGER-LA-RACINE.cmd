@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   RANGER LA RACINE — 104 .cmd et 68 rapports noyaient les 6 fichiers qui comptent.
REM
REM   LE PIEGE QU'UN SIMPLE GLISSER-DEPOSER AURAIT DECLENCHE :
REM     chaque .cmd fait `cd /d "%~dp0.."` et cherche src\ A COTE DE LUI.
REM     Deplace tel quel, %~dp0 designe le NOUVEAU dossier -> 104 scripts CASSES.
REM   -> cet outil DEPLACE **ET REPARE** : cd, PYTHONPATH, chemin des rapports.
REM
REM   IL NE SUPPRIME RIEN. Un `move`, jamais un `delete`.
REM
REM   RESTENT A LA RACINE : LANCER_HYPERSMART, LANCER-TOUT, TEST-AUDIT-complet,
REM                         MOISSONNER-GITHUB (le moissonneur ne bouge PAS).
REM
REM   IL GENERE AUSSI :
REM     - `outils de test\TOUT-VERIFIER.cmd`  le point d'entree UNIQUE (8 verifs vivantes)
REM     - `outils de test\README.md`          l'index, EXTRAIT des en-tetes REM
REM                                           (un index ecrit a la main ment)
REM
REM   ASCII PUR, pas de pause -> ranger_racine.txt
REM ==================================================================================
python tools\ranger_racine.py > ranger_racine.txt 2>&1
REM  Le journal de CET outil ne peut pas se deplacer lui-meme pendant qu'il ecrit dedans
REM  (WinError 32). On le range ICI, une fois le handle ferme.
if exist "%~dp0..\outils de test\rapports\" move /y "%~dp0..\ranger_racine.txt" "%~dp0..\outils de test\rapports\" >nul 2>&1
exit /b 0
