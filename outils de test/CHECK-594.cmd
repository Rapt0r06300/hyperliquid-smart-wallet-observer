@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #594 / #310 -- UNE SEULE PORTE D'EDGE, et plus aucune re-ponderation d'une mesure.
REM   ASCII PUR, pas de pause -> "%~dp0rapports\check_594.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_594.txt"
echo === 1. la porte unique + le double-comptage + le bug de signe === >> "%~dp0rapports\check_594.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_edge_vient_de_la_table.py >> "%~dp0rapports\check_594.txt" 2>&1
echo. >> "%~dp0rapports\check_594.txt"
echo === 2. tous les appelants du scoreur === >> "%~dp0rapports\check_594.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_realtime_magic_score.py tests\test_copy_edge_must_be_empirical.py tests\test_calibration_no_dead_gates.py tests\test_realtime_liquidity_market_gate.py tests\test_fresh_opportunity.py >> "%~dp0rapports\check_594.txt" 2>&1
echo. >> "%~dp0rapports\check_594.txt"
echo === 3. l'UI (chemin LIVE) + l'invariant AST anti-formule === >> "%~dp0rapports\check_594.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_ui_simulation_v9_filters.py tests\test_ui_simulation_persistence.py tests\test_noyau_unique.py tests\test_edge_source_q1.py >> "%~dp0rapports\check_594.txt" 2>&1
echo. >> "%~dp0rapports\check_594.txt"
echo === 4. safety-audit === >> "%~dp0rapports\check_594.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\check_594.txt" 2>&1
echo FIN >> "%~dp0rapports\check_594.txt"
exit /b 0
