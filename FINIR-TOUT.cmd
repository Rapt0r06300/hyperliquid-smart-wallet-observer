@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   FINIR TOUT (2026-07-13) -- funding + archive S3 + triage H-46..H-89
REM
REM   🔒 DECISION DE FLO : **RIEN DE PAYANT.**
REM      L'archive S3 est en requester-pays -> le mode payant est DESACTIVE.
REM      On ne pose que la question GRATUITE : le bucket est-il PUBLIC ?
REM
REM   Aucun ordre reel. Aucun argent reel. Aucune cle privee. Aucune signature.
REM   ASCII PUR, pas de pause -> finir_tout.txt
REM ==================================================================================

echo ============ 1. TESTS DES NOUVEAUX MODULES ============ > finir_tout.txt
python -m pytest -q tests\test_funding_cross_venue.py tests\test_funding_backfill.py tests\test_archive_s3.py tests\test_zones_mortes_entree_mesuree.py >> finir_tout.txt 2>&1

echo. >> finir_tout.txt
echo ============ 2. TRIAGE #451-#494 (H-46 a H-89) ============ >> finir_tout.txt
python tools\trier_h46_h89.py >> finir_tout.txt 2>&1

echo. >> finir_tout.txt
echo ============ 3. FUNDING CROSS-VENUE (normalise bps/HEURE) ============ >> finir_tout.txt
python tools\mesurer_funding_cross_venue.py >> finir_tout.txt 2>&1

echo. >> finir_tout.txt
echo ============ 4. BACKFILL FUNDING 120 JOURS (gratuit, API publique) ============ >> finir_tout.txt
python tools\backfill_funding.py --jours=120 >> finir_tout.txt 2>&1

echo. >> finir_tout.txt
echo ============ 5. ARCHIVE S3 : SONDE **GRATUITE** (--no-sign-request) ============ >> finir_tout.txt
python tools\sonder_archive_s3.py --coin=BTC >> finir_tout.txt 2>&1

echo. >> finir_tout.txt
echo ============ 6. DEPOTS ARBITRUM (X-01, adresse du pont verifiee) ============ >> finir_tout.txt
set "HYPERSMART_HL_BRIDGE_ARBITRUM=0x2df1c51e09aecf9cacb7bc98cb1742757f163df7"
python tools\collecter_depots_arbitrum.py >> finir_tout.txt 2>&1

echo. >> finir_tout.txt
echo ============ 7. SUITE COMPLETE (la verite est sur Windows) ============ >> finir_tout.txt
python -m pytest -q >> finir_tout.txt 2>&1

echo. >> finir_tout.txt
echo ============ 8. SECURITE ============ >> finir_tout.txt
python -m hl_observer safety-audit >> finir_tout.txt 2>&1
exit /b 0
