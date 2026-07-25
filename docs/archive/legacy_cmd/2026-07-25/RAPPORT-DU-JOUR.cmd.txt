@echo off
REM ============================================================================
REM  RAPPORT DU JOUR — la verite du bot en UNE page (R6, 20/07)
REM ============================================================================
REM  Double-clique : le rapport s'ecrit dans rapports\RAPPORT_DU_JOUR.md
REM  (+ une copie datee dans rapports\archive_quotidienne\) et s'affiche ici.
REM
REM  Chaque chiffre se remonte a un fichier (ledger, positions, journaux).
REM  Lecture seule. 0 ordre reel, 0 cle, 0 signature.
REM ============================================================================
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
python tools\rapport_quotidien.py
echo.
pause
