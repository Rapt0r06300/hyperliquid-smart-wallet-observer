@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   MOISSONNEUR v4 - les tests. **NE LANCE AUCUNE MOISSON, AUCUNE REQUETE RESEAU.**
REM
REM   LE TEST CENTRAL : un README BAVARD (qui recite 10 concepts, 5 etoiles) doit
REM   passer DERRIERE un README SUBSTANTIEL (formule posee + aveu de limite + chiffre).
REM   L'ancien tri classait le bavard PREMIER : n_concepts=12 -> mediane 5 etoiles,
REM   n_concepts=0 -> mediane 15. ANTI-CORRELE. Le grep mesurait la VERBOSITE.
REM
REM   ET : la CHECKLIST du moisson-fini.md doit reprendre TOUTES les taches.
REM   Une tache qui peut se perdre est une tache perdue.
REM
REM   NOTE : la verification est dans tools\verifier_moissonneur.py, pas dans un
REM   python -c. Un python -c bourre de guillemets dans un .cmd est fragile :
REM   cmd.exe avale les %% comme des variables. Ca a casse ce controle au 1er essai.
REM
REM   Lecture seule. ASCII PUR.
REM ==================================================================================

echo ============ 1. LES TESTS (scan + tri + dossier + graphe) ============ > "%~dp0rapports\check_moissonneur.txt"
python -m pytest -q -p no:cacheprovider tests\test_github_signals.py tests\test_github_dossier.py tests\test_github_scan_plan.py tests\test_scan_resilience_et_sources.py tests\test_moissonneur_15_idees.py tests\test_moissonneur_10h.py tests\test_frontiere_et_web.py tests\test_sources17_et_idees.py tests\test_domaines.py tests\test_moissonneur_smoke.py tests\test_moissonneur_10_manques.py tests\test_moissonneur_etape1_8h.py >> "%~dp0rapports\check_moissonneur.txt" 2>&1

echo. >> "%~dp0rapports\check_moissonneur.txt"
echo ============ 2. TOUT COMPILE (Windows = la verite, le mount tronque) ============ >> "%~dp0rapports\check_moissonneur.txt"
python -m py_compile tools\moissonner_github.py tools\moissonner_scan.py tools\moissonner_concepts.py tools\moissonner_lire_le_code.py tools\moissonner_sources.py tools\moisson_finale.py src\hl_observer\research\github_signals.py src\hl_observer\research\github_dossier.py src\hl_observer\research\github_graph.py src\hl_observer\research\github_scan_plan.py src\hl_observer\research\scan_resilience.py src\hl_observer\research\sources.py src\hl_observer\research\canari.py src\hl_observer\research\mine_de_code.py src\hl_observer\research\differentiel.py src\hl_observer\research\moteur.py src\hl_observer\research\frontiere.py src\hl_observer\research\web_ouvert.py src\hl_observer\research\moissonneur_sujets.py src\hl_observer\research\sources_plus.py src\hl_observer\research\idee.py src\hl_observer\research\semantique.py src\hl_observer\research\jugement_plus.py src\hl_observer\research\lecture_profonde.py tools\moissonner_10h.py >> "%~dp0rapports\check_moissonneur.txt" 2>&1
if errorlevel 1 (echo   ECHEC COMPILATION >> "%~dp0rapports\check_moissonneur.txt") else (echo   OK - les 25 fichiers compilent >> "%~dp0rapports\check_moissonneur.txt")

echo. >> "%~dp0rapports\check_moissonneur.txt"
echo ============ 3. LES DEFAUTS SONT-ILS CORRIGES ? ============ >> "%~dp0rapports\check_moissonneur.txt"
python tools\verifier_moissonneur.py >> "%~dp0rapports\check_moissonneur.txt" 2>&1
exit /b 0
