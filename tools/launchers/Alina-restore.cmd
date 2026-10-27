@echo off
rem Compatibility name for the canonical RESTORE_ALINA.cmd launcher.
rem Forward every argument and preserve the exact restore exit code.
setlocal EnableExtensions DisableDelayedExpansion
for %%I in ("%~dp0..\..") do set "ALINA_PROJECT_ROOT=%%~fI"
cd /d "%ALINA_PROJECT_ROOT%" || exit /b 1
call "%ALINA_PROJECT_ROOT%\tools\launchers\RESTORE_ALINA.cmd" %*
exit /b %ERRORLEVEL%
