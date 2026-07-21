@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   MEGATEST - LES 7 CONTROLES HYPERSMART EN UN SEUL PASSAGE
REM
REM   IMPORTANT : ce fichier est en ASCII PUR, et il n'y a PAS de "chcp".
REM   Un seul caractere non-ASCII (tiret cadratin, point median, accent) DECALE
REM   l'analyseur de cmd.exe : il perd des octets et tente d'EXECUTER des morceaux
REM   de lignes. Symptome vu le 2026-07-12 : "'5001' n'est pas reconnu" en boucle
REM   (c'est "chcp 65001" ampute de son 6). Bug reel, deja rencontre sur
REM   MOISSONNER-GITHUB.cmd. PYTHONIOENCODING + PYTHONUTF8 suffisent : pas de chcp.
REM
REM   Remplace, et rend obsoletes :
REM     TEST-AUDIT-complet.cmd   POURQUOI-ZERO-POSITION.cmd   MESURER_SEUIL_FUNDING.cmd
REM     MESURER-SPREAD-CARNET.cmd   MESURER-FLUX-MM.cmd   MESURER-CARRY-NEUTRE.cmd
REM     CONSULTER-MEMOIRE.cmd
REM
REM   SORTIE UNIQUE :  MEGATEST.md  (a la racine)
REM   Reecrit APRES CHAQUE SECTION, donc il existe meme si tu fais Ctrl-C.
REM
REM   USAGE
REM     MEGATEST.cmd --ci             AVANT DE COMMITER : audit du CODE seul.
REM                                   Aucun reseau requis. C'est LUI qui autorise le commit.
REM     MEGATEST.cmd                  rapide  : audit + toutes les mesures de marche courtes
REM     MEGATEST.cmd --fast           idem, audit sans 2e passe anti-flaky (le plus rapide)
REM     MEGATEST.cmd --complet        + ecoute du flux public 60 min (selection adverse MM)
REM     MEGATEST.cmd --minutes 240    + ecoute du flux public 240 min
REM
REM   ECHEC n'est PAS un VERDICT.
REM     ECHEC(code=N)   = le CODE est casse. Seul l'audit peut en produire un. NE PAS COMMITER.
REM     VERDICT(code=N) = le MARCHE a repondu non (ex: aucun carry viable). Ce n'est PAS une
REM                       panne, et ca n'interdit PAS de commiter.
REM
REM   Ctrl-C a tout moment : le rapport contient tout ce qui a ete mesure jusque-la.
REM
REM   100%% LECTURE SEULE.
REM   0 ordre reel, 0 argent reel, 0 cle privee, 0 signature, 0 depot/retrait.
REM ==================================================================================

REM Outils qui rendent l'audit robuste (best effort : sans reseau, ca passe quand meme).
python -m pip install -q pytest-timeout coverage 2>nul

python tools\megatest.py %*
set "CODE=%ERRORLEVEL%"

echo.
if exist "MEGATEST.md" (
  echo   Rapport unique : %~dp0MEGATEST.md
  echo   Envoie CE fichier a Claude : il contient les 7 controles.
) else (
  echo   ATTENTION : MEGATEST.md n'a pas ete ecrit. Copie l'erreur ci-dessus.
)

echo.
pause
exit /b %CODE%
