@echo off
REM ============================================================================
REM  SONDER-CONFIRMATION — diagnostic de TRANSPORT strictement lecture seule.
REM  Pour chacun des 5 vaults du shard B (les candidats calmes), ouvre une socket
REM  DIAGNOSTIC temporaire, s'abonne a SON userFills et attend soit le
REM  subscriptionResponse (ACK), soit le 1er userFills isSnapshot=true (SNAPSHOT).
REM  Sinon PENDING. Croise REST (curseur) : un fill REST plus recent que le
REM  curseur WS et absent = shard DEFAILLANT. Sondes sequentielles, tres largement
REM  sous 30 connexions/minute. 0 ordre, 0 cle, 0 signature, config_hash inchange.
REM  Ecrit runtime\data\sonde_confirmation.json ET affiche a l'ecran.
REM ============================================================================
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
if not exist "runtime\data" mkdir "runtime\data" >nul 2>&1
echo Sonde en cours (shard B, ~1-2 min)... chaque vault : ACK / SNAPSHOT / PENDING.
echo.
python "tools\sonde_confirmation_vaults.py" --shard B
echo.
echo Rapport JSON : runtime\data\sonde_confirmation.json
echo.
pause
