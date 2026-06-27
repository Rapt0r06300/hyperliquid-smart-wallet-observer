param(
    [string]$ProjectRoot = ".",
    [string]$OutputDir = "",
    [string]$Name = ""
)

$ErrorActionPreference = "Stop"

function Resolve-FullPath([string]$PathValue) {
    if (Test-Path -LiteralPath $PathValue) {
        return (Resolve-Path -LiteralPath $PathValue).Path
    }
    return [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $PathValue))
}

function Test-ArchiveSafeRelativePath([string]$RelativePath) {
    $normalized = $RelativePath.Replace("\", "/")
    $lower = $normalized.ToLowerInvariant()
    $parts = $lower.Split("/", [System.StringSplitOptions]::RemoveEmptyEntries)
    $excludedParts = @(
        ".git", ".venv", "venv", "logs", "data", "__pycache__",
        ".pytest_cache", ".mypy_cache", ".refact", "dist", "build"
    )
    foreach ($part in $parts) {
        if ($excludedParts -contains $part) {
            return $false
        }
    }
    if ($lower -eq ".env") {
        return $false
    }
    $excludedSuffixes = @(
        ".sqlite3", ".sqlite3-wal", ".sqlite3-shm",
        ".db", ".db-wal", ".db-shm",
        ".log", ".zip", ".7z", ".rar", ".pyc", ".tmp"
    )
    foreach ($suffix in $excludedSuffixes) {
        if ($lower.EndsWith($suffix)) {
            return $false
        }
    }
    return $true
}

function Get-ArchiveRelativePath([string]$Root, [string]$PathValue) {
    $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd("\", "/")
    $pathFull = [System.IO.Path]::GetFullPath($PathValue)
    $prefix = $rootFull + [System.IO.Path]::DirectorySeparatorChar
    if ($pathFull.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $pathFull.Substring($prefix.Length).Replace("\", "/")
    }
    return (Split-Path -Leaf $pathFull)
}

function Copy-IncludePath(
    [string]$Root,
    [string]$Staging,
    [string]$Include
) {
    $source = Join-Path $Root $Include
    if (-not (Test-Path -LiteralPath $source)) {
        return @{ Copied = 0; Excluded = 0 }
    }

    $copied = 0
    $excluded = 0
    $sourceItem = Get-Item -LiteralPath $source -Force
    if (-not $sourceItem.PSIsContainer) {
        $relative = $Include.Replace("\", "/")
        if (Test-ArchiveSafeRelativePath $relative) {
            $target = Join-Path $Staging $relative
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
            Copy-Item -LiteralPath $sourceItem.FullName -Destination $target -Force
            $copied++
        } else {
            $excluded++
        }
        return @{ Copied = $copied; Excluded = $excluded }
    }

    Get-ChildItem -LiteralPath $sourceItem.FullName -Recurse -Force -File | ForEach-Object {
        $relative = Get-ArchiveRelativePath -Root $Root -PathValue $_.FullName
        if (Test-ArchiveSafeRelativePath $relative) {
            $target = Join-Path $Staging $relative
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $target -Force
            $script:CopiedCount++
        } else {
            $script:ExcludedCount++
        }
    }
    return @{ Copied = 0; Excluded = 0 }
}

function Test-ZipIsClean([string]$ZipPath) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        $bad = New-Object System.Collections.Generic.List[string]
        foreach ($entry in $archive.Entries) {
            $name = $entry.FullName.Replace("\", "/")
            $lower = $name.ToLowerInvariant()
            if (
                $lower.StartsWith("logs/") -or
                $lower.StartsWith("data/") -or
                $lower.StartsWith(".git/") -or
                $lower.StartsWith(".venv/") -or
                $lower.StartsWith("venv/") -or
                $lower.Contains("/__pycache__/") -or
                $lower.StartsWith("__pycache__/") -or
                $lower.Contains("/.pytest_cache/") -or
                $lower.StartsWith(".pytest_cache/") -or
                $lower.Contains("/.refact/") -or
                $lower.StartsWith(".refact/") -or
                $lower.Contains("/.mypy_cache/") -or
                $lower.StartsWith(".mypy_cache/") -or
                $lower.EndsWith(".sqlite3") -or
                $lower.EndsWith(".sqlite3-wal") -or
                $lower.EndsWith(".sqlite3-shm") -or
                $lower.EndsWith(".db") -or
                $lower.EndsWith(".db-wal") -or
                $lower.EndsWith(".db-shm") -or
                $lower.EndsWith(".log") -or
                $lower.EndsWith(".zip") -or
                $lower.EndsWith(".7z") -or
                $lower.EndsWith(".rar") -or
                $lower.EndsWith(".pyc") -or
                $lower.EndsWith(".env") -or
                $lower -eq ".env"
            ) {
                $bad.Add($name)
            }
        }
        if ($bad.Count -gt 0) {
            $sample = ($bad | Select-Object -First 10) -join ", "
            throw "Archive contains forbidden runtime files: $sample"
        }
        return $archive.Entries.Count
    } finally {
        $archive.Dispose()
    }
}

$root = Resolve-FullPath $ProjectRoot
$desktop = [Environment]::GetFolderPath("Desktop")
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = $desktop
}
if ([string]::IsNullOrWhiteSpace($Name)) {
    $Name = "Projet_invest_clean_{0}.zip" -f (Get-Date -Format "yyyyMMdd_HHmmss")
}
$output = Resolve-FullPath $OutputDir
$rootFull = [System.IO.Path]::GetFullPath($root).TrimEnd("\", "/")
$outputFull = [System.IO.Path]::GetFullPath($output).TrimEnd("\", "/")
if ($outputFull.Equals($rootFull, [System.StringComparison]::OrdinalIgnoreCase) -or $outputFull.StartsWith($rootFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refused: OutputDir is inside the project. Clean archives must be created on the Desktop or outside the project."
}
if ($Name -match '[\\/]') {
    throw "Refused: Name must be a file name, not a path."
}
New-Item -ItemType Directory -Force -Path $output | Out-Null
$zipPath = Join-Path $output $Name
$zipFull = [System.IO.Path]::GetFullPath($zipPath)
if ($zipFull.StartsWith($rootFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refused: archive path is inside the project."
}

$stagingParent = Join-Path ([System.IO.Path]::GetTempPath()) ("projet-invest-archive-" + [System.Guid]::NewGuid().ToString("N"))
$staging = Join-Path $stagingParent "staging"
New-Item -ItemType Directory -Force -Path $staging | Out-Null

$includes = @(
    "src",
    "hyper_smart_observer",
    "config",
    "docs",
    "tests",
    "tools",
    "README.md",
    "AGENTS.md",
    "requirements.txt",
    "pyproject.toml",
    ".env.example",
    ".gitignore",
    "CREER_ARCHIVE_PROPRE.cmd",
    "LANCER_HYPERSMART.cmd"
)

$script:CopiedCount = 0
$script:ExcludedCount = 0

try {
    Write-Host "Creating clean archive from staging only"
    Write-Host "Project root: $root"
    Write-Host "Staging: $staging"
    Write-Host "Output: $zipPath"

    foreach ($include in $includes) {
        $result = Copy-IncludePath -Root $root -Staging $staging -Include $include
        $script:CopiedCount += [int]$result.Copied
        $script:ExcludedCount += [int]$result.Excluded
    }

    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zipPath -Force
    $entries = Test-ZipIsClean $zipPath

    Write-Host ""
    Write-Host "Clean archive created successfully"
    Write-Host "Archive: $zipPath"
    Write-Host "Desktop output policy: archives are created outside the project"
    Write-Host "Files copied: $script:CopiedCount"
    Write-Host "Runtime files excluded/skipped: $script:ExcludedCount"
    Write-Host "Zip entries: $entries"
    Write-Host "Verified: no logs/, data/, sqlite/db/WAL/SHM/log/archive/.env files in ZIP"
    Write-Host "Safe with locked runtime DBs: logs/ and data/ were never copied"
    New-Item -ItemType Directory -Force -Path (Join-Path $root "docs\release") | Out-Null
    $auditPath = Join-Path $root "docs\release\HYPERSMART_ARCHIVE_AUDIT.md"
    $auditLines = @(
        "# HyperSmart Archive Audit",
        "",
        "- status: OK",
        "- archive_path: $zipPath",
        "- files_copied: $script:CopiedCount",
        "- zip_entries: $entries",
        "- output_policy: Desktop/outside project only",
        "- excluded: logs/, data/, .git/, SQLite, WAL/SHM, .env, caches, nested archives"
    )
    Set-Content -Path $auditPath -Value $auditLines -Encoding UTF8
    Write-Host "Archive audit: $auditPath"
} finally {
    if (Test-Path -LiteralPath $stagingParent) {
        Remove-Item -LiteralPath $stagingParent -Recurse -Force
    }
}
