@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #599 -- ou vivent les 16 % de lignes jamais executees ?
REM   + #591 -- le garde-fou AFFAME (l'estimateur de vol n'etait nourri que si une
REM             position etait deja ouverte, alors que le veto d'ENTREE le consomme)
REM   ASCII PUR, pas de pause -> "%~dp0rapports\analyse_599.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\analyse_599.txt"
echo === 1. #591 -- le garde-fou affame === >> "%~dp0rapports\analyse_599.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_garde_fou_affame_591.py tests\test_vol_adjusted_barriers.py tests\test_market_quality_score.py >> "%~dp0rapports\analyse_599.txt" 2>&1
echo. >> "%~dp0rapports\analyse_599.txt"
echo === 2. #599 -- ou vivent les lignes jamais executees === >> "%~dp0rapports\analyse_599.txt"
python tools\analyser_couverture_599.py >> "%~dp0rapports\analyse_599.txt" 2>&1
echo FIN >> "%~dp0rapports\analyse_599.txt"
exit /b 0
