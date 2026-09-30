@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   🔴 « EN GROS RIEN N'EST VRAIMENT BRANCHE SUR LA SIMULATION ? » (Flo, 2026-07-14)
REM
REM   IL AVAIT RAISON : **22 modules livres, 3 branches.**
REM   *Un module qui existe n'est pas un module qui garde.*
REM
REM   ET EN CHERCHANT, J'AI TROUVE **LE PIRE BUG DU PROJET** :
REM
REM     local_engine.py:215   plancher_edge_net_bps = **0.0**   <- dans le chemin LIVE
REM     schemas.py:130        estimated_fee_bps     = **0.0**   <- un candidat mal rempli
REM     noyau_unique.py:127   frais_bps             = **0.0**   <- le defaut du noyau
REM     runtime_v9_adapter    repli                 = **4.0**   <- n'existe NULLE PART
REM
REM   ***UN EDGE NET DE +0,01 bps FRANCHISSAIT LA PORTE.***
REM   Le deny-by-default protegeait les ORDRES ; il ne protegeait pas les CHIFFRES.
REM   (Et le commentaire du noyau disait deja : « Jamais des constantes silencieuses ».)
REM
REM   CE QUI EST MAINTENANT BRANCHE **DANS LA PORTE** (noyau_unique.decider) :
REM     #543  les FRAIS       -> source unique, 9,0 bps A/R. Plancher net **30 bps**.
REM     #566  only_per_side   -> 19/21 SHORT = 1 chance sur 4 520.
REM     #521  le VPIN         -> *ne pas savoir n'est pas une permission de trader*.
REM     #576  les CONTRAINTES -> *un trade que l'exchange aurait refuse est un trade INVENTE*.
REM
REM   + un INVARIANT AST (tests/test_branchements_noyau.py) : si un garde-fou est
REM     debranche, ou si un ZERO silencieux revient, **le test HURLE**.
REM
REM   Aucun ordre reel. Aucune cle. Aucune signature. Rien de payant.
REM   ASCII PUR, pas de pause -> "%~dp0rapports\branchements.txt"
REM ==================================================================================
REM   🔴 #292b RESOLU AUSSI : les 11 gates de `risk_engine_v3` n'avaient qu'UN appelant --
REM      `analysis/negative_pnl_auditor.py`, **L'AUTOPSIE**.
REM      ***Les 11 gates qui auraient pu EMPECHER la perte ne servaient qu'a l'EXPLIQUER.***
REM      -> `risk/session_gate.py` : ils passent en **GATE 0** du noyau, AVANT tout le reste.
REM      🚩 Et j'ai commis LE MEME bug dans mon propre garde-fou : `getattr(g, "blocks")`
REM         alors que le champ s'appelle `blocks_new_entries` -> **aucun gate ne bloquait**.
REM         *J'ai reproduit exactement la maladie que je reparais.* Corrige + test verrouille.

echo ============ 1. L'INVARIANT DE BRANCHEMENT ============ > "%~dp0rapports\branchements.txt"
python -m pytest -q tests\test_branchements_noyau.py tests\test_session_gate.py >> "%~dp0rapports\branchements.txt" 2>&1

echo. >> "%~dp0rapports\branchements.txt"
echo ============ 2. LE NOYAU + LE CHEMIN D'ENTREE ============ >> "%~dp0rapports\branchements.txt"
python -m pytest -q tests\test_noyau_unique.py tests\test_no_real_trade_foundations.py >> "%~dp0rapports\branchements.txt" 2>&1

echo. >> "%~dp0rapports\branchements.txt"
echo ============ 3. QUI EST ENCORE MORT ? (audit de cablage) ============ >> "%~dp0rapports\branchements.txt"
python tools\audit_cablage_cli.py >> "%~dp0rapports\branchements.txt" 2>&1

echo. >> "%~dp0rapports\branchements.txt"
echo ============ 4. SUITE COMPLETE (la verite est sur Windows) ============ >> "%~dp0rapports\branchements.txt"
python -m pytest -q >> "%~dp0rapports\branchements.txt" 2>&1

echo. >> "%~dp0rapports\branchements.txt"
echo ============ 5. SECURITE ============ >> "%~dp0rapports\branchements.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\branchements.txt" 2>&1
exit /b 0
