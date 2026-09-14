[CmdletBinding()]
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$Tag = "",
    [string]$OutputDirectory = "",
    [ValidateRange(64, 2000)][int]$VolumeMiB = 1900,
    [ValidateRange(1, 8)][int]$CompressionThreads = 2
)

$ErrorActionPreference = "Stop"
$rootPath = [IO.Path]::GetFullPath($Root)
$git = Join-Path $rootPath "tools\git\cmd\git.exe"
$python = Join-Path $rootPath "portable_runtime\python_backup_20260813_224532\python.exe"
$sevenZip = "C:\Program Files\7-Zip\7z.exe"
$sevenZipDll = "C:\Program Files\7-Zip\7z.dll"
$compiler = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
foreach ($required in @($git, $python, $sevenZip, $sevenZipDll, $compiler)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Outil requis absent: $required" }
}

$head = (& $git -C $rootPath rev-parse HEAD).Trim()
& $git -C $rootPath merge-base --is-ancestor origin/main HEAD
if ($LASTEXITCODE -ne 0) { throw "La branche locale doit contenir intégralement origin/main avant construction." }
$status = @(& $git -C $rootPath status --porcelain=v1 --untracked-files=all)
if ($LASTEXITCODE -ne 0 -or $status.Count -ne 0) { throw ("Le dépôt doit être propre avant construction." + [Environment]::NewLine + ($status -join [Environment]::NewLine)) }
if ([string]::IsNullOrWhiteSpace($Tag)) { $Tag = "alina-full-" + $head.Substring(0, 12) }
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $rootPath ("runtime\portable-build\" + $Tag)
}
$output = [IO.Path]::GetFullPath($OutputDirectory)
if (-not $output.StartsWith($rootPath + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "La sortie doit rester dans le dépôt."
}
if (Test-Path -LiteralPath $output) {
    $resolvedOutput = (Resolve-Path -LiteralPath $output).Path
    if (-not $resolvedOutput.StartsWith((Join-Path $rootPath "runtime\portable-build") + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refus de nettoyer une sortie hors runtime\portable-build."
    }
    Remove-Item -LiteralPath $resolvedOutput -Recurse -Force
}
New-Item -ItemType Directory -Path $output | Out-Null

Write-Host "1/4 Inventaire et SHA-256 des fichiers source..."
& $python -m hl_observer.ops.full_folder_release plan --root $rootPath --output $output --head $head
if ($LASTEXITCODE -ne 0) { throw "Échec de l'inventaire." }

Write-Host "2/4 Création des volumes 7-Zip de $VolumeMiB Mio..."
$archive = Join-Path $output "Alina-SmartFlow-Full.7z"
$members = Join-Path $output "archive-members.txt"
$volumeArgument = "-v" + $VolumeMiB + "m"
$arguments = @(
    "a", ('"' + $archive + '"'), "-t7z", "-mx=0", "-mmt=$CompressionThreads",
    $volumeArgument, "-scsUTF-8", "-bsp1", ('@"' + $members + '"')
)
$process = Start-Process -FilePath $sevenZip -ArgumentList $arguments -WorkingDirectory $rootPath -Wait -PassThru -NoNewWindow
if ($process.ExitCode -ne 0) { throw "7-Zip a échoué, code $($process.ExitCode)." }

Write-Host "3/4 SHA-256 des volumes et manifeste final..."
& $python -m hl_observer.ops.full_folder_release finalize --root $rootPath --output $output --tag $Tag --head $head --repository "Rapt0r06300/hyperliquid-smart-wallet-observer"
if ($LASTEXITCODE -ne 0) { throw "Échec de la finalisation." }

$manifest = Join-Path $output "ALINA_FULL_FOLDER_RELEASE.json"
$manifestHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $manifest).Hash.ToLowerInvariant()
$manifestUrl = "https://github.com/Rapt0r06300/hyperliquid-smart-wallet-observer/releases/download/$([Uri]::EscapeDataString($Tag))/ALINA_FULL_FOLDER_RELEASE.json"
$template = Get-Content -Raw -LiteralPath (Join-Path $rootPath "tools\full_folder_installer\ReleaseInfo.template.cs")
$releaseInfo = $template.Replace("__REPOSITORY__", "Rapt0r06300/hyperliquid-smart-wallet-observer").Replace("__TAG__", $Tag).Replace("__GIT_HEAD__", $head).Replace("__MANIFEST_SHA256__", $manifestHash).Replace("__MANIFEST_URL__", $manifestUrl)
$releaseInfoPath = Join-Path $output "ReleaseInfo.generated.cs"
[IO.File]::WriteAllText($releaseInfoPath, $releaseInfo, [Text.UTF8Encoding]::new($false))
$installer = Join-Path $output "Installer-Alina-SmartFlow.exe"
$installerSource = Join-Path $rootPath "tools\full_folder_installer\AlinaFullInstaller.cs"
Write-Host "4/4 Compilation du petit installateur..."
& $compiler /nologo /optimize+ /target:exe /platform:anycpu /out:$installer /reference:System.Web.Extensions.dll /resource:"$sevenZip,Alina.Embedded.7z.exe" /resource:"$sevenZipDll,Alina.Embedded.7z.dll" $installerSource $releaseInfoPath
if ($LASTEXITCODE -ne 0) { throw "Compilation de l'installateur échouée." }

$assets = @($installer, $manifest, (Join-Path $output "ALINA_FULL_FOLDER_INVENTORY.json")) + @(Get-ChildItem -LiteralPath $output -Filter "Alina-SmartFlow-Full.7z.*" | Sort-Object Name | ForEach-Object FullName)
$uploadList = Join-Path $output "ASSETS_A_TELECHARGER.txt"
[IO.File]::WriteAllLines($uploadList, $assets, [Text.UTF8Encoding]::new($false))
[pscustomobject]@{
    ok = $true
    tag = $Tag
    git_head = $head
    output = $output
    installer = $installer
    asset_count = $assets.Count
    manifest_sha256 = $manifestHash
} | ConvertTo-Json
