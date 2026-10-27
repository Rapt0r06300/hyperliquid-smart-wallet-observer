@echo off
REM [Bloc 57] Recette Windows un double-clic : smoke offline de HyperLab.
REM Paper / read-only : 0 ordre reel, 0 cle privee, 0 endpoint /exchange, capital fictif <= 1000 USD.
setlocal
for %%I in ("%~dp0..\..") do set "ALINA_PROJECT_ROOT=%%~fI"
cd /d "%ALINA_PROJECT_ROOT%" || exit /b 1
cd /d "%ALINA_PROJECT_ROOT%\"
echo === HyperLab smoke (offline, paper) ===
python -m pip install -e . 1>nul 2>nul
python -m hl_observer.hyperlab smoke
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (echo SMOKE OK) else (echo SMOKE ECHEC code=%RC%)
echo Collecte live = REQUIRES_NETWORK (hors de ce smoke).
pause
exit /b %RC%
