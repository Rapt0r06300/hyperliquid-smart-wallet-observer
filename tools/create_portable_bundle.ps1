param(
    [string]$ProjectRoot = "",
    [string]$OutputDir = "",
    [string]$Name = "",
    [switch]$RebuildRuntime
)

$ErrorActionPreference = "Stop"

function Resolve-FullPath([string]$Value) {
    if (Test-Path -LiteralPath $Value) {
        return (Resolve-Path -LiteralPath $Value).Path
    }
    return [System.IO.Path]::GetFullPath($Value)
}

function Test-IsWithin([string]$PathValue, [string]$ParentValue) {
    $path = [System.IO.Path]::GetFullPath($PathValue).TrimEnd("\", "/")
    $parent = [System.IO.Path]::GetFullPath($ParentValue).TrimEnd("\", "/")
    return $path.Equals($parent, [System.StringComparison]::OrdinalIgnoreCase) -or
        $path.StartsWith($parent + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)
}

function Test-SafeMember([string]$RelativePath) {
    $normalized = $RelativePath.Replace("\", "/").TrimStart("/")
    $lower = $normalized.ToLowerInvariant()
    $parts = $lower.Split("/", [System.StringSplitOptions]::RemoveEmptyEntries)
    if ($parts.Count -eq 0) { return $false }
    $excludedTop = @(
        ".git", ".hypothesis", ".mypy_cache", ".pytest_cache", ".refact",
        ".ruff_cache", ".venv", "build", "data", "dist", "env", "logs",
        "node_modules", "reports", "runtime", "venv"
    )
    if ($excludedTop -contains $parts[0]) { return $false }
    if (
        $parts[0] -eq "portable_runtime" -and
        $parts.Count -gt 1 -and
        (
            $parts[1].StartsWith("python_backup_") -or
            $parts[1].StartsWith("python_failed_")
        )
    ) { return $false }
    if ($parts -contains "__pycache__") { return $false }
    if ($lower -eq ".env" -or $lower.EndsWith("/.env")) { return $false }
    if (
        $parts.Count -eq 3 -and
        $parts[0] -eq "portable_runtime" -and
        $parts[1] -eq "python" -and
        $parts[2] -match "^python[0-9]+\.zip$"
    ) { return $true }
    $excludedSuffixes = @(
        ".7z", ".db", ".db-shm", ".db-wal", ".log", ".p12", ".pem",
        ".pfx", ".pyc", ".rar", ".sqlite", ".sqlite3", ".sqlite3-shm",
        ".sqlite3-wal", ".tmp", ".zip"
    )
    foreach ($suffix in $excludedSuffixes) {
        if ($lower.EndsWith($suffix)) { return $false }
    }
    return $true
}

function Copy-SafeTree([string]$Root, [string]$Staging, [string]$RelativeSource) {
    $source = Join-Path $Root $RelativeSource
    if (-not (Test-Path -LiteralPath $source)) { return }
    Get-ChildItem -LiteralPath $source -Recurse -Force -File -ErrorAction Stop | ForEach-Object {
        $full = $_.FullName
        $relative = $full.Substring($Root.TrimEnd("\", "/").Length).TrimStart("\", "/")
        if (Test-SafeMember $relative) {
            $target = Join-Path $Staging $relative
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
            Copy-Item -LiteralPath $full -Destination $target -Force
            $script:CopiedFiles++
            $script:CopiedBytes += $_.Length
        } else {
            $script:ExcludedFiles++
        }
    }
}

function Remove-GeneratedPythonCaches([string]$StagingRoot) {
    $resolvedStaging = [System.IO.Path]::GetFullPath($StagingRoot).TrimEnd("\", "/")
    $resolvedTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd("\", "/")
    if (-not $resolvedStaging.StartsWith(
        $resolvedTemp + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Refusing cache cleanup outside the Windows temporary directory: $resolvedStaging"
    }

    Get-ChildItem -LiteralPath $resolvedStaging -Recurse -Force -File -ErrorAction Stop |
        Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
        ForEach-Object {
            if (-not (Test-IsWithin $_.FullName $resolvedStaging)) {
                throw "Refusing cache cleanup outside staging: $($_.FullName)"
            }
            Remove-Item -LiteralPath $_.FullName -Force
        }

    Get-ChildItem -LiteralPath $resolvedStaging -Recurse -Force -Directory -ErrorAction Stop |
        Where-Object { $_.Name -eq "__pycache__" } |
        Sort-Object { $_.FullName.Length } -Descending |
        ForEach-Object {
            if (-not (Test-IsWithin $_.FullName $resolvedStaging)) {
                throw "Refusing cache cleanup outside staging: $($_.FullName)"
            }
            Remove-Item -LiteralPath $_.FullName -Recurse -Force
        }
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$root = Resolve-FullPath $ProjectRoot
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = [Environment]::GetFolderPath("Desktop")
}
$output = Resolve-FullPath $OutputDir
if (Test-IsWithin $output $root) {
    throw "Portable bundles must be created outside the project (Desktop by default)."
}
if ([string]::IsNullOrWhiteSpace($Name)) {
    $Name = "HyperSmart_Portable_Windows_x64_{0}.zip" -f (Get-Date -Format "yyyyMMdd_HHmmss")
}
if ($Name -match "[\\/]") {
    throw "Name must be a file name, not a path."
}
if (-not $Name.ToLowerInvariant().EndsWith(".zip")) {
    $Name += ".zip"
}
$zipPath = Join-Path $output $Name
if (Test-IsWithin $zipPath $root) {
    throw "Portable bundle path is inside the project."
}

$installer = Join-Path $root "tools\install_portable_runtime.ps1"
$portablePython = Join-Path $root "portable_runtime\python\python.exe"
$installArguments = @{
    ProjectRoot = $root
}
if ($RebuildRuntime) { $installArguments.Force = $true }
& $installer @installArguments
if ($LASTEXITCODE -ne 0) {
    throw "Portable Python runtime installation or manifest verification failed."
}

& $portablePython (Join-Path $root "tools\portable_runtime.py") --root $root check --require-embedded
if ($LASTEXITCODE -ne 0) {
    throw "Portable runtime verification failed."
}

$tempParent = Join-Path ([System.IO.Path]::GetTempPath()) ("hypersmart-bundle-" + [guid]::NewGuid().ToString("N"))
$staging = Join-Path $tempParent "HyperSmart"
$script:CopiedFiles = 0
$script:CopiedBytes = [int64]0
$script:ExcludedFiles = 0

$includeDirectories = @(
    ".github",
    "archive",
    "config",
    "docs",
    "hyper_smart_observer",
    "portable_runtime",
    "src",
    "tests",
    "tools"
)
$includeFiles = @(
    ".env.example",
    ".gitattributes",
    ".gitignore",
    "AGENTS.md",
    "CLAUDE.md",
    "LANCER_HYPERSMART.cmd",
    "MEGATEST.md",
    "OBJECTIF.md",
    "PORTFOLIO.md",
    "PORTFOLIO_EN.md",
    "pyproject.toml",
    "README.md",
    "RECAP-COMPLET.md",
    "requirements.txt",
    "requirements-portable.txt",
    "requirements-recherche.txt",
    "ruff.toml",
    "mypy.ini",
    "TASKLIST.md"
)

try {
    New-Item -ItemType Directory -Force -Path $staging | Out-Null
    foreach ($directory in $includeDirectories) {
        Copy-SafeTree -Root $root -Staging $staging -RelativeSource $directory
    }
    foreach ($relative in $includeFiles) {
        $source = Join-Path $root $relative
        if ((Test-Path -LiteralPath $source) -and (Test-SafeMember $relative)) {
            $target = Join-Path $staging $relative
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
            Copy-Item -LiteralPath $source -Destination $target -Force
            $item = Get-Item -LiteralPath $source
            $script:CopiedFiles++
            $script:CopiedBytes += $item.Length
        }
    }

    $commit = ""
    try { $commit = (& git -C $root rev-parse --short HEAD 2>$null).Trim() } catch { }
    $bundleManifest = [ordered]@{
        schema_version = 1
        created_at = (Get-Date).ToUniversalTime().ToString("o")
        target = "Windows 10/11 x64"
        entrypoint = "LANCER_HYPERSMART.cmd"
        project_commit = $commit
        copied_files = $script:CopiedFiles
        copied_bytes = $script:CopiedBytes
        excluded_files = $script:ExcludedFiles
        embedded_python = "portable_runtime/python/python.exe"
        active_runtime_included = $false
        starts_with_clean_runtime = $true
        exclusions = @(
            ".git", "runtime", "data", "logs", "SQLite/DB/WAL/SHM",
            "caches", "archives", ".env", "private key material"
        )
        safety = "read-only market data; local paper simulation; no real execution"
    }
    $bundleManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $staging "PORTABLE_BUNDLE_MANIFEST.json") -Encoding UTF8
    @"
HYPERSMART PORTABLE - WINDOWS 10/11 X64
=======================================

1. Extract the whole HyperSmart directory to a writable local disk.
2. Double-click LANCER_HYPERSMART.cmd.
3. Keep the portable_runtime directory beside the launcher.

The bundle starts with a clean runtime. Active databases and logs from the
source PC are intentionally excluded because they can be locked and exceed
160 GB. No .env, private key, secret or real-order capability is bundled.

Network access is still required for read-only Hyperliquid market data.
"@ | Set-Content -LiteralPath (Join-Path $staging "PORTABLE_README.txt") -Encoding UTF8

    $stagedPython = Join-Path $staging "portable_runtime\python\python.exe"
    & $stagedPython (Join-Path $staging "tools\portable_runtime.py") --root $staging check --require-embedded
    if ($LASTEXITCODE -ne 0) {
        throw "Staged portable runtime failed its relocatability test."
    }
    & $stagedPython -m hl_observer --help *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Staged HyperSmart CLI smoke test failed."
    }
    # The relocatability smoke tests import application modules and can create
    # bytecode in staging. Strip those generated caches before compression.
    Remove-GeneratedPythonCaches -StagingRoot $staging

    New-Item -ItemType Directory -Force -Path $output | Out-Null
    if (Test-Path -LiteralPath $zipPath) {
        throw "Output already exists: $zipPath"
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $staging,
        $zipPath,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $false
    )

    $archive = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        $names = @($archive.Entries | ForEach-Object { $_.FullName.Replace("\", "/") })
        $required = @(
            "LANCER_HYPERSMART.cmd",
            "portable_runtime/python/python.exe",
            "portable_runtime/portable_runtime_manifest.json",
            "src/hl_observer/__init__.py",
            "tools/start_hypersmart_simulation.ps1",
            "PORTABLE_BUNDLE_MANIFEST.json"
        )
        foreach ($requiredName in $required) {
            if ($names -notcontains $requiredName) {
                throw "Portable archive is missing required entry: $requiredName"
            }
        }
        $forbidden = @($names | Where-Object {
            $n = $_.ToLowerInvariant()
            $n.StartsWith(".git/") -or
            $n.StartsWith("runtime/") -or
            $n.StartsWith("data/") -or
            $n.StartsWith("logs/") -or
            $n.Contains("/__pycache__/") -or
            $n.EndsWith("/.env") -or
            $n -eq ".env" -or
            $n.EndsWith(".pyc") -or
            $n.EndsWith(".pyo") -or
            $n.EndsWith(".sqlite3") -or
            $n.EndsWith(".db") -or
            $n.EndsWith(".db-wal") -or
            $n.EndsWith(".db-shm") -or
            ($n.EndsWith(".zip") -and $n -notmatch "^portable_runtime/python/python[0-9]+\.zip$") -or
            $n.EndsWith(".7z") -or
            $n.EndsWith(".rar")
        })
        if ($forbidden.Count -gt 0) {
            throw "Forbidden files found in portable archive: " + (($forbidden | Select-Object -First 10) -join ", ")
        }
        $entryCount = $archive.Entries.Count
    } finally {
        $archive.Dispose()
    }

    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath).Hash
    Write-Host ""
    Write-Host "HYPERSMART PORTABLE BUNDLE READY"
    Write-Host "Archive : $zipPath"
    Write-Host "SHA256  : $hash"
    Write-Host "Entries : $entryCount"
    Write-Host "Source files copied : $script:CopiedFiles"
    Write-Host "Verified : embedded Python + imports + CLI + safe archive"
    Write-Host "Excluded : active runtime/data/logs, databases, caches, secrets, nested archives"
} finally {
    if (Test-Path -LiteralPath $tempParent) {
        Remove-Item -LiteralPath $tempParent -Recurse -Force -ErrorAction SilentlyContinue
    }
}
