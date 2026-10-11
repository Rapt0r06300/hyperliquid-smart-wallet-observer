@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0" || (
  echo ALINA_RESTORE_FAIL: cannot open the cloned repository directory.
  exit /b 2
)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
rem Restore is strictly read-only against GitHub. No collector is stopped.
rem The Python restore verifies the canonical SHA-bound catalog and every
rem Release/LFS asset before placing any shard under usable/.
rem Do not force git lfs pull here: space requirements must be preflighted.
rem On large restores, use a read-only GitHub session without printing/storing tokens.
if not defined GH_TOKEN if not defined GITHUB_TOKEN (
  where gh >nul 2>nul
  if not errorlevel 1 (
    for /f "delims=" %%T in ('gh auth token 2^>nul') do set "GH_TOKEN=%%T"
  )
)
if not defined GH_TOKEN if not defined GITHUB_TOKEN (
  echo ALINA_RESTORE_AUTH_WARNING: GitHub anonymous API quotas may block this large restore.
  echo Use 'gh auth login' or set GH_TOKEN / GITHUB_TOKEN if rate-limited.
)
rem Python >= 3.10 is required. A broken embedded interpreter, missing
rem py -3 installation, or Windows Store alias must not block another valid one.
if exist "%~dp0tools\python\python.exe" (
  "%~dp0tools\python\python.exe" -c "import sys; sys.exit(sys.version_info[:2] < (3, 10))" >nul 2>nul && goto :embedded
)
where py >nul 2>nul && py -3 -c "import sys; sys.exit(sys.version_info[:2] < (3, 10))" >nul 2>nul && goto :pylauncher
where python >nul 2>nul && python -c "import sys; sys.exit(sys.version_info[:2] < (3, 10))" >nul 2>nul && goto :system
echo ALINA_RESTORE_FAIL: Python 3.10 or newer is required (embedded, py -3 or python).
exit /b 2

:embedded
"%~dp0tools\python\python.exe" tools\restore_alina.py --everything --destination "runtime\recovery\full" %*
exit /b %ERRORLEVEL%

:pylauncher
py -3 tools\restore_alina.py --everything --destination "runtime\recovery\full" %*
exit /b %ERRORLEVEL%

:system
python tools\restore_alina.py --everything --destination "runtime\recovery\full" %*
exit /b %ERRORLEVEL%
