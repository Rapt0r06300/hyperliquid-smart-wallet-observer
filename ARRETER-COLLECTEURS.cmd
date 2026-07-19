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

powershell -NoProfile -Command ^
  "$c = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*boucle_collecteur.cmd*' };" ^
  "if (-not $c) { Write-Host '  aucun collecteur en cours.' ; exit 0 };" ^
  "$c | ForEach-Object { Write-Host ('  arret PID ' + $_.ProcessId + ' -- ' + ($_.CommandLine.Substring(0,[Math]::Min(90,$_.CommandLine.Length)))) };" ^
  "$c | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch { Write-Host ('  (deja termine : ' + $_.ProcessId + ')') } };" ^
  "Write-Host '' ; Write-Host ('  ' + $c.Count + ' collecteur(s) arrete(s).')"

echo.
echo Les journaux restent lisibles dans runtime\logs\ :
echo    carry-feeder.log  ^|  marks-collector.log  ^|  liq-collector.log
echo.
pause
