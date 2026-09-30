@echo off
REM ============================================================================
REM  VERIFIER TOUT — LE seul fichier a lancer pour savoir si le bot va bien
REM ============================================================================
REM  Remplace une dizaine de petits verificateurs qui trainaient a la racine
REM  (VERIF-FIX-CARRY, VERIF-TOMBES, VOIR-CARRY, VERIFIER-DONNEES-REPLAY...).
REM  Ils sont RANGES dans « outils de test\ », pas supprimes.
REM
REM  7 sections : tests · replay · carry · liquidations · collecteurs · cablage
REM               · securite.  Verdict par section + resume final.
REM
REM  TROIS etats, jamais deux :
REM     OK           le controle passe
REM     ECHEC        quelque chose est casse
REM     INSUFFISANT  pas de quoi juger -- NI succes NI echec
REM  Ce 3e etat evite de confondre « pas de donnees » et « tout va bien » :
REM  c'est cette confusion qui avait produit le faux « 1 sur 1M ».
REM
REM  Le MOISSONNEUR reste a part (decision de Flo) : c'est de la recherche,
REM  pas un controle de sante du bot.
REM
REM  Securite : lecture seule. 0 ordre, 0 cle, 0 signature.
REM ============================================================================
cd /d "%~dp0"
title Verification complete du bot
set "PYTHONPATH=%~dp0src"
set "PYTHONIOENCODING=utf-8"
python tools\verifier_tout.py %*
echo.
echo   Rapport : resultat-verification.txt
echo   Suite de tests COMPLETE (plus longue) : TEST-AUDIT-complet.cmd
echo.
pause
