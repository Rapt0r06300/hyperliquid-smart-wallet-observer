@echo off
REM [Bloc 8] Environnement PARTAGE des CMD d'analyse (source unique - dedup). Appele apres 'cd /d %~dp0'.
REM PAPER STRICT : execution mainnet/testnet desactivee, 0 ordre reel.
set "PYTHONPATH=%CD%\src;%CD%\tools"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
set "REAL_MAINNET_TRADING=false"
set "TESTNET_ONLY=true"
