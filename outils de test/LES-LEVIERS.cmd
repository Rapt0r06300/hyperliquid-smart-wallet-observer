@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   "trouve TOUS les moyens possibles pour accepter les 18 coins sur 19"
REM
REM   Je ne reponds pas par une opinion. J'enumere CHAQUE levier et je le CALCULE.
REM
REM   LEVIER 1  exempter le CARRY de only_per_side   -> ✅ +2 coins. C'ETAIT MON BUG.
REM             short perp + long spot = delta ZERO. La jambe perp n'est pas un pari.
REM   LEVIER 2  executer en MAKER (23 -> 11 bps)     -> gain reel, fill PAS garanti
REM   LEVIER 3  allonger l'horizon (30->90 j)        -> ouvre... mais DOMINE par HLP
REM   LEVIER 4  les 224 perps SANS spot              -> 🔴 PHYSIQUE. Pas du code.
REM   LEVIER 5  le funding negatif                   -> 🔴 shorter le spot n'existe pas sur HL
REM   LEVIER 6  baisser les planchers                -> 🚨 C'EST LE BUG QUI A COUTE -64 $
REM   LEVIER 7  de nouvelles FAMILLES (#530)         -> 🎯 la seule voie honnete
REM
REM   Paper-only. Aucun ordre reel. ASCII PUR, pas de pause -> "%~dp0rapports\les_leviers.txt"
REM ==================================================================================

echo ============ 1. LE TEST QUI VERROUILLE LA CORRECTION ============ > "%~dp0rapports\les_leviers.txt"
python -m pytest -q tests\test_side_lock_carry_exempte.py >> "%~dp0rapports\les_leviers.txt" 2>&1

echo. >> "%~dp0rapports\les_leviers.txt"
echo ============ 2. NON-REGRESSION : le noyau + les branchements ============ >> "%~dp0rapports\les_leviers.txt"
python -m pytest -q tests\test_branchements_noyau.py tests\test_session_gate.py tests\test_carry_runtime.py tests\test_carry_scanner.py tests\test_side_lock.py >> "%~dp0rapports\les_leviers.txt" 2>&1

echo. >> "%~dp0rapports\les_leviers.txt"
echo ============ 3. TOUS LES LEVIERS (calcules, pas opines) ============ >> "%~dp0rapports\les_leviers.txt"
python tools\tous_les_leviers.py >> "%~dp0rapports\les_leviers.txt" 2>&1

echo. >> "%~dp0rapports\les_leviers.txt"
echo ============ 4. CE QUE LE BOT OUVRE MAINTENANT ============ >> "%~dp0rapports\les_leviers.txt"
python tools\scanner_carry_live.py >> "%~dp0rapports\les_leviers.txt" 2>&1

echo. >> "%~dp0rapports\les_leviers.txt"
echo ============ 5. SECURITE : 0 ordre reel ============ >> "%~dp0rapports\les_leviers.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\les_leviers.txt" 2>&1
exit /b 0
