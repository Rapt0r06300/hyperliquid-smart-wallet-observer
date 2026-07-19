@echo off
REM ============================================================================
REM  REANIMER-COLLECTEURS — relance les 4 collecteurs SANS redemarrer le bot
REM ============================================================================
REM  POURQUOI (19/07) : les 4 collecteurs sont morts ensemble a 15:27 (en plein
REM  sommeil, code 0). 15 min plus tard le carry refusait tout : inputs perimes.
REM  Le superviseur integre au moteur les relance desormais tout seul — mais il
REM  ne vit QUE dans un moteur redemarre apres le commit 1bdbf4a. Ce bouton est
REM  le defibrillateur MANUEL : double-clic, et la collecte repart.
REM
REM  ⚠️ Les lignes ci-dessous DOIVENT rester identiques a celles de
REM  LANCER_HYPERSMART.cmd. Le test tests/test_superviseur_collecteurs.py
REM  (canari anti-derive) compare les DEUX fichiers au registre du superviseur.
REM
REM  Securite : collecte publique en lecture seule. 0 ordre, 0 cle, 0 signature.
REM ============================================================================
setlocal
cd /d "%~dp0"

echo.
echo  Reanimation des 4 collecteurs (les doublons sont sans danger : chaque
echo  passe est idempotente et les lecteurs dedupliquent) ...
echo.

start "" /b tools\boucle_collecteur.cmd carry-feeder tools\ecrire_carry_spot_inputs.py 240
start "" /b tools\boucle_collecteur.cmd marks-collector tools\ecrire_marks_tous_coins.py 60 --une-fois
start "" /b tools\boucle_collecteur.cmd liq-collector tools\collecter_liquidations.py 300 --une-fois
start "" /b tools\boucle_collecteur.cmd venues-collector tools\collecter_dispersion_venues.py 300 --une-fois

echo  4 collecteurs relances. Verification dans ~1 min :
echo    - runtime\logs\carry-feeder.log doit avoir une passe fraiche ;
echo    - le carry sort de INPUTS_SPOT_PERIMES_NO_TRADE en ^<= 4 min.
echo.
echo  Controle complet a tout moment : VERIFIER-TOUT.cmd (section 5).
echo.
pause
