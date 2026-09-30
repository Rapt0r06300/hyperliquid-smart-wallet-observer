@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   🏁 LE LANCEUR FINAL — tout, dans l'ordre, sans raccourci.
REM
REM   LA CHAINE COMPLETE :
REM     funding 365 j (MESURE) -> SCANNER (4 portes) -> NOYAU (8 portes) -> PaperIntent
REM
REM   LES 4 PORTES DU SCANNER :
REM     1. LE SPOT      -- sans spot, on est short le perp A NU (pari, pas carry). 8/232 coins.
REM     2. LE SIGNE     -- funding negatif -> il faudrait SHORTER le spot : impossible sur HL.
REM     3. LA STABILITE -- AZTEC : 83 %% d'heures positives, moyenne -0,84 bps/h.
REM        *Sur 120 j il paraissait a +5,7 %% APR. Sur 365 j, il PERD.*
REM        ***L'idee des 365 jours de Flo a tue un faux positif que j'allais annoncer.***
REM     4. L'ECONOMIE   -- amortir 23 bps (4 executions) en moins de 30 jours.
REM
REM   PUIS LE NOYAU rejuge TOUT : frais reels (9 bps) · plancher net (30 bps) · disjoncteur
REM   de session (11 gates V19) · only_per_side · VPIN · contraintes d'exchange
REM   · **ET LA JAMBE SPOT** (branchee le 14/07 : le noyau n'en verifiait qu'UNE sur deux).
REM
REM   🔴 LES 3 BUGS TROUVES LE 14/07 AU SOIR :
REM     a) l'APR affiche etait le **BRUT** : les 23 bps etaient verifies a la porte puis
REM        JAMAIS soustraits du chiffre. -> PURR 12,71 -> 11,31 %%
REM     b) le benchmark HLP etait **SUPPOSE** ("10 a 30 %%"). Mesure : **-0,01 %%**.
REM        *Le market maker PAYE pour l'etre ne gagne rien.*
REM     c) le noyau ne verifiait **PAS le carnet SPOT**. Mesure : le carnet de PUMP porte
REM        **473 $** pour 500 $ voulus. ***Le bot l'aurait ouvert.***
REM
REM   Paper-only. Aucun ordre reel. Aucune cle. Aucune signature. Rien de payant.
REM   ASCII PUR, pas de pause -> lancer_tout.txt
REM ==================================================================================

echo ============ 1. TOUS LES TESTS ============ > lancer_tout.txt
python -m pytest -q tests\test_carry_runtime.py tests\test_carry_scanner.py tests\test_carry_apr_net.py tests\test_spot_depth.py tests\test_noyau_jambe_spot.py tests\test_side_lock_carry_exempte.py tests\test_branchements_noyau.py tests\test_session_gate.py >> lancer_tout.txt 2>&1

echo. >> lancer_tout.txt
echo ============ 2. LA VRAIE LISTE DES SPOT (spotMeta) ============ >> lancer_tout.txt
python tools\lister_spot_hl.py >> lancer_tout.txt 2>&1

echo. >> lancer_tout.txt
echo ============ 3. LE SCANNER + LE NOYAU : QUE VA OUVRIR LE BOT ? ============ >> lancer_tout.txt
python tools\scanner_carry_live.py >> lancer_tout.txt 2>&1

echo. >> lancer_tout.txt
echo ============ 4. LA PROFONDEUR DU CARNET (4 jambes) ============ >> lancer_tout.txt
python tools\profondeur_spot.py >> lancer_tout.txt 2>&1

echo. >> lancer_tout.txt
echo ============ 5. LE VERDICT : HLP MESURE vs NOS CARRYS ============ >> lancer_tout.txt
python tools\le_verdict.py >> lancer_tout.txt 2>&1

echo. >> lancer_tout.txt
echo ============ 6. LES BRANCHEMENTS (AST) ============ >> lancer_tout.txt
python tools\audit_cablage_cli.py >> lancer_tout.txt 2>&1

echo. >> lancer_tout.txt
echo ============ 7. SECURITE ============ >> lancer_tout.txt
python -m hl_observer safety-audit >> lancer_tout.txt 2>&1
exit /b 0
