@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #597 -- la porte des OUTILS de recherche. Le plafond BAISSE (304 -> 273).
REM   ASCII PUR, pas de pause -> "%~dp0rapports\check_597.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_597.txt"
echo === 1. l'audit de cablage : ses propres tests === >> "%~dp0rapports\check_597.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_audit_cablage.py >> "%~dp0rapports\check_597.txt" 2>&1
echo. >> "%~dp0rapports\check_597.txt"
echo === 2. LE CLIQUET + les invariants de limbe (T3b/T3c) === >> "%~dp0rapports\check_597.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_risk_guards_no_limbo.py >> "%~dp0rapports\check_597.txt" 2>&1
echo. >> "%~dp0rapports\check_597.txt"
echo === 3. non-regression : edge Q1/G2 + tombes + couverture === >> "%~dp0rapports\check_597.txt"
python -m pytest -q --tb=line -p no:cacheprovider tests\test_edge_source_q1.py tests\test_measured_edge_table.py tests\test_tombes_remplacants_vivants.py tests\test_couverture_cliquet.py tests\test_outils_isoles_du_ctrl_c.py >> "%~dp0rapports\check_597.txt" 2>&1
echo. >> "%~dp0rapports\check_597.txt"
echo === 4. l'outil T3-CABLAGE tourne-t-il encore ? === >> "%~dp0rapports\check_597.txt"
python tools\auditer_cablage.py > "%~dp0rapports\t3_cablage.txt" 2>&1
echo code retour audit_cablage = %ERRORLEVEL% >> "%~dp0rapports\check_597.txt"
findstr /C:"0. OUTILLES" t3_cablage.txt >> "%~dp0rapports\check_597.txt"
findstr /C:"module(s) de RECHERCHE" t3_cablage.txt >> "%~dp0rapports\check_597.txt"
echo. >> "%~dp0rapports\check_597.txt"
echo === 5. safety-audit === >> "%~dp0rapports\check_597.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\check_597.txt" 2>&1
echo FIN >> "%~dp0rapports\check_597.txt"
exit /b 0
