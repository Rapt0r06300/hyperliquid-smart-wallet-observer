@echo off
REM ============================================================
REM  Verif RAPIDE du fix carry_scanner (revert PORTE 3bis)
REM  + tous les modules crees dans la session du 16/07.
REM  100%% lecture seule. Ecrit verif-fix-resultat.txt a la racine.
REM ============================================================
cd /d "%~dp0.."
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
echo.
echo === VERIF DU FIX + modules de la session (16/07) ===
echo.
python -m pytest -q tests\test_carry_scanner.py tests\test_carry_ranking.py tests\test_carry_inversion_guard.py tests\test_funding_prediction.py tests\test_anti_lookahead_pipeline.py tests\test_capital_allocation.py tests\test_order_split_benefit.py tests\test_liquidation_net.py tests\test_market_impact.py tests\test_markout_validation.py tests\test_fill_intensity.py tests\test_queue_model.py tests\test_order_rejection.py > verif-fix-resultat.txt 2>&1
type verif-fix-resultat.txt
echo.
echo === FIN ( verif-fix-resultat.txt ecrit a la racine ) ===
pause
