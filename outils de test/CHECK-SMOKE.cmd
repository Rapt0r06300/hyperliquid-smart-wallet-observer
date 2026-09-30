@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM  Test de fumee : la chaine COMPLETE tourne-t-elle de bout en bout sans crasher ?
REM  Reseau coupe, budget minuscule. -> il attrape les COUTURES que les tests unitaires ratent.
python -m pytest -q -p no:cacheprovider -o cache_dir=%TEMP%\pctest_smoke tests\test_moissonneur_smoke.py > "%~dp0rapports\check_smoke.txt" 2>&1
exit /b 0
