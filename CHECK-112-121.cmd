@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #112 : la latence des REFUS (fin du biais de survivant dans l'instrumentation).
REM   #121 : le cliquet de couverture -- le nombre de modules non testes ne monte plus.
REM   ASCII PUR, pas de pause -> check_112_121.txt
REM ==================================================================================
echo DEBUT > check_112_121.txt
echo === 1 sur 4 : poser la baseline de couverture === >> check_112_121.txt
python tools\poser_baseline_couverture.py >> check_112_121.txt 2>&1
echo. >> check_112_121.txt
echo === 2 sur 4 : le cliquet tient === >> check_112_121.txt
python -m pytest -q -s --tb=short -p no:cacheprovider tests\test_couverture_cliquet.py >> check_112_121.txt 2>&1
echo. >> check_112_121.txt
echo === 3 sur 4 : la latence des REFUS est journalisee === >> check_112_121.txt
python -m pytest -q --tb=short -p no:cacheprovider tests\test_latency_journal.py tests\test_latency_trace.py >> check_112_121.txt 2>&1
echo. >> check_112_121.txt
echo === 4 sur 4 : non-regression du chemin vivant + safety === >> check_112_121.txt
python -m pytest -q --tb=short -p no:cacheprovider tests\test_fusion_paper_engine_adapter.py tests\test_no_real_trade_foundations.py >> check_112_121.txt 2>&1
python -m hl_observer safety-audit >> check_112_121.txt 2>&1
echo FIN >> check_112_121.txt
exit /b 0
