@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #495-#585 (H-90 a H-180) -- 91 taches. **L'OR ETAIT DANS NOTRE CODE.**
REM
REM   🎯 #543 -- LE NOMBRE LE PLUS IMPORTANT DU PROJET :
REM      1,5 bps maker est JUSTE (perp tier 0, doc officielle).
REM      MAIS le code utilisait **6 valeurs eparpillees** : 2.5 / 4.0 / 4.5 / 6.0
REM      -- et **2,5 bps ne figure NULLE PART** dans la grille Hyperliquid.
REM      -> src/hl_observer/fees/hyperliquid_fees.py = SOURCE UNIQUE + cliquet.
REM
REM   🔴 #543b -- LE SPOT NE COUTE PAS LE PRIX DU PERP :
REM      spot maker = 4,0 bps (perp : 1,5). spot taker = 7,0 (perp : 4,5).
REM      Or T2b -- LE SEUL RESULTAT POSITIF -- a une jambe SPOT chiffree en PERP.
REM      Aller-retour : 18 -> **23 bps** (taker), 6 -> **11 bps** (maker).
REM      **Le carry HYPE etait sous-estime de 5 bps. -15 % de son edge.** CORRIGE.
REM
REM   🔑 #517 -- la SEULE reouverture legitime : le MM sur HIP-3 (growth mode = frais/10).
REM      A **MESURER** avec l'outil T1b, pas a supposer.
REM
REM   Aucun ordre reel. Aucun argent reel. Aucune cle privee. Aucune signature. Rien de payant.
REM   ASCII PUR, pas de pause -> "%~dp0rapports\h90_h180.txt"
REM ==================================================================================
echo ============ 1. TESTS (frais + capture funding) ============ > "%~dp0rapports\h90_h180.txt"
python -m pytest -q tests\test_hyperliquid_fees.py tests\test_snapshot_capture.py >> "%~dp0rapports\h90_h180.txt" 2>&1

echo. >> "%~dp0rapports\h90_h180.txt"
echo ============ 2. TRIAGE DES 91 TACHES ============ >> "%~dp0rapports\h90_h180.txt"
python tools\trier_h90_h180.py >> "%~dp0rapports\h90_h180.txt" 2>&1

echo. >> "%~dp0rapports\h90_h180.txt"
echo ============ 3. SUITE COMPLETE (la verite) ============ >> "%~dp0rapports\h90_h180.txt"
python -m pytest -q >> "%~dp0rapports\h90_h180.txt" 2>&1

echo. >> "%~dp0rapports\h90_h180.txt"
echo ============ 4. SECURITE ============ >> "%~dp0rapports\h90_h180.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\h90_h180.txt" 2>&1
exit /b 0
