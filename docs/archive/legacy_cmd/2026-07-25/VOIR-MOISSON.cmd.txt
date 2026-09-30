@echo off
REM ==================================================================================
REM   VOIR LA MOISSON  --  tableau de bord SANS CLIGNOTEMENT ni SAUT
REM
REM   Double-clique ce fichier a tout moment (meme pendant que la moisson tourne).
REM   Il redessine EXACTEMENT la hauteur de la fenetre a chaque fois : il ne peut donc
REM   pas defiler -> plus de clignotement, plus de "saut", plus de "ca remonte".
REM   Fermer cette fenetre n'arrete RIEN.  Il ne fait que LIRE moisson-en-cours.txt.
REM ==================================================================================
title Tableau de bord - Moisson
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\voir_dashboard.ps1" -Root "%~dp0"
echo.
pause
