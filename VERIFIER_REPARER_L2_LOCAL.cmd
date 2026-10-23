@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0" || exit /b 2
echo ALINA_LOCAL_L2_AUDIT: checking already downloaded SAFE shards, no download.
if exist "%~dp0tools\python\python.exe" (
  "%~dp0tools\python\python.exe" tools\certify_local_l2.py --repair %*
  goto :done
)
where py >nul 2>nul && (
  py -3 tools\certify_local_l2.py --repair %*
  goto :done
)
where python >nul 2>nul && (
  python tools\certify_local_l2.py --repair %*
  goto :done
)
echo Python 3.10+ is required.
exit /b 2
:done
set "RESULT=%ERRORLEVEL%"
echo.
echo Report: runtime\recovery\full\LOCAL_L2_CERTIFICATION.json
echo Exit code: %RESULT%  (1 = some L2 shards blocked, 2 = infrastructure failure)
if "%~1"=="" pause
exit /b %RESULT%
