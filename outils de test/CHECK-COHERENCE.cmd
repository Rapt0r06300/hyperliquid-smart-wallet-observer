@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   L'INCOHERENCE VUE PAR FLO : le registre refusait sur des MOTS-CLES.
REM   Une zone morte doit declarer l'ENTREE qu'elle a mesuree.
REM   SUITE COMPLETE + SAFETY. ASCII PUR, pas de pause -> "%~dp0rapports\check_coherence.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_coherence.txt"
echo === SUITE COMPLETE === >> "%~dp0rapports\check_coherence.txt"
python -m pytest -q -p no:cacheprovider --tb=short >> "%~dp0rapports\check_coherence.txt" 2>&1
echo. >> "%~dp0rapports\check_coherence.txt"
echo === SAFETY (no-real-trade) === >> "%~dp0rapports\check_coherence.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\check_coherence.txt" 2>&1
echo FIN >> "%~dp0rapports\check_coherence.txt"
exit /b 0
