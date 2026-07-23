@echo off
REM ============================================================================
REM  ARRETER LES COLLECTEURS DE FOND (carry-feeder / marks / liquidations)
REM ============================================================================
REM  Depuis le 19/07 les collecteurs tournent SANS FENETRE (Flo : « y'a plein de
REM  fenetres qui s'ouvrent et je veux pas ca »). Consequence honnete : on ne peut
REM  plus les fermer d'un clic sur la croix. Ce script existe pour ca.
REM
REM  ⚠️ IL NE TUE PAS PYTHON PAR FILTRE. Un `taskkill /im python.exe` emporterait
REM  le BOT lui-meme, et potentiellement d'autres travaux Python de la machine.
REM  On cible UNIQUEMENT les processus dont la ligne de commande contient
REM  `boucle_collecteur.cmd` -- c'est-a-dire nos collecteurs, et rien d'autre.
REM
REM  Le bot (fenetre principale) n'est PAS affecte : ferme-le normalement.
REM ============================================================================
cd /d "%~dp0"
echo Recherche des collecteurs de fond...
echo.

REM  ⚠️ 23/07 (fix Flo) : on tue AUSSI les ENFANTS python (python ...\tools\xxx.py) spawnes par
REM  boucle_collecteur -- sinon des collecteurs persistants (ex. userfills-live) restaient ORPHELINS.
REM  On reste STRICTEMENT borne aux processus dont la ligne de commande contient CE dossier projet
REM  (%~dp0) -- aucun autre python de la machine n'est touche. + on tue le detenteur du verrou userfills.
powershell -NoProfile -Command ^
  "$projet = '%~dp0';" ^
  "$c = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and ($_.CommandLine -like '*boucle_collecteur.cmd*' -or ($_.CommandLine -like ('*'+$projet+'*') -and $_.CommandLine -like '*.py*')) };" ^
  "if (-not $c) { Write-Host '  aucun collecteur en cours.' } else {" ^
  "  $c | ForEach-Object { Write-Host ('  arret PID ' + $_.ProcessId + ' -- ' + ($_.CommandLine.Substring(0,[Math]::Min(90,$_.CommandLine.Length)))) };" ^
  "  $c | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} };" ^
  "  Write-Host ('  ' + $c.Count + ' processus projet arretes.') };" ^
  "$lk = Join-Path $projet 'runtime\data\userfills_live.lock';" ^
  "if (Test-Path $lk) { try { $p = (Get-Content $lk -Raw | ConvertFrom-Json).pid; Stop-Process -Id $p -Force -ErrorAction SilentlyContinue; Remove-Item $lk -Force -ErrorAction SilentlyContinue; Write-Host ('  verrou userfills libere (PID ' + $p + ')') } catch {} }"

echo.
echo Les journaux restent lisibles dans runtime\logs\ :
echo    carry-feeder.log  ^|  marks-collector.log  ^|  liq-collector.log
echo.
pause
