@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   LE CARRY — **LA SEULE STRATEGIE MESUREE POSITIVE DU PROJET.**
REM
REM   Sur ~600 idees, UNE SEULE a survecu a la falsification :
REM     T2/T2b — le carry delta-neutre sur HYPE. **+33,6 bps dans son PIRE mois.**
REM
REM   Elle franchit le noyau parce que sa famille (CARRY_STRUCTUREL) est VALIDE_PARTIEL,
REM   pas une zone morte. Et la raison est de NATURE, pas de degre :
REM
REM     ***Ce n'est PAS une prediction. C'est un PAIEMENT pour detenir une position.***
REM
REM   C'est l'exact oppose du copy-trading, qui pariait qu'un leader savait quelque chose
REM   -- et la mesure a dit qu'il ne savait RIEN (-7,97 bps, meme a cout ZERO).
REM
REM   LES 3 ETAPES :
REM     1. BRANCHER  -> strategies/carry_runtime.py (couts REELS : **23 bps**, pas 18)
REM     2. REJOUER   -> sur des MOIS de fundingHistory (endpoint public)
REM     3. JUGER     -> par le CASH, le BUY-AND-HOLD et **le vault HLP**
REM
REM   🎯 ***Une strategie qui ne bat pas un depot passif n'est pas une strategie.***
REM
REM   🚩 CE QUE JE NE PROMETS PAS :
REM      - ~2 %% APR, pas 4 %% (le capital est sur DEUX jambes)
REM      - -15 %% de plus apres correction des frais SPOT (4,0 bps, pas 1,5)
REM      - **UN SEUL MARCHE** (HYPE) a survecu sur 8
REM      - la jambe PERP peut etre **LIQUIDEE** (X-08)
REM
REM   Paper-only. Aucun ordre reel. Aucune cle. Aucune signature. Rien de payant.
REM   ASCII PUR, pas de pause -> "%~dp0rapports\carry.txt"
REM ==================================================================================

REM  🔴 ETAPE 0 AJOUTEE LE 2026-07-14 — **JE SUPPOSAIS LA LISTE DU SPOT.**
REM     J'avais ecrit {HYPE, PURR} de memoire, sans jamais verifier.
REM     *La meme erreur que « data-limited » (a un appel de distance) et « pas de source
REM      historique » (l'archive S3 existait depuis 2023).*
REM     ***On demande a l'API. On ne devine pas.*** -> endpoint public `spotMeta`.

echo ============ 0. LA VRAIE LISTE DES MARCHES SPOT (spotMeta) ============ > "%~dp0rapports\carry.txt"
python tools\lister_spot_hl.py >> "%~dp0rapports\carry.txt" 2>&1

echo. >> "%~dp0rapports\carry.txt"
echo ============ 1. LE MOTEUR CARRY (tests) ============ >> "%~dp0rapports\carry.txt"
python -m pytest -q tests\test_carry_runtime.py >> "%~dp0rapports\carry.txt" 2>&1

echo. >> "%~dp0rapports\carry.txt"
echo ============ 2. BACKFILL DU FUNDING (120 jours, endpoint public) ============ >> "%~dp0rapports\carry.txt"
python tools\backfill_funding.py --jours=120 >> "%~dp0rapports\carry.txt" 2>&1

echo. >> "%~dp0rapports\carry.txt"
echo ============ 3. LE CARRY REJOUE, ET SES TROIS JUGES ============ >> "%~dp0rapports\carry.txt"
python tools\backtest_carry_vs_hlp.py >> "%~dp0rapports\carry.txt" 2>&1

echo. >> "%~dp0rapports\carry.txt"
echo ============ 4. SECURITE ============ >> "%~dp0rapports\carry.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\carry.txt" 2>&1
exit /b 0
