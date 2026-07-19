@echo off
REM ============================================================================
REM  ALIMENTATION AUTOMATIQUE DU CARRY
REM
REM  Le carry (funding/carry_paper_runtime) lit ses entrees dans
REM  runtime/data/carry_spot_inputs.json, qui doit rester FRAIS (< 15 min, sinon
REM  = perime = refus). Ce script les re-mesure en boucle toutes les 10 min.
REM
REM  Laisse cette fenetre OUVERTE a cote du bot. Ctrl-C pour arreter.
REM
REM  Levier 2x : c'est le seul niveau ou la jambe perp du carry HYPE survit a la
REM  pire hausse REELLE mesuree (~+29 %). A 3x+, le short serait liquide.
REM  100%% LECTURE SEULE cote marche. Aucun ordre reel, aucune signature.
REM ============================================================================
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
echo Alimentation auto du carry HYPE demarree (levier 2x, toutes les 600 s). Ctrl-C pour arreter.
echo.
:boucle
python tools\ecrire_carry_spot_inputs.py
echo   [%date% %time%] inputs rafraichis -- prochaine mesure dans 10 min.
echo.
REM 19/07 : cadence 600 s -> 240 s. Chaque passe manquee creait un TROU dans la shortlist, et
REM l'ancienne regle fermait la position sur ce trou (29 fermetures sur 31, ~5 $ de frais).
REM L'anti-churn tolere desormais l'absence, mais moins de trous = moins de bruit tout court.
timeout /t 240 /nobreak >nul
goto boucle
