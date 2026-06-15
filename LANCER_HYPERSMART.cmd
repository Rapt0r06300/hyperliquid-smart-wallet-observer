@echo off
setlocal
cd /d "%~dp0"

set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "HL_ENV=paper"
set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
set "HYPERSMART_MODE=SIMULATION_ONLY_UNTIL_MANUAL_REVIEW"
set "HYPERSMART_POSITIVE_PNL_REQUIRED_FOR_FUTURE_REVIEW=1"
REM Reglages SELECTIFS (2026-06-12): edge net > cout (~17 bps), fraicheur stricte,
REM pas d'ADD comme entree, marches liquides seulement. Moins de trades, plus propres.
set "HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS=6000"
set "HYPERSMART_SIMULATION_ALLOW_ADD_AS_ENTRY=0"
set "HYPERSMART_SIMULATION_MIN_EDGE_BPS=35"
set "HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE=0.5"
set "HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS=12"

REM ── dYdX v4 — Scan rapide multi-wallets (READ-ONLY / PAPER, opt-in) ────────
REM   Active la decouverte ON-CHAIN Cosmos (maximum d'adresses) + le WebSocket
REM   Indexer temps reel pour suivre les wallets et reproduire leurs moves en
REM   moins d'1s (simulation paper uniquement, aucun ordre reel).
REM   Pour DESACTIVER: remettre 0 ci-dessous (ou supprimer ces 2 lignes).
set "DYDX_FAST_SCANNER=1"
set "DYDX_FAST_SCANNER_HOT_CAPACITY=1000"

REM Politique de risque (anti-churn, exits ATR, coupe-circuit, anti-scalper).
REM Pour DESACTIVER: mettre 0. Defaut moteur = OFF.
set "DYDX_RISK_POLICY=1"

REM Mode "mouvement propre": copier les top wallets PROUVES un par un (comme le
REM vrai bot viral), pas seulement en consensus de 2. Edge net exige > ~1.5x couts
REM (au lieu de 3x) pour qu'il y ait enfin des trades. Qualite gardee par le gate
REM "leaders prouves" + marche liquide + fraicheur + politique de risque.
set "DYDX_CONSENSUS_MIN_WALLETS=1"
set "DYDX_EDGE_SAFETY_MULTIPLIER=1.5"

REM Firehose full node (tous les fills + adresses en temps reel). Mettre 1 QUAND
REM ton node dYdX (--grpc-streaming-enabled) tourne: il s'active alors tout seul
REM au demarrage. Sans node, laisser 0 (sinon reconnexions inutiles en boucle).
if not defined DYDX_FULL_NODE_STREAM set "DYDX_FULL_NODE_STREAM=0"
if not defined DYDX_FULL_NODE_STREAM_ENDPOINT set "DYDX_FULL_NODE_STREAM_ENDPOINT=127.0.0.1:9090"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start_hypersmart_simulation.ps1" -Port 8794 -IntervalSeconds 15 -MaxLeaders 50 -Interactive

exit /b 0
