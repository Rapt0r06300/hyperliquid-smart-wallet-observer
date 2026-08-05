@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   Q1 - LA TABLE D'EDGE MESUREE. L'edge brut ne vient plus d'une formule inventee.
REM
REM   1. mesure le MARKOUT REEL de chaque signal enregistre (ce que le prix a FAIT) ;
REM   2. coupe chronologiquement train/test ;
REM   3. construit la table sur le train ;
REM   4. PURGE les alphas fantomes : ne livre que ce qui survit au TEST.
REM
REM   ASCII PUR, pas de "chcp". Sans pause : tout va dans q1_table_edge.txt.
REM   Lecture seule (fichiers replay). Aucun ordre, aucune cle, aucune signature.
REM ==================================================================================
(
  echo === [1/2] Construction + validation hors-echantillon ===
  python tools\construire_table_edge.py --horizon-s 60 --min-n 30
  echo.
  echo === [2/2] Les tests de Q1 ===
  python -m pytest -q --tb=short -p no:cacheprovider tests\test_measured_edge_table.py tests\test_edge_source_q1.py
) > "%~dp0rapports\q1_table_edge.txt" 2>&1
exit /b 0
