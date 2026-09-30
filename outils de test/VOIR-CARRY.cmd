@echo off
REM ============================================================================
REM  VOIR L'ETAT DU CARRY (paper) : coins viables, positions ouvertes, PnL.
REM  100%% LECTURE SEULE -- n'ecrit rien, ne trade rien, aucun ordre reel.
REM  Double-clique ce fichier a tout moment pour voir ou en est le carry.
REM ============================================================================
cd /d "%~dp0.."
set "PYTHONIOENCODING=utf-8"
python tools\voir_carry.py
echo.
pause
