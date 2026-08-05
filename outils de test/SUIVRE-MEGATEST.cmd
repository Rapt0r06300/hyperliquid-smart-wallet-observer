@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   OBSERVATEUR DU MEGATEST - a lancer dans une 2e fenetre, PENDANT que le test tourne.
REM
REM   ASCII PUR, pas de chcp : un octet non-ASCII ferait executer les commentaires
REM   par cmd.exe (bug rencontre 3 fois, cf. tools/garde_cmd_ascii.py).
REM
REM   100%% LECTURE SEULE. Il n'ecrit rien, ne tue rien, ne parle a personne.
REM   Ctrl-C ici ferme SEULEMENT cette fenetre : le MEGATEST continue.
REM
REM   Il montre :
REM     - quelles sections sont terminees
REM     - ou en est l'audit (33 controles), avec une barre de progression
REM     - le temps restant estime, calcule sur les durees du passage precedent
REM ==================================================================================
python tools\suivre_megatest.py
pause
