@echo off
REM ============================================================================
REM  TOUT-TESTER — LE SEUL fichier a lancer
REM ============================================================================
REM  Tu double-cliques ICI, tu vas boire un cafe, et a la fin tu as UN fichier
REM  qui dit tout : RECAP-COMPLET.md (a la racine du projet).
REM
REM  OPTIONS :
REM    --aide                 la liste des options, puis on sort
REM    --rapide               saute la recherche de pepites, environ 10 min
REM    --tests-seulement      securite, pytest et invariants, environ 5 min
REM    --securite-seulement   uniquement l'audit no-real-trade, environ 30 s
REM    --sans-pause           ne demande pas d'appuyer sur une touche a la fin
REM    --ouvrir               ouvre le RECAP a la fin
REM    --forcer               ignore un verrou laisse par un run mort
REM
REM  Compte environ 1 h en mode complet. 100%% lecture seule.
REM ============================================================================
REM
REM  POURQUOI CE FICHIER EST SI COURT (21/07)
REM  ----------------------------------------
REM  Il a d'abord fait 365 lignes : les 40 ameliorations du lanceur ecrites
REM  directement en batch. Elles ont ete ecrites depuis un environnement ou
REM  elles ne pouvaient PAS etre executees. Au premier lancement : plantage,
REM  et deux fichiers parasites vides crees a la racine du projet.
REM
REM  Cause : dans cmd, le signe egal est un DELIMITEUR de token. Un chevron
REM  fermant suivi d'un signe egal, ecrit dans un commentaire ou dans un
REM  python -c, est donc lu comme une REDIRECTION vers le token suivant. C'est
REM  ainsi qu'ont ete crees un fichier nomme 3.10 et un fichier nomme (3.
REM  Le script est mort avant meme d'avoir cree son dossier de logs : aucune
REM  trace, aucun RECAP.
REM
REM  Ce commentaire lui-meme ne contient donc AUCUN chevron : un test le verifie,
REM  et il m'a attrape en ecrivant cette explication.
REM
REM  Regle du projet : la verite c'est Windows, pas le sandbox. Du code qui ne
REM  peut pas etre execute ne doit pas porter de logique. Les 40 ameliorations
REM  vivent donc dans tools\lanceur_tout_tester.py, ou chacune a son test.
REM
REM  Ce fichier ne garde que ce qui DOIT etre du batch : encodage de la console,
REM  variables d'environnement, appel, code de sortie. Aucune parenthese, aucun
REM  for /f, aucun signe de redirection dans un commentaire.
REM ============================================================================
setlocal
chcp 65001 >nul 2>&1
cd /d "%~dp0"

set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONUNBUFFERED=1"
set "HYPERSMART_READ_ONLY=1"
set "HYPERSMART_PAPER_ONLY=1"

title TOUT-TESTER

where python >nul 2>&1
if errorlevel 1 goto :pas_de_python

python "%~dp0tools\lanceur_tout_tester.py" %*
set "CODE=%ERRORLEVEL%"
title TOUT-TESTER — termine
endlocal & exit /b %CODE%

:pas_de_python
echo.
echo   ARRET : "python" est introuvable dans le PATH.
echo   Installe Python 3.10 ou plus recent, puis relance ce fichier.
echo.
pause
exit /b 3
