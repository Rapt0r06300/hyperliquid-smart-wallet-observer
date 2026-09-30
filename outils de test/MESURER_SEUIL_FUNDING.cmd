@echo off
REM ==============================================================================================
REM  LE SEUIL D'ENTREE DU GRINDER EST-IL ATTEIGNABLE ?  (2026-07-11)
REM
REM  Le funding-arb (la seule strategie "grinder" cablee) n'a JAMAIS trade. Son verrou d'entree
REM  exige 2,5 bps de funding PAR HEURE. Le commentaire du code trahit son origine : "~20 bps/8h".
REM  Le repo d'origine visait une place ou le funding tombe toutes les 8 HEURES.
REM  Hyperliquid, lui, paie toutes les HEURES.
REM
REM  Si le funding horaire reel reste loin sous 2,5 bps => VERROU MORT : zero trade garanti,
REM  par construction. Je n'ai PAS pu le mesurer (pas de reseau depuis mon environnement), donc
REM  je n'ai RIEN change. Ce script va chercher la donnee reelle sur ta machine.
REM
REM  LECTURE SEULE. Endpoint public /info uniquement.
REM  Aucun ordre, aucun argent, aucune cle privee, aucune signature.
REM ==============================================================================================
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src"
set "PYTHONIOENCODING=utf-8"

echo.
echo   Mesure du funding reel sur Hyperliquid (lecture seule, endpoint public)...
echo.

python tools\measure_funding_gate.py
if errorlevel 1 (
  echo.
  echo   [!] La mesure a echoue.
  echo       Verifie que Python est installe et accessible ^(tape: python --version^).
)

echo.
echo   ----------------------------------------------------------------------------
echo   VERDICT_MORT     = le seuil est infranchissable : le Grinder ne tradera JAMAIS.
echo   QUASI-MORT       = moins de 2 %% des marches passent : quasi inutile.
echo   SELECTIF         = le seuil laisse passer une minorite de marches.
echo   PASSANT          = le seuil n'est pas ce qui bloque le Grinder.
echo.
echo   Un instantane ne prouve rien seul : le funding varie dans le temps.
echo   Pour trancher pour de bon, laisse le bot tourner (il enregistre le funding).
echo   ----------------------------------------------------------------------------
echo.
pause
