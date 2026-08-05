@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #112 : la latence des REFUS (fin du biais de survivant dans l'instrumentation).
REM   #121 : le cliquet de couverture -- le nombre de modules non testes ne monte plus.
REM   ASCII PUR, pas de pause -> "%~dp0rapports\check_112_121.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_112_121.txt"
echo === 1 sur 4 : poser la baseline de couverture === >> "%~dp0rapports\check_112_121.txt"
python tools\poser_baseline_couverture.py >> "%~dp0rapports\check_112_121.txt" 2>&1
echo. >> "%~dp0rapports\check_112_121.txt"
echo === 2 sur 4 : le cliquet tient === >> "%~dp0rapports\check_112_121.txt"
python -m pytest -q -s --tb=short -p no:cacheprovider tests\test_couverture_cliquet.py >> "%~dp0rapports\check_112_121.txt" 2>&1
echo. >> "%~dp0rapports\check_112_121.txt"
echo === 3 sur 4 : la latence des REFUS est journalisee === >> "%~dp0rapports\check_112_121.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_latency_journal.py tests\test_latency_trace.py >> "%~dp0rapports\check_112_121.txt" 2>&1
echo. >> "%~dp0rapports\check_112_121.txt"
echo === 4 sur 4 : non-regression du chemin vivant + safety === >> "%~dp0rapports\check_112_121.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_fusion_paper_engine_adapter.py tests\test_no_real_trade_foundations.py >> "%~dp0rapports\check_112_121.txt" 2>&1
python -m hl_observer safety-audit >> "%~dp0rapports\check_112_121.txt" 2>&1
echo FIN >> "%~dp0rapports\check_112_121.txt"
exit /b 0
