@echo off
REM Mesure les inputs spot du carry (base, liquidite, funding, levier, marge, pire-hausse)
REM et ecrit runtime/data/carry_spot_inputs.json -> DEBLOQUE le carry (il decidait NO_TRADE
REM faute d'entrees mesurees). 100%% lecture seule cote marche. Aucun ordre reel.
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
echo.
echo === MESURE + ECRITURE des inputs spot du carry (HYPE) ===
echo.
python tools\ecrire_carry_spot_inputs.py --diagnostic
echo.
echo === FIN ( relance ce .cmd toutes les ~10 min pour garder le carry alimente ) ===
pause
