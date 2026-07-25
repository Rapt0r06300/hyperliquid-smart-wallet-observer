@echo off
REM Retire la tache planifiee du verificateur OOS shadow.
set "TN=HyperSmart_VerifOOS"
schtasks /Delete /TN "%TN%" /F
if %ERRORLEVEL%==0 (echo Tache "%TN%" supprimee.) else (echo Tache "%TN%" absente ou non supprimee.)
pause
