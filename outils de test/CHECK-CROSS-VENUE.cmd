@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #365 / H-137 -- FUNDING CROSS-VENUE (HL <-> Binance <-> Bybit, MEME coin)
REM
REM   ⚠️ LE PIEGE : la 1re version annoncait **38 %% APR** sur l'exemple de la doc.
REM      C'etait FAUX. Binance/Bybit publient un taux **8 HEURES** ; HL un taux **1 HEURE**.
REM      0.0001 / 8 = 0.0000125  ->  LES 3 VENUES SONT EXACTEMENT D'ACCORD.
REM      Le "8x d'ecart" etait l'INTERVALLE DE FUNDING, pas un edge.
REM      (Doc : « paid every hour », « one eighth of the computed [8h] rate ».)
REM
REM   1) les tests (dont l'anti-regression de ce bug precis)
REM   2) la mesure sur les VRAIES donnees, apres normalisation en bps/HEURE
REM
REM   Lecture seule. Aucun ordre. Aucune cle. Aucune signature.
REM   ASCII PUR, pas de pause -> "%~dp0rapports\check_cross_venue.txt"
REM ==================================================================================
echo ================ 1. TESTS ================ > "%~dp0rapports\check_cross_venue.txt"
python -m pytest -q tests\test_funding_cross_venue.py >> "%~dp0rapports\check_cross_venue.txt" 2>&1
echo. >> "%~dp0rapports\check_cross_venue.txt"
echo ================ 2. MESURE REELLE ================ >> "%~dp0rapports\check_cross_venue.txt"
python tools\mesurer_funding_cross_venue.py >> "%~dp0rapports\check_cross_venue.txt" 2>&1
echo. >> "%~dp0rapports\check_cross_venue.txt"
echo ================ 3. SUITE COMPLETE (la verite) ================ >> "%~dp0rapports\check_cross_venue.txt"
python -m pytest -q >> "%~dp0rapports\check_cross_venue.txt" 2>&1
echo. >> "%~dp0rapports\check_cross_venue.txt"
echo ================ 4. SECURITE ================ >> "%~dp0rapports\check_cross_venue.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\check_cross_venue.txt" 2>&1
exit /b 0
