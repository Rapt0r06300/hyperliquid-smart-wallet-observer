@echo off
rem Compatibility name for the canonical RESTORE_ALINA.cmd launcher.
rem Forward every argument and preserve the exact restore exit code.
setlocal EnableExtensions DisableDelayedExpansion
call "%~dp0RESTORE_ALINA.cmd" %*
exit /b %ERRORLEVEL%
