@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   VERIFIER LE CARRY **AVANT** DE CROIRE SES CHIFFRES — sur **365 JOURS**.
REM
REM   🚩 D'ABORD : JE SUSPECTE MON PROPRE PARSEUR.
REM      296 spot x 232 perps -> seulement **8** en commun. C'est ANORMALEMENT BAS.
REM      Si mon appariement token<->paire est faux, **j'ai JETE des coins carryables**.
REM      *Suspecter son propre outil avant le code d'autrui.*
REM
REM   PUIS LES 4 POINTS, dans l'ordre ou ils peuvent TUER la piste :
REM     1️⃣ LA PROFONDEUR DU CARNET SPOT — ***un edge sur un carnet de 3 $ n'existe pas.***
REM        PURR/AZTEC/PUMP sont petits. Peut-on passer 500 $ SANS bouger le prix ?
REM     2️⃣ LA LIQUIDATION de la jambe perp (X-08) — le carry n'est neutre que tant qu'on
REM        tient LES DEUX jambes.
REM     3️⃣ LA STABILITE DU FUNDING — BERA est passe a -0,16. Un moyen positif peut cacher
REM        des semaines negatives. -> **part d'heures positives**.
REM     4️⃣ LE BENCHMARK — cash, buy-and-hold, **et HLP**.
REM
REM   🚩 LA REGLE QUI M'A DEJA SAUVE : *quand un resultat est beau, regarde QUI survit.*
REM      **PURR a +11 %% APR est un memecoin.** Son funding est haut PRECISEMENT PARCE QUE
REM      le detenir est dangereux. C'est mot pour mot la lecon de CASHCAT (faux +34,94 bps).
REM
REM   Lecture seule. Aucun ordre reel. Aucune cle. Aucune signature. Rien de payant.
REM   ASCII PUR, pas de pause -> "%~dp0rapports\carry_verifie.txt"
REM ==================================================================================

echo ============ 1. LA VRAIE LISTE DES SPOT (spotMeta) ============ > "%~dp0rapports\carry_verifie.txt"
python tools\lister_spot_hl.py >> "%~dp0rapports\carry_verifie.txt" 2>&1

echo. >> "%~dp0rapports\carry_verifie.txt"
echo ============ 2. BACKFILL DU FUNDING SUR **365 JOURS** ============ >> "%~dp0rapports\carry_verifie.txt"
python tools\backfill_funding.py --jours=365 >> "%~dp0rapports\carry_verifie.txt" 2>&1

echo. >> "%~dp0rapports\carry_verifie.txt"
echo ============ 3. LES 4 VERIFICATIONS (dont la PROFONDEUR du carnet) ============ >> "%~dp0rapports\carry_verifie.txt"
python tools\verifier_carry_reel.py >> "%~dp0rapports\carry_verifie.txt" 2>&1

echo. >> "%~dp0rapports\carry_verifie.txt"
echo ============ 4. LE CARRY REJOUE + SES JUGES ============ >> "%~dp0rapports\carry_verifie.txt"
python tools\backtest_carry_vs_hlp.py >> "%~dp0rapports\carry_verifie.txt" 2>&1

echo. >> "%~dp0rapports\carry_verifie.txt"
echo ============ 5. SECURITE ============ >> "%~dp0rapports\carry_verifie.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\carry_verifie.txt" 2>&1
exit /b 0
