@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   LES 8 BUGS REELS DES 91 TACHES -- TOUS EXECUTES (2026-07-13)
REM
REM   #543  FRAIS : 6 valeurs eparpillees (2.5/4.0/4.5/6.0) -> source unique + cliquet.
REM   #543b SPOT != PERP : spot maker 4,0 bps (perp 1,5). T2b (le SEUL resultat positif)
REM         avait sa jambe SPOT chiffree en PERP -> aller-retour 18->23 bps. CORRIGE.
REM   #563  Le grep pandas ne marche PAS ici (Python pur) -> BALAYAGE DIFFERENTIEL (#562),
REM         qui SE TAIT s'il ne retrouve pas `garch11_variance` (bug connu).
REM   #571  BUY-AND-HOLD **et LE CASH** : jamais affiches. Un rendement negatif est
REM         DOMINE par ne rien faire, sur les DEUX dimensions.
REM   #567/#573  DEUX drawdowns : celui des trades clotures CACHE la douleur vecue.
REM   #574  ESPERANCE : un winrate de 87 %% peut etre une machine a perdre.
REM   #576  CONTRAINTES EXCHANGE : notionnel min **10 $** (on size 500 $ -> ca passe),
REM         prix a 5 chiffres significatifs, taille arrondie a szDecimals VERS LE BAS.
REM   #498/#540  **BadAloPx** : un post-only qui croiserait est **REJETE**, PAS execute
REM         en taker. Une simulation qui compte un fill ici INVENTE un trade.
REM   #496  La liste OFFICIELLE des rejets (dont **Oracle** : « price too far from oracle »).
REM   #572  INTRA-BOUGIE : une bougie 1 h qui touche SL **et** TP ne dit pas lequel d'abord.
REM         Mode PESSIMISTE par defaut : **on ne se fait jamais de cadeau.**
REM   #578  🔴 « JE ME SUIS TROMPE » : le rapport dit **1 425 000** scenarios, pas 150 000 000.
REM         Facteur 105. **Le CODE etait juste** (n_essais=evaluated). Ma NARRATION etait fausse.
REM         **La conclusion TIENT : 0 config robuste sur 1,4 M reste 0.**
REM   #514  Decimal vs float : ecart **2e-15 $ sur 100 000 trades**. Refute par un chiffre.
REM
REM   Aucun ordre reel. Aucun argent reel. Aucune cle. Aucune signature. Rien de payant.
REM   ASCII PUR, pas de pause -> "%~dp0rapports\tous_les_bugs.txt"
REM ==================================================================================
echo ============ 1. TESTS DES NOUVEAUX MODULES ============ > "%~dp0rapports\tous_les_bugs.txt"
python -m pytest -q tests\test_hyperliquid_fees.py tests\test_snapshot_capture.py tests\test_honest_metrics.py tests\test_execution_realism.py tests\test_zones_mortes_entree_mesuree.py >> "%~dp0rapports\tous_les_bugs.txt" 2>&1

echo. >> "%~dp0rapports\tous_les_bugs.txt"
echo ============ 2. BALAYAGE DIFFERENTIEL DU LOOKAHEAD ============ >> "%~dp0rapports\tous_les_bugs.txt"
python tools\balayage_lookahead.py >> "%~dp0rapports\tous_les_bugs.txt" 2>&1

echo. >> "%~dp0rapports\tous_les_bugs.txt"
echo ============ 3. TRIAGE DES 91 ============ >> "%~dp0rapports\tous_les_bugs.txt"
python tools\trier_h90_h180.py >> "%~dp0rapports\tous_les_bugs.txt" 2>&1

echo. >> "%~dp0rapports\tous_les_bugs.txt"
echo ============ 4. SUITE COMPLETE (la verite est sur Windows) ============ >> "%~dp0rapports\tous_les_bugs.txt"
python -m pytest -q >> "%~dp0rapports\tous_les_bugs.txt" 2>&1

echo. >> "%~dp0rapports\tous_les_bugs.txt"
echo ============ 5. SECURITE ============ >> "%~dp0rapports\tous_les_bugs.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\tous_les_bugs.txt" 2>&1
exit /b 0
