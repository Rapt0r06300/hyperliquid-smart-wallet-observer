# Afficheur du tableau de bord de la moisson -- SANS CLIGNOTEMENT et SANS SAUT.
#
# Le secret : on ecrit EXACTEMENT la hauteur de la fenetre a chaque fois, depuis le
# coin (0,0). Comme on ne depasse jamais le bas de la fenetre, elle ne peut PAS defiler
# -> plus de "saut", plus de "quand je descends ca remonte".
#
# Il ne fait que LIRE moisson-en-cours.txt. Aucun reseau, aucune action.

param([string]$Root = "")

# Le .cmd passe "%~dp0" qui finit par un backslash -> PowerShell casse le guillemet et
# le chemin recu est invalide. On ignore donc un $Root inutilisable et on DERIVE la racine
# du script lui-meme : voir_dashboard.ps1 est dans tools\, la racine est le dossier parent.
if ([string]::IsNullOrWhiteSpace($Root) -or -not (Test-Path -LiteralPath $Root)) {
  if ($PSScriptRoot) { $Root = Split-Path $PSScriptRoot -Parent } else { $Root = (Get-Location).Path }
}

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
try { $Host.UI.RawUI.WindowTitle = 'Tableau de bord - Moisson' } catch {}
try { [Console]::CursorVisible = $false } catch {}
# 🔒 Ctrl+C ne doit PAS cracher d'erreurs rouges ni declencher "Terminer le programme (O/N)".
#    On le capture comme une simple touche (ignoree) : pour arreter, on ferme la fenetre.
try { [Console]::TreatControlCAsInput = $true } catch {}

$fichier = Join-Path $Root 'moisson-en-cours.txt'
$flag    = Join-Path $Root 'moisson-termine.flag'

Clear-Host

while ($true) {
  $fin = Test-Path $flag

  $wh = [Console]::WindowHeight
  $ww = [Console]::WindowWidth - 1

  $lines = @()
  if (Test-Path $fichier) {
    try { $lines = Get-Content $fichier -Encoding UTF8 -ErrorAction SilentlyContinue } catch { $lines = @() }
  } else {
    $lines = @('', '   Demarrage de la moisson...', '   (le canari verifie le trieur, puis il indexe notre code)')
  }

  # On dessine EXACTEMENT (hauteur - 1) lignes, depuis le haut. Jamais plus -> pas de scroll.
  try { [Console]::SetCursorPosition(0, 0) } catch {}
  for ($k = 0; $k -lt ($wh - 1); $k++) {
    if ($k -lt $lines.Count) { $l = [string]$lines[$k] } else { $l = '' }
    if ($l.Length -gt $ww) { $l = $l.Substring(0, $ww) }
    [Console]::Write($l.PadRight($ww))
    if ($k -lt ($wh - 2)) { [Console]::Write("`r`n") }
  }

  if ($fin) { break }
  Start-Sleep -Milliseconds 1500
}

try { [Console]::CursorVisible = $true } catch {}
Clear-Host
if (Test-Path $fichier) { Get-Content $fichier -Encoding UTF8 | Write-Host }
Write-Host ''
Write-Host '   ================================================================'
Write-Host '     MOISSON TERMINEE.  Resultat : moisson-fini.md  (a la racine)'
Write-Host '   ================================================================'
