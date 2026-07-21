@echo off
REM ============================================================================
REM  TOUT-TESTER — LE SEUL fichier a lancer (21/07)
REM ============================================================================
REM  Tu double-cliques ICI, tu vas boire un cafe, et a la fin tu as UN fichier
REM  qui dit tout : RECAP-COMPLET.md (a la racine du projet).
REM
REM  LES 6 ETAPES, DANS L'ORDRE :
REM    1. SECURITE        0 ordre reel possible (la barriere non negociable)
REM    2. TESTS           la suite pytest COMPLETE (~800 fichiers) = la verite du code
REM    3. CABLAGE         modules cables / testes-seulement / orphelins
REM    4. DONNEES         qualite du replay (etiquetage, couverture, doublons, prix)
REM    5. RECHERCHE       pepites par module (carry, copy, arbitrage, cross-venue)
REM    6. SANTE LIVE      moteur, collecteurs, positions, mesures en cours
REM
REM  BON A SAVOIR :
REM    - une etape qui plante n'arrete PAS les suivantes (son verdict = ERREUR) ;
REM    - chaque etape a un budget : un test qui pend ne mange plus la soiree ;
REM    - RECAP-COMPLET.md est ecrit A LA FIN QUOI QU'IL ARRIVE (meme apres Ctrl-C) ;
REM    - option RAPIDE : "TOUT-TESTER.cmd --rapide" saute la recherche de pepites
REM      (l'etape la plus longue) -> ~10 min au lieu de ~1 h.
REM
REM  Compte ~1 h en mode complet. 100%% lecture seule : 0 ordre reel, 0 cle.
REM ============================================================================
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
title TOUT-TESTER — HyperSmart Observer

echo.
echo   ============================================================
echo     TOUT-TESTER : securite, tests, cablage, donnees,
echo     recherche de pepites, sante live.
echo     A la fin : RECAP-COMPLET.md
echo   ============================================================
echo.

python -m pip install -q pytest-timeout 2>nul
python tools\tout_tester.py %*
set "CODE=%ERRORLEVEL%"

echo.
if exist "RECAP-COMPLET.md" (
  echo   RECAP ecrit : %~dp0RECAP-COMPLET.md
  echo   ^(c'est CE fichier a envoyer a Claude^)
) else (
  echo   !! RECAP ABSENT : envoie CETTE fenetre a Claude.
)
if "%CODE%"=="0" (
  echo   TOUT EST VERT.
) else (
  echo   Des etapes ont echoue — le detail est dans le RECAP.
)
echo.
pause
