[CmdletBinding()]
param(
    [Parameter()]
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$version = "2.54.0.windows.1"
$archiveName = "MinGit-2.54.0-64-bit.zip"
$downloadUrl = "https://github.com/git-for-windows/git/releases/download/v$version/$archiveName"
$expectedSha256 = "04F937E1F0918B17B9BE6F2294CB2BB66E96E1D9832D1C298E2DE088A1D0E668"

$root = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd("\", "/")
$tools = Join-Path $root "tools"
$target = Join-Path $tools "git"
$gitExe = Join-Path $target "cmd\git.exe"

if (Test-Path -LiteralPath $gitExe -PathType Leaf) {
    $installedVersion = (& $gitExe --version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Git portable deja disponible : $installedVersion" -ForegroundColor Green
        Write-Host "     $gitExe"
        exit 0
    }
}

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("hypersmart-mingit-" + [Guid]::NewGuid().ToString("N"))
$archive = Join-Path $tempRoot $archiveName
$staging = Join-Path $tempRoot "expanded"
New-Item -ItemType Directory -Path $staging -Force | Out-Null

try {
    Write-Host "[1/4] Telechargement officiel de MinGit $version..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $downloadUrl -OutFile $archive -UseBasicParsing

    Write-Host "[2/4] Verification SHA-256..." -ForegroundColor Cyan
    $actualSha256 = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($actualSha256 -ne $expectedSha256) {
        throw "Archive MinGit refusee : SHA-256 inattendu ($actualSha256)."
    }

    Write-Host "[3/4] Extraction dans le runtime portable..." -ForegroundColor Cyan
    Expand-Archive -LiteralPath $archive -DestinationPath $staging -Force
    $stagedGit = Join-Path $staging "cmd\git.exe"
    if (-not (Test-Path -LiteralPath $stagedGit -PathType Leaf)) {
        throw "MinGit extrait ne contient pas cmd\git.exe."
    }

    if (Test-Path -LiteralPath $target) {
        $backup = Join-Path $tools ("git_backup_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
        Move-Item -LiteralPath $target -Destination $backup
        Write-Host "      Ancien runtime conserve dans $backup" -ForegroundColor DarkYellow
    }
    Move-Item -LiteralPath $staging -Destination $target

    Write-Host "[4/4] Test du binaire..." -ForegroundColor Cyan
    $installedVersion = (& $gitExe --version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Git portable installe mais non executable."
    }
    Write-Host "[OK] $installedVersion" -ForegroundColor Green
    Write-Host "     $gitExe"
    exit 0
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
