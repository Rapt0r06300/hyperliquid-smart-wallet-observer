@echo off
REM ==================================================================================
REM   ci_local.cmd  ->  MEGATEST.cmd --ci
REM
REM   Ce script ne faisait DEJA que rediriger vers l'audit. Tout est desormais dans
REM   MEGATEST, avec une distinction qui manquait et qui compte :
REM
REM       --ci   = uniquement l'AUDIT DU CODE (bloquant, sans reseau).
REM                C'est ce que tu veux AVANT DE COMMITER.
REM
REM       (sans) = audit + toutes les mesures de marche (funding, carnet, carry...).
REM                C'est ce que tu veux pour SAVOIR OU EN EST LE BOT.
REM
REM   Un marche qui repond "non" n'est PAS une raison de bloquer un commit.
REM   MEGATEST le distingue maintenant : ECHEC (code casse) vs VERDICT (marche defavorable).
REM
REM   Sortie unique : MEGATEST.md a la racine.
REM
REM   100%% LECTURE SEULE. 0 ordre reel - 0 argent reel - 0 cle privee - 0 signature.
REM ==================================================================================
echo.
echo   La CI locale fait desormais partie de MEGATEST :
echo.
echo       MEGATEST.cmd --ci        (audit du code seul, avant commit)
echo       MEGATEST.cmd             (audit + mesures de marche)
echo.
echo   Lancement de l'audit du code...
echo.
call "%~dp0..\MEGATEST.cmd" --ci %*
exit /b %ERRORLEVEL%
