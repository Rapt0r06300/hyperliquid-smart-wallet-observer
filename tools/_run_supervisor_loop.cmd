@echo off
rem Wrapper : boucle resiliente du SUPERVISEUR de collecteurs, SANS fenetre.
rem Appele par LANCER_COLLECTEURS via start /B. Herite CV_* et PYTHONPATH.
rem Sortie -> runtime\logs\supervisor.log. Arret via stop_collecteurs.flag + watchdog --stop.
rem PAPER / lecture seule.
set "CV_RESTARTS=0"
set "CV_BACKOFF=%CV_BACKOFF_INIT%"
set "SUPLOG=%CV_ROOT%runtime\logs\supervisor.log"
:campagne
if exist "%CV_ROOT%runtime\data\stop_collecteurs.flag" goto :fin
set /a CV_RESTARTS+=1
if %CV_RESTARTS% GTR %CV_MAX_RESTARTS% goto :fin
"%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\watch_economic_collectors.py" --root "%CV_ROOT%." --profile %CV_PROFILE% --interval-s %CV_INTERVAL% --duration-s %CV_DURATION% --lease-duration-s %CV_LEASE% >> "%SUPLOG%" 2>&1
set "RC=%ERRORLEVEL%"
if exist "%CV_ROOT%runtime\data\stop_collecteurs.flag" goto :fin
if "%RC%"=="130" goto :fin
if not "%RC%"=="0" goto :backoff
if /I "%CV_MODE%"=="once" goto :fin
goto :campagne
:backoff
>>"%CV_ROOT%runtime\logs\collecteur_restarts.log" echo RESTART=%CV_RESTARTS% RC=%RC% BACKOFF=%CV_BACKOFF%s
timeout /t %CV_BACKOFF% /nobreak >nul 2>nul
set /a CV_BACKOFF=%CV_BACKOFF% * 2
if %CV_BACKOFF% GTR %CV_BACKOFF_MAX% set "CV_BACKOFF=%CV_BACKOFF_MAX%"
if /I "%CV_MODE%"=="once" goto :fin
goto :campagne
:fin
