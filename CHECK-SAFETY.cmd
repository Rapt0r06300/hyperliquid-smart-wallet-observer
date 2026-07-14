@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
echo DEBUT > check_safety.txt
echo === safety-audit === >> check_safety.txt
python -m hl_observer safety-audit >> check_safety.txt 2>&1
echo. >> check_safety.txt
echo === doctor === >> check_safety.txt
python -m hl_observer doctor >> check_safety.txt 2>&1
echo. >> check_safety.txt
echo === le cliquet de cablage + l'invariant Ctrl-C etendu aux tests === >> check_safety.txt
python -m pytest -q --tb=line -p no:cacheprovider tests\test_risk_guards_no_limbo.py tests\test_outils_isoles_du_ctrl_c.py tests\test_env_hermetique.py >> check_safety.txt 2>&1
echo FIN >> check_safety.txt
exit /b 0
