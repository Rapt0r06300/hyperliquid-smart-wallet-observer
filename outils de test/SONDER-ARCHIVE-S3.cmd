@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #462 / H-57 -- L'ARCHIVE S3 OFFICIELLE HYPERLIQUID
REM
REM   🔴 J'AI AFFIRME 3 FOIS que le carnet L2 et les trades n'avaient AUCUNE source
REM      historique gratuite. **C'ETAIT FAUX.** Doc officielle (historical-data) :
REM
REM        s3://hyperliquid-archive/market_data/[date]/[hour]/l2Book/[coin].lz4
REM        s3://hl-mainnet-node-data/node_fills_by_block   (fills, PAR BLOC)
REM        s3://hl-mainnet-node-data/node_trades           (trades)
REM        s3://hl-mainnet-node-data/misc_events_by_block  (transferts + funding)
REM
REM      L'exemple de la doc date de 2023. 3e fois aujourd'hui apres candleSnapshot
REM      et fundingHistory : une capacite presente, un chainon manquant.
REM
REM   ⚠️ REQUESTER-PAYS : chaque octet est FACTURE. Cet outil ne telecharge
REM      **qu'UN SEUL objet**, mesure sa taille, et CHIFFRE le cout d'un backfill.
REM      Il ne telecharge RIEN en masse.
REM
REM   🔒 PREREQUIS : AWS CLI installee, et AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
REM      dans l'ENVIRONNEMENT WINDOWS. **JAMAIS dans un fichier du projet.**
REM      Sans identifiants -> l'outil REFUSE et ne facture rien.
REM
REM   Aucun ordre reel. Aucune cle privee de trading. Aucune signature.
REM   ASCII PUR, pas de pause -> "%~dp0rapports\archive_s3.txt"
REM ==================================================================================
echo ============ TESTS ============ > "%~dp0rapports\archive_s3.txt"
python -m pytest -q tests\test_archive_s3.py >> "%~dp0rapports\archive_s3.txt" 2>&1
echo. >> "%~dp0rapports\archive_s3.txt"
echo ============ SONDAGE (1 objet, cout chiffre) ============ >> "%~dp0rapports\archive_s3.txt"
python tools\sonder_archive_s3.py --coin=BTC --jours=30 >> "%~dp0rapports\archive_s3.txt" 2>&1
echo. >> "%~dp0rapports\archive_s3.txt"
echo ============ TRIAGE H-46..H-89 ============ >> "%~dp0rapports\archive_s3.txt"
python tools\trier_h46_h89.py >> "%~dp0rapports\archive_s3.txt" 2>&1
exit /b 0
