@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   LE VERDICT — nos carrys battent-ils un simple VIREMENT dans HLP ?
REM
REM   DEUX BUGS TROUVES EN RELISANT LE RAPPORT :
REM
REM   🔴 1. L'APR AFFICHE ETAIT LE **BRUT**.
REM         apr_sur_capital = (funding / 2) x 24 x 365
REM         -> les 23 bps de couts n'y figuraient PAS. Ils etaient verifies a la porte,
REM            puis JAMAIS soustraits du chiffre. *Un cout qu'on verifie mais qu'on ne
REM            soustrait pas est un cout qu'on CACHE.*
REM         PURR 12,71 -> 11,31 %   PUMP 6,63 -> 5,23 %   HYPE 5,87 -> 4,48 %
REM
REM   🔴 2. LE BENCHMARK HLP ETAIT **SUPPOSE** ("10 a 30 %", ecrit de tete).
REM         C'est le peche que ce projet punit : DEVINER au lieu de DEMANDER. 4e fois.
REM         -> on le MESURE via `vaultDetails` (public, lecture seule).
REM
REM   Le benchmark decide de TOUT : si HLP rend plus que nos carrys, toute notre
REM   complexite est DOMINEE PAR UN VIREMENT. Et il faut le dire.
REM
REM   Lecture seule. Aucun depot. Aucun ordre reel. ASCII PUR -> "%~dp0rapports\le_verdict.txt"
REM ==================================================================================

echo ============ 1. LES TESTS DE L'APR NET ============ > "%~dp0rapports\le_verdict.txt"
python -m pytest -q tests\test_carry_apr_net.py tests\test_side_lock_carry_exempte.py >> "%~dp0rapports\le_verdict.txt" 2>&1

echo. >> "%~dp0rapports\le_verdict.txt"
echo ============ 2. NON-REGRESSION (carry + noyau + session) ============ >> "%~dp0rapports\le_verdict.txt"
python -m pytest -q tests\test_carry_runtime.py tests\test_carry_scanner.py tests\test_branchements_noyau.py tests\test_session_gate.py >> "%~dp0rapports\le_verdict.txt" 2>&1

echo. >> "%~dp0rapports\le_verdict.txt"
echo ============ 3. LE VERDICT : HLP MESURE vs NOS CARRYS AU NET ============ >> "%~dp0rapports\le_verdict.txt"
python tools\le_verdict.py >> "%~dp0rapports\le_verdict.txt" 2>&1

echo. >> "%~dp0rapports\le_verdict.txt"
echo ============ 4. CE QUE LE BOT OUVRE (APR desormais NET) ============ >> "%~dp0rapports\le_verdict.txt"
python tools\scanner_carry_live.py >> "%~dp0rapports\le_verdict.txt" 2>&1

echo. >> "%~dp0rapports\le_verdict.txt"
echo ============ 5. SECURITE : 0 ordre reel ============ >> "%~dp0rapports\le_verdict.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\le_verdict.txt" 2>&1
exit /b 0
