@echo off
REM ============================================================================
REM  TUER L'ORPHELIN userfills-live (fix chirurgical Flo 23/07)
REM ----------------------------------------------------------------------------
REM  Probleme : le collecteur userfills persistant peut rester ORPHELIN (ancien
REM  code) et garder le verrou runtime\data\userfills_live.lock -> bloque la
REM  relance du NOUVEAU code (RAW_PROBE). ARRETER-COLLECTEURS s'auto-tuait
REM  (sa propre ligne de commande matchait le filtre projet+.py).
REM
REM  Ce script est AUTO-SUR : il ne matche QUE python.exe / pythonw.exe dont la
REM  ligne de commande contient 'collecter_userfills_vaults.py'. Un powershell ne
REM  porte jamais ce nom -> aucune auto-terminaison possible. Il tue AUSSI, par
REM  PID, le detenteur du verrou lu directement dans le fichier .lock.
REM ============================================================================
cd /d "%~dp0"
echo Arret cible de l'orphelin userfills-live...
echo.
powershell -NoProfile -Command ^
  "$projet = '%~dp0';" ^
  "$lk = Join-Path $projet 'runtime\data\userfills_live.lock';" ^
  "if (Test-Path $lk) {" ^
  "  try {" ^
  "    $p = (Get-Content $lk -Raw | ConvertFrom-Json).pid;" ^
  "    Write-Host ('  verrou detenu par PID ' + $p + ' -- arret force...');" ^
  "    Stop-Process -Id $p -Force -ErrorAction SilentlyContinue;" ^
  "    Start-Sleep -Milliseconds 700;" ^
  "    Remove-Item $lk -Force -ErrorAction SilentlyContinue;" ^
  "    Write-Host ('  PID ' + $p + ' arrete, verrou supprime.')" ^
  "  } catch { Write-Host ('  echec lecture verrou : ' + $_) }" ^
  "} else { Write-Host '  pas de fichier verrou (deja libere).' };" ^
  "$py = Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -like '*collecter_userfills_vaults.py*' };" ^
  "if ($py) { foreach ($x in $py) { Write-Host ('  python collecteur PID ' + $x.ProcessId + ' -- arret force...'); Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue } } else { Write-Host '  aucun python collecteur userfills residuel.' };" ^
  "Start-Sleep -Milliseconds 300;" ^
  "if (Test-Path $lk) { Write-Host '  ATTENTION : le verrou existe encore.' } else { Write-Host '  OK : plus de verrou userfills.' }"
echo.
echo Termine. Tu peux relancer LANCER_HYPERSMART.cmd
echo.
pause
