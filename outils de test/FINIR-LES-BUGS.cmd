@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   LES BUGS REELS DES 91 TACHES (H-90 a H-180) -- executes, pas classes.
REM
REM   #543  FRAIS : 6 valeurs eparpillees (2.5 / 4.0 / 4.5 / 6.0) -> source unique.
REM   #543b SPOT != PERP : le carry HYPE (T2b) sous-estime de 5 bps. CORRIGE.
REM   #563  LOOKAHEAD : le grep pandas ne marche PAS ici (code Python pur) ->
REM         remplace par le BALAYAGE DIFFERENTIEL (#562), qui ne lit pas le code.
REM         🔑 Il se CONTROLE lui-meme sur `garch11_variance` (bug connu) :
REM            s'il ne le retrouve pas, **il REFUSE de rendre un verdict** (exit 2).
REM   #571  BUY-AND-HOLD + **LE CASH** : on n'a JAMAIS affiche le benchmark.
REM         Une strategie a rendement negatif est dominee par NE RIEN FAIRE.
REM   #567/#573  DEUX drawdowns : celui des trades clotures CACHE la douleur vecue.
REM   #574  L'ESPERANCE : un winrate de 87 %% peut etre une machine a perdre.
REM   #579  Juger sur le PIRE mois, pas sur la moyenne.
REM
REM   Aucun ordre reel. Aucun argent reel. Aucune cle. Aucune signature. Rien de payant.
REM   ASCII PUR, pas de pause -> "%~dp0rapports\les_bugs.txt"
REM ==================================================================================
echo ============ 1. TESTS DES NOUVEAUX MODULES ============ > "%~dp0rapports\les_bugs.txt"
python -m pytest -q tests\test_hyperliquid_fees.py tests\test_snapshot_capture.py tests\test_honest_metrics.py >> "%~dp0rapports\les_bugs.txt" 2>&1

echo. >> "%~dp0rapports\les_bugs.txt"
echo ============ 2. BALAYAGE DIFFERENTIEL DU LOOKAHEAD ============ >> "%~dp0rapports\les_bugs.txt"
echo    (il se controle sur garch11_variance : s'il ne le retrouve pas, il se TAIT) >> "%~dp0rapports\les_bugs.txt"
python tools\balayage_lookahead.py >> "%~dp0rapports\les_bugs.txt" 2>&1

echo. >> "%~dp0rapports\les_bugs.txt"
echo ============ 3. TRIAGE DES 91 ============ >> "%~dp0rapports\les_bugs.txt"
python tools\trier_h90_h180.py >> "%~dp0rapports\les_bugs.txt" 2>&1

echo. >> "%~dp0rapports\les_bugs.txt"
echo ============ 4. SUITE COMPLETE (la verite est sur Windows) ============ >> "%~dp0rapports\les_bugs.txt"
python -m pytest -q >> "%~dp0rapports\les_bugs.txt" 2>&1

echo. >> "%~dp0rapports\les_bugs.txt"
echo ============ 5. SECURITE ============ >> "%~dp0rapports\les_bugs.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\les_bugs.txt" 2>&1
exit /b 0
