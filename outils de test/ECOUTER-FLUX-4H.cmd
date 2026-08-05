@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   T1 - TRANCHER KAITO : 4 h d'ecoute du canal PUBLIC `trades`.
REM
REM   ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py).
REM
REM   CE QUE CA FAIT
REM     Ecoute les marches dont le spread couvre les frais, KAITO FORCE (un seuil de
REM     profondeur l'excluait silencieusement), pendant 240 minutes, puis rend le verdict.
REM
REM   POURQUOI 4 H
REM     KAITO n'avait que 30 trades LIVE sur 691 s. Il en faut 300 sur 30 min minimum pour
REM     mesurer une mediane de selection adverse qui veuille dire quelque chose.
REM
REM   SECURITE : les SEULS messages sortants sont des `subscribe` au canal PUBLIC `trades`.
REM   Aucun ordre, aucune cle, aucune signature. JAMAIS.
REM ==================================================================================
echo.
echo =============================================================
echo   T1 - ECOUTE DU FLUX REEL (4 h) - lecture seule
echo =============================================================
echo.
echo   Laisse cette fenetre ouverte. Elle ecrit dans runtime\replay\trades.*.jsonl
echo   Le verdict tombe automatiquement a la fin.
echo.

python tools\mesurer_flux_market_making.py --minutes 240 --inclure KAITO

echo.
echo   Termine.
echo.
pause
