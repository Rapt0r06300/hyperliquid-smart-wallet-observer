@echo off
REM ============================================================================
REM  REDEMARRER-USERFILLS — recharge le collecteur userfills avec le CODE COURANT
REM ----------------------------------------------------------------------------
REM  Un seul double-clic : (1) tue l'ancien enfant python + son wrapper
REM  boucle_collecteur + libère le verrou ; (2) relance le collecteur détaché,
REM  sans fenêtre, qui recharge le code courant (RAW 10$, gate d'âge, déclencheur
REM  relatif au vault, 10 places WS, watcher PREMIER_RAW). Auto-sûr (ne matche que
REM  python/cmd du collecteur). Lecture seule marché. 0 ordre, 0 clé, 0 signature.
REM ============================================================================
cd /d "%~dp0"
echo Rechargement du collecteur userfills-live avec le code courant...
echo.
powershell -NoProfile -Command ^
  "$p = '%~dp0';" ^
  "$lk = Join-Path $p 'runtime\data\userfills_live.lock';" ^
  "if (Test-Path $lk) { try { $pid0 = (Get-Content $lk -Raw | ConvertFrom-Json).pid; Write-Host ('  verrou PID ' + $pid0 + ' -> arret'); Stop-Process -Id $pid0 -Force -ErrorAction SilentlyContinue } catch {} };" ^
  "$morts = Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -and ( (($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -like '*collecter_userfills_vaults.py*') -or ($_.Name -eq 'cmd.exe' -and $_.CommandLine -like '*boucle_collecteur.cmd userfills-live*') ) };" ^
  "foreach ($m in $morts) { Write-Host ('  arret ' + $m.Name + ' PID ' + $m.ProcessId); Stop-Process -Id $m.ProcessId -Force -ErrorAction SilentlyContinue };" ^
  "Start-Sleep -Milliseconds 900;" ^
  "Remove-Item $lk -Force -ErrorAction SilentlyContinue;" ^
  "Start-Process -WindowStyle Hidden -FilePath 'cmd.exe' -ArgumentList '/c','tools\boucle_collecteur.cmd userfills-live tools\collecter_userfills_vaults.py 5' -WorkingDirectory $p;" ^
  "Write-Host '  collecteur relance (detache, sans fenetre, code courant).'"
echo.
timeout /t 9 >nul
if exist "runtime\data\userfills_live.lock" (
  echo   OK : verrou recree -> collecteur en cours (nouveau pid/run_id) :
  type "runtime\data\userfills_live.lock"
) else (
  echo   Pas encore de verrou ^(demarrage en cours, patiente ~10 s^).
)
echo.
pause
