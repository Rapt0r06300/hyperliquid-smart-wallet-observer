[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$BuildDirectory,
    [switch]$Draft
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$build = [IO.Path]::GetFullPath($BuildDirectory)
$allowed = [IO.Path]::GetFullPath((Join-Path $root "runtime\portable-build")) + [IO.Path]::DirectorySeparatorChar
if (-not $build.StartsWith($allowed, [StringComparison]::OrdinalIgnoreCase)) { throw "Le build doit se trouver dans runtime\portable-build." }
$manifestPath = Join-Path $build "ALINA_FULL_FOLDER_RELEASE.json"
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
$assets = @(Get-Content -LiteralPath (Join-Path $build "ASSETS_A_TELECHARGER.txt"))
foreach ($asset in $assets) { if (-not (Test-Path -LiteralPath $asset -PathType Leaf)) { throw "Asset absent: $asset" } }
$gh = Get-Command gh -ErrorAction SilentlyContinue
if (-not $gh) { throw "GitHub CLI (gh) est requis pour publier la release." }
$arguments = @("release", "create", [string]$manifest.tag, "--repo", [string]$manifest.repository, "--title", "Alina SmartFlow - copie complète $($manifest.git_head.Substring(0,12))", "--notes", "Installateur léger et copie complète vérifiée SHA-256. Téléchargement reprenable des volumes; contenu source: $($manifest.file_count) fichiers, $($manifest.total_bytes) octets.")
if ($Draft) { $arguments += "--draft" }
$arguments += "--"
$arguments += $assets
& $gh.Source @arguments
if ($LASTEXITCODE -ne 0) { throw "Publication GitHub échouée." }
