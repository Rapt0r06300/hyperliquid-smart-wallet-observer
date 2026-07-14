@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #362 / X-01 -- depots Arbitrum -> Hyperliquid. LECTURE ON-CHAIN SEULE.
REM
REM   L'ADRESSE DU PONT, **VERIFIEE SUR LA DOC OFFICIELLE** (2026-07-13) :
REM     https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/bridge2
REM     « The bridge between Hyperliquid and Arbitrum:
REM       https://arbiscan.io/address/0x2df1c51e09aecf9cacb7bc98cb1742757f163df7 »
REM     ... et citee une 2e fois sur la meme page (`spender` de batchedDepositWithPermit).
REM
REM   USDC natif Arbitrum : 0xaf88d065e77c8cC2239327C5EDb3A432268e5831 (6 decimales).
REM   Depot minimum : 5 USDC. Credite en **MOINS D'UNE MINUTE** -> c'est notre avance.
REM
REM   ⚠️ L'adresse est fournie ICI, pas codee en dur dans le module : un invariant
REM      interdit toute adresse litterale dans `arbitrum_deposits.py`. Le module ne
REM      peut donc jamais lire un contrat que personne n'a verifie.
REM
REM   Aucun ordre reel. Aucune cle. Aucune signature. Aucun depot EMIS.
REM   ASCII PUR, pas de pause -> depots_arbitrum.txt
REM ==================================================================================
set "HYPERSMART_HL_BRIDGE_ARBITRUM=0x2df1c51e09aecf9cacb7bc98cb1742757f163df7"
python tools\collecter_depots_arbitrum.py > depots_arbitrum.txt 2>&1
exit /b 0
