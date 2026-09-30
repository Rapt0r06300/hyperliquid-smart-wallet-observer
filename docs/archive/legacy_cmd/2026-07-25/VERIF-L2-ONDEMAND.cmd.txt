@echo off
REM ============================================================================
REM  VERIF-L2-ONDEMAND — prouve que le lecteur L2 on-demand rend un carnet FRAIS
REM  (<1 s) pour les coins CANDIDATS (WLD/AERO/TIA/IO/LDO), l'etape qui bloquait
REM  RAW_PROBE (REFUS:L2_INDISPONIBLE_1S). Lecture seule (l2Book public). 0 ordre.
REM  Ecrit le resultat dans runtime\data\verif_l2_ondemand.txt ET a l'ecran.
REM ============================================================================
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
if not exist "runtime\data" mkdir "runtime\data" >nul 2>&1
python -c "import sys; sys.path.insert(0,'tools'); import collecter_userfills_vaults as C; [print(c, C._lecteur_l2_ondemand(c)) for c in ('WLD','AERO','TIA','IO','LDO','SOL')]" > "runtime\data\verif_l2_ondemand.txt" 2>&1
type "runtime\data\verif_l2_ondemand.txt"
echo.
pause
