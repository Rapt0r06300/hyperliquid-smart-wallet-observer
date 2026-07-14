@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   FINIR LA PARTIE FUNDING (2026-07-13)
REM
REM   1. TESTS des 2 nouveaux modules (dont l'anti-regression du piege d'unite 8h/1h)
REM   2. MESURE REELLE du funding cross-venue (predictedFundings, normalise en bps/HEURE)
REM   3. BACKFILL du funding realise sur 120 JOURS (fundingHistory) -- X-04 et T2 ont
REM      ete juges sur **18,9 h** alors que l'historique etait public.
REM   4. COLLECTE des depots Arbitrum (X-01) -- adresse du pont VERIFIEE sur la doc.
REM   5. SUITE COMPLETE + SECURITE (la verite est sur Windows, pas dans le sandbox)
REM
REM   Lecture seule. Aucun ordre reel. Aucune cle. Aucune signature. Aucun depot EMIS.
REM   ASCII PUR, pas de pause -> finir_cross_venue.txt
REM ==================================================================================
echo ============ 1. TESTS DES NOUVEAUX MODULES ============ > finir_cross_venue.txt
python -m pytest -q tests\test_funding_cross_venue.py tests\test_funding_backfill.py >> finir_cross_venue.txt 2>&1

echo. >> finir_cross_venue.txt
echo ============ 2. FUNDING CROSS-VENUE (mesure reelle) ============ >> finir_cross_venue.txt
python tools\mesurer_funding_cross_venue.py >> finir_cross_venue.txt 2>&1

echo. >> finir_cross_venue.txt
echo ============ 3. BACKFILL FUNDING 120 JOURS ============ >> finir_cross_venue.txt
python tools\backfill_funding.py --jours=120 >> finir_cross_venue.txt 2>&1

echo. >> finir_cross_venue.txt
echo ============ 4. DEPOTS ARBITRUM (X-01) ============ >> finir_cross_venue.txt
set "HYPERSMART_HL_BRIDGE_ARBITRUM=0x2df1c51e09aecf9cacb7bc98cb1742757f163df7"
python tools\collecter_depots_arbitrum.py >> finir_cross_venue.txt 2>&1

echo. >> finir_cross_venue.txt
echo ============ 5. SUITE COMPLETE (la verite) ============ >> finir_cross_venue.txt
python -m pytest -q >> finir_cross_venue.txt 2>&1

echo. >> finir_cross_venue.txt
echo ============ 6. SECURITE ============ >> finir_cross_venue.txt
python -m hl_observer safety-audit >> finir_cross_venue.txt 2>&1
exit /b 0
