@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   LES 3 DERNIERES PISTES (2026-07-13)
REM
REM   #517 -- LE MM SUR HIP-3. **La SEULE reouverture legitime** : ma zone morte prevoit
REM        « une mesure montrant que le risque d'inventaire est INFERIEUR au spread capture ».
REM        Growth mode = frais / 10 (maker 0,15 bps). La porte des COUTS est franchie.
REM        🚩 MAIS T1b est mort sur l'INVENTAIRE : le prix bouge 5 a 30x le spread capture.
REM           A 20 bps de demi-spread, il faudrait que le prix bouge MOINS de 20 bps.
REM           Sur le marche le plus NEUF et le plus ILLIQUIDE de la plateforme.
REM        **J'ATTENDS UN ECHEC, ET JE LE DIS AVANT DE MESURER.**
REM        + sur HIP-3 l'ORACLE est fixe par le DEPLOYEUR (doc), pas par une mediane de CEX.
REM
REM   #556 -- L'ORACLE HL suit les CEX (mediane ponderee, doc).
REM        🚫 La forme naive (« devancer l'oracle ») est une COURSE DE VITESSE : on serait
REM           le pigeon. Et la latence est une ZONE MORTE (courbe edge/horizon PLATE).
REM        ✅ L'angle retenu : l'ecart mark-oracle EST le premium -> il **pilote le funding**,
REM           qui se paie a l'HEURE. **On a une heure pour agir. Aucune vitesse requise.**
REM
REM   #530 -- LES LIQUIDATIONS : un flux FORCE, donc **NON INFORME**. Le liquide ne CHOISIT
REM        pas de vendre : il est VENDU. C'est l'inverse exact du copy-trading (leader
REM        contrarien). ⚠️ 4 pieges dits d'avance : le couteau qui tombe · notre carte est
REM        BORGNE (on ne voit que les wallets suivis) · le BACKSTOP LIQUIDATOR absorbe une
REM        partie du flux HORS CARNET · la concurrence.
REM        Markout sur le **MID** -- jamais sur des prix de trade (bid-ask bounce : 2 fois, ca suffit).
REM
REM   Lecture seule. Aucun ordre reel. Aucune cle. Aucune signature. Rien de payant.
REM   ASCII PUR, pas de pause -> "%~dp0rapports\trois_pistes.txt"
REM ==================================================================================
echo ============ 1. TESTS DES 3 MODULES ============ > "%~dp0rapports\trois_pistes.txt"
python -m pytest -q tests\test_trois_pistes.py >> "%~dp0rapports\trois_pistes.txt" 2>&1

echo. >> "%~dp0rapports\trois_pistes.txt"
echo ============ 2. SUITE COMPLETE (la verite est sur Windows) ============ >> "%~dp0rapports\trois_pistes.txt"
python -m pytest -q >> "%~dp0rapports\trois_pistes.txt" 2>&1

echo. >> "%~dp0rapports\trois_pistes.txt"
echo ============ 3. SECURITE ============ >> "%~dp0rapports\trois_pistes.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\trois_pistes.txt" 2>&1
exit /b 0
