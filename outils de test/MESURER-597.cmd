@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #597 -- la porte que l'audit ne voyait pas : les OUTILS de recherche.
REM   ASCII PUR, pas de pause -> "%~dp0rapports\mesure_597.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\mesure_597.txt"
python tools\mesurer_cablage_597.py >> "%~dp0rapports\mesure_597.txt" 2>&1
echo. >> "%~dp0rapports\mesure_597.txt"
echo === tests unitaires de l'audit de cablage === >> "%~dp0rapports\mesure_597.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_audit_cablage.py >> "%~dp0rapports\mesure_597.txt" 2>&1
echo FIN >> "%~dp0rapports\mesure_597.txt"
exit /b 0
