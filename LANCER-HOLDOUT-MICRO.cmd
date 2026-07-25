@echo off
chcp 65001 >nul
REM HISTORICAL_HOLDOUT_V1 - micro-echantillon AWS, BORNE (30 LIST, 6 GET, 50 Mo, 1 EUR). Lecture S3 seule.
REM Refuse sans le profil dedie 'hl-holdout-ro'. AUCUNE cle affichee/loggee. Ne lance qu'apres le feu vert de Claude.
cd /d "%~dp0"
python -c "import boto3" 1>nul 2>nul || echo [!] boto3 requis : pip install boto3
echo Micro-echantillon holdout (borne). Lecture S3 seule, aucun ordre reel.
python tools\holdout_micro_download.py --profile hl-holdout-ro --coin SOL
echo.
echo (code de sortie %ERRORLEVEL%)  ^|  rapport GO/NO-GO : runtime\rapports\holdout\holdout_micro_go_nogo.json
pause
