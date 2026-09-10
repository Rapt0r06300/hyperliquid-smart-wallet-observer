@echo off
REM ============================================================================
REM  Alina Smart Flow - portes officielles de recherche / analyse, paper-read-only.
REM  Aucun ordre reel, aucune cle privee, aucune signature.
REM ============================================================================
setlocal EnableExtensions
cd /d "%~dp0"
call "%~dp0tools\portable_env.cmd"
if errorlevel 1 exit /b 30
if not defined HYPERSMART_PYTHON exit /b 31

set "PYTHONPATH=%CD%\src;%CD%\tools"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "HL_ENV=paper"
set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
set "REAL_MAINNET_TRADING=false"
set "TESTNET_ONLY=true"

if /I "%~1"=="semantic" goto semantic
if /I "%~1"=="campaigns" goto campaigns
if /I "%~1"=="bbo" goto bbo
if /I "%~1"=="context" goto context
if not "%~1"=="" goto usage

:context
"%HYPERSMART_PYTHON%" -u tools\codex_research_context.py --auto
exit /b %ERRORLEVEL%

:semantic
shift
"%HYPERSMART_PYTHON%" -u tools\codex_semantic_discovery.py %*
exit /b %ERRORLEVEL%

:campaigns
shift
"%HYPERSMART_PYTHON%" -u tools\run_dataset_economic_campaigns.py %*
exit /b %ERRORLEVEL%

:bbo
shift
"%HYPERSMART_PYTHON%" -u tools\collecter_bbo.py %*
exit /b %ERRORLEVEL%

:usage
echo Usage:
echo   LANCER-CODEX-RESEARCH.cmd
echo   LANCER-CODEX-RESEARCH.cmd context
echo   LANCER-CODEX-RESEARCH.cmd semantic [arguments]
echo   LANCER-CODEX-RESEARCH.cmd campaigns [arguments]
echo   LANCER-CODEX-RESEARCH.cmd bbo [arguments]
exit /b 2
