@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #597 -- la porte des OUTILS de recherche. Le plafond BAISSE (304 -> 273).
REM   ASCII PUR, pas de pause -> check_597.txt
REM ==================================================================================
echo DEBUT > check_597.txt
echo === 1. l'audit de cablage : ses propres tests === >> check_597.txt
python -m pytest -q --tb=short -p no:cacheprovider tests\test_audit_cablage.py >> check_597.txt 2>&1
echo. >> check_597.txt
echo === 2. LE CLIQUET + les invariants de limbe (T3b/T3c) === >> check_597.txt
python -m pytest -q --tb=short -p no:cacheprovider tests\test_risk_guards_no_limbo.py >> check_597.txt 2>&1
echo. >> check_597.txt
echo === 3. non-regression : edge Q1/G2 + tombes + couverture === >> check_597.txt
python -m pytest -q --tb=line -p no:cacheprovider tests\test_edge_source_q1.py tests\test_measured_edge_table.py tests\test_tombes_remplacants_vivants.py tests\test_couverture_cliquet.py tests\test_outils_isoles_du_ctrl_c.py >> check_597.txt 2>&1
echo. >> check_597.txt
echo === 4. l'outil T3-CABLAGE tourne-t-il encore ? === >> check_597.txt
python tools\auditer_cablage.py > t3_cablage.txt 2>&1
echo code retour audit_cablage = %ERRORLEVEL% >> check_597.txt
findstr /C:"0. OUTILLES" t3_cablage.txt >> check_597.txt
findstr /C:"module(s) de RECHERCHE" t3_cablage.txt >> check_597.txt
echo. >> check_597.txt
echo === 5. safety-audit === >> check_597.txt
python -m hl_observer safety-audit >> check_597.txt 2>&1
echo FIN >> check_597.txt
exit /b 0
