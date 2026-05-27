@echo off
setlocal
cd /d "%~dp0"

set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "HL_ENV=paper"
set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
set "HYPERSMART_MODE=SIMULATION_ONLY_UNTIL_MANUAL_REVIEW"
set "HYPERSMART_POSITIVE_PNL_REQUIRED_FOR_FUTURE_REVIEW=1"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start_hypersmart_simulation.ps1" -Port 8792 -IntervalSeconds 60 -MaxLeaders 50 -Interactive

exit /b 0
