@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   PAGE-KAITO - la progression de T1, en direct.
REM   ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py).
REM
REM   Sert http://127.0.0.1:8799/ et ouvre le navigateur.
REM   Elle ne fait que LIRE les fichiers deja enregistres par l'ecoute 4 h.
REM   Aucun ordre, aucune cle, aucune signature. Ferme cette fenetre pour l'arreter.
REM ==================================================================================
echo.
echo =============================================================
echo   PAGE KAITO - progression T1 (lecture seule)
echo =============================================================
echo.
echo   [1/2] Test de la page (l'ETA ne doit jamais etre invente)
python -m pytest -q --tb=short -p no:cacheprovider tests\test_page_kaito.py
echo.
echo   [2/2] Demarrage du serveur local + ouverture du navigateur...
start "" "http://127.0.0.1:8799/"
python tools\page_kaito.py --port 8799
echo.
pause
