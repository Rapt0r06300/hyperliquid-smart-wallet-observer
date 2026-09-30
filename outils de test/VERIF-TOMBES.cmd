@echo off
REM Verif : les 2 tombes (capital_allocation, order_rejection) sortent du limbe risk/.
cd /d "%~dp0.."
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
echo.
echo === VERIF TOMBES (entre-deux risk/) ===
echo.
python -m pytest -q "tests\test_risk_guards_no_limbo.py::test_aucun_garde_fou_ne_reste_dans_l_entre_deux" "tests\test_risk_guards_no_limbo.py::test_toute_tombe_designe_un_module_qui_existe_vraiment" tests\test_capital_allocation.py tests\test_order_rejection.py > verif-tombes-resultat.txt 2>&1
type verif-tombes-resultat.txt
echo.
echo === FIN ( verif-tombes-resultat.txt ) ===
pause
