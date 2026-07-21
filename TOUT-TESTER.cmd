@echo off
REM ============================================================================
REM  TOUT-TESTER -- LE SEUL fichier a lancer
REM ============================================================================
REM  Double-clic ici. A la fin : RECAP-COMPLET.md a la racine du projet.
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
REM  Environ 1 h en mode complet. 100%% lecture seule.
REM ============================================================================
REM
REM  POURQUOI CE FICHIER EST AUSSI DEPOUILLE (21/07)
REM  -----------------------------------------------
REM  Version 1 : 365 lignes de batch, ecrites depuis un environnement ou elles
REM  ne pouvaient PAS etre executees. Plantage, plus deux fichiers parasites
REM  vides crees a la racine -- dans cmd, le signe egal est un DELIMITEUR de
REM  token, donc un chevron fermant suivi d'un signe egal est lu comme une
REM  REDIRECTION, y compris dans un commentaire.
REM
REM  Version 2 : 24 lignes, mais avec goto, label, chcp et endlocal. Resultat :
REM  la fenetre se fermait instantanement, sans rien afficher. Le lanceur qui
REM  MARCHE chez Flo depuis des semaines, LANCER_HYPERSMART.cmd, n'a AUCUN des
REM  quatre. Avec des fins de ligne LF, la recherche de label d'un goto echoue
REM  et cmd sort en silence.
REM
REM  Version 3 (celle-ci) : on imite exactement ce qui fonctionne deja.
REM  Zero goto, zero label, zero chcp, zero endlocal, pur ASCII, fins de ligne
REM  CRLF, et une pause TOUJOURS atteinte -- une fenetre qui se ferme sans rien
REM  dire est le pire mode d'echec possible.
REM
REM  Toute la logique (les 40 ameliorations) vit dans le Python, ou elle est
REM  testee : tools\lanceur_tout_tester.py
REM ============================================================================

cd /d "%~dp0"

set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONUNBUFFERED=1"
set "HYPERSMART_READ_ONLY=1"
set "HYPERSMART_PAPER_ONLY=1"

title TOUT-TESTER

python "%~dp0tools\lanceur_tout_tester.py" %*

REM Si Python n'a meme pas demarre, le message ci-dessous est la seule trace
REM que Flo verra. Il ne doit donc JAMAIS etre saute.
if errorlevel 9009 echo.
if errorlevel 9009 echo   ARRET : "python" est introuvable dans le PATH.
if errorlevel 9009 echo   Installe Python 3.10 ou plus recent, puis relance.
if errorlevel 9009 echo.
if errorlevel 9009 pause

exit /b %ERRORLEVEL%
