@echo off
setlocal EnableExtensions
REM ============================================================
REM  LANCER_OBJECTIF_4USD.cmd
REM  Campagnes economiques PAPER/READ-ONLY separees :
REM    Copy-Vault / Lead-Lag / Cross-Venue Dislocation v2
REM  Cible de preuve : +4 USD NET REALISE par famille.
REM  Aucun ordre reel, aucune signature, aucun /exchange.
REM ============================================================
cd /d "%~dp0"
call "%~dp0tools\portable_env.cmd"
if errorlevel 1 (
  echo [OBJECTIF-4USD] Python portable invalide. Abandon fail-closed.
  endlocal & exit /b 30
)
if not defined HYPERSMART_PYTHON (
  echo [OBJECTIF-4USD] HYPERSMART_PYTHON absent. Abandon fail-closed.
  endlocal & exit /b 31
)
set "PYTHONPATH=%~dp0src;%~dp0tools"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
set "REAL_MAINNET_TRADING=false"
set "TESTNET_ONLY=true"

echo.
echo ============================================================
echo   OBJECTIF ECONOMIQUE PAPER : +4 USD NET PAR FAMILLE
echo   Copy-Vault / Lead-Lag / Cross-Venue Dislocation v2
echo   LIQUIDATABLE_NET + OOS + FORWARD + PLACEBO obligatoires
echo ============================================================
echo.

"%HYPERSMART_PYTHON%" "%~dp0tools\run_economic_objective_campaigns.py" --root "%~dp0."
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo [OBJECTIF-4USD] Echec fail-closed ^(code %RC%^).
  endlocal & exit /b %RC%
)

echo.
echo [OBJECTIF-4USD] Campagne terminee. Voir :
echo runtime\reports\economic_campaigns\HYPERSMART_ECONOMIC_OBJECTIVE_CAMPAIGN.md
endlocal & exit /b 0
