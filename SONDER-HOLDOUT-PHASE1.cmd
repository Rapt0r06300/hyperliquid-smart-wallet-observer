@echo off
chcp 65001 >nul
REM HISTORICAL_HOLDOUT_V1 - PHASE 1 : sonde metadonnees S3 GRATUITE (<=30 requetes, 0 telechargement).
REM Aucun compte/paiement AWS. Si aws absent -> le script le dit (n'installe rien sans accord).
cd /d "%~dp0"
echo Sonde metadonnees archive Hyperliquid (gratuit, --no-sign-request)...
echo.
python tools\sonde_holdout_phase1.py
echo.
echo (code de sortie: %ERRORLEVEL%)  ^| rapport: runtime\rapports\holdout\phase1_sonde.txt
pause
