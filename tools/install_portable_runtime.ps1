param(
    [string]$ProjectRoot = "",
    [string]$PythonVersion = "3.14.2",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$env:PYTHONNOUSERSITE = "1"
$env:PIP_USER = "0"
$env:PIP_NO_INDEX = "1"
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"

function Resolve-FullPath([string]$Value) {
    if (Test-Path -LiteralPath $Value) { return (Resolve-Path -LiteralPath $Value).Path }
    return [System.IO.Path]::GetFullPath($Value)
}

function Invoke-Checked {
    param([string]$FilePath, [string[]]$Arguments, [string]$Description)
    Write-Host "[portable] $Description"
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Description failed with exit code $LASTEXITCODE" }
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent $PSScriptRoot }
$root = Resolve-FullPath $ProjectRoot
$requirements = Join-Path $root "requirements-portable.txt"
$wheelhouse = Join-Path $root "tools\wheelhouse"
$wheelLock = Join-Path $wheelhouse "WHEELHOUSE_LOCK.json"
$runtimeRoot = Join-Path $root "tools"
$destination = Join-Path $runtimeRoot "python"
$manifestPath = Join-Path $destination "portable_runtime_manifest.json"
$pythonPath = Join-Path $destination "python.exe"
$legacyPython = Join-Path $root "portable_runtime\python\python.exe"
$runtimeTool = Join-Path $root "tools\portable_runtime.py"
$wheelTool = Join-Path $root "tools\wheelhouse_lock.py"

foreach ($required in @($requirements, $wheelLock, $runtimeTool, $wheelTool)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required portable input is missing: $required" }
}
if (-not (Test-Path -LiteralPath $wheelhouse -PathType Container)) { throw "Wheelhouse is missing: $wheelhouse" }
if ($PSVersionTable.PSVersion.Major -ge 6 -and -not $IsWindows) { throw "Windows 10/11 x64 is required." }
$arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
if ($arch -notin @("X64", "x64", "AMD64")) { throw "Unsupported architecture '$arch'; Windows x64 is required." }

# One-time, non-destructive migration. The legacy tree remains untouched.
if (-not (Test-Path -LiteralPath $pythonPath) -and (Test-Path -LiteralPath $legacyPython)) {
    Invoke-Checked -FilePath $legacyPython -Arguments @($runtimeTool, "--root", $root, "migrate") `
        -Description "Migrating portable_runtime/python to tools/python"
}

$requirementsHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $requirements).Hash.ToLowerInvariant()
$wheelLockHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $wheelLock).Hash.ToLowerInvariant()
if ((Test-Path -LiteralPath $pythonPath) -and -not $Force) {
    $manifestMatches = $false
    if (Test-Path -LiteralPath $manifestPath) {
        try {
            $existing = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
            $manifestMatches = (
                [string]$existing.python_version -eq $PythonVersion -and
                [string]$existing.requirements_sha256 -eq $requirementsHash -and
                [string]$existing.wheelhouse_lock_sha256 -eq $wheelLockHash -and
                [bool]$existing.isolated_from_user_site
            )
        } catch { $manifestMatches = $false }
    }
    if ($manifestMatches) {
        Invoke-Checked -FilePath $pythonPath -Arguments @($runtimeTool, "--root", $root, "check", "--require-embedded") `
            -Description "Verifying existing tools/python runtime"
        Write-Host "[portable] Runtime already exact: $pythonPath"
        exit 0
    }
    Write-Host "[portable] Existing or migrated runtime is not exact; rebuilding from audited inputs."
}

$artifactName = "python-$PythonVersion-embed-amd64.zip"
$downloadUrl = "https://www.python.org/ftp/python/$PythonVersion/$artifactName"
$knownHashes = @{ "3.14.2" = "F05E28D161C6B15AF64A7CB7F08B4A22B3A6B03EEE71BAEE24EA557B3BDD5798" }
if (-not $knownHashes.ContainsKey($PythonVersion)) { throw "No audited SHA256 is configured for Python $PythonVersion." }
$expectedSha256 = $knownHashes[$PythonVersion]

$tempParent = Join-Path ([System.IO.Path]::GetTempPath()) ("hypersmart-portable-" + [guid]::NewGuid().ToString("N"))
$downloadPath = Join-Path $tempParent $artifactName
$buildPython = Join-Path $tempParent "python"
$backup = $null
try {
    New-Item -ItemType Directory -Force -Path $buildPython | Out-Null
    Write-Host "[portable] Downloading audited CPython: $downloadUrl"
    Invoke-WebRequest -Uri $downloadUrl -OutFile $downloadPath -UseBasicParsing
    $actualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $downloadPath).Hash.ToUpperInvariant()
    if ($actualSha256 -ne $expectedSha256) {
        throw "CPython SHA256 mismatch. Expected $expectedSha256, got $actualSha256."
    }
    Expand-Archive -LiteralPath $downloadPath -DestinationPath $buildPython -Force
    $pthFile = Get-ChildItem -LiteralPath $buildPython -Filter "python*._pth" -File | Select-Object -First 1
    if ($null -eq $pthFile) { throw "Embedded Python path file is missing." }
    @("python314.zip", ".", "Lib\site-packages", "..\..\src", "..\..", "..\..\tools") |
        Set-Content -LiteralPath $pthFile.FullName -Encoding ASCII
    $buildPythonExe = Join-Path $buildPython "python.exe"
    $sitePackages = Join-Path $buildPython "Lib\site-packages"
    New-Item -ItemType Directory -Force -Path $sitePackages | Out-Null

    # The verifier is pure stdlib and runs before any third-party code is loaded.
    Invoke-Checked -FilePath $buildPythonExe -Arguments @(
        $wheelTool, "--wheelhouse", $wheelhouse, "--verifier", $wheelLock,
        "--requirements", $requirements
    ) -Description "Verifying exact Windows x64 wheelhouse"

    $pipWheel = Get-ChildItem -LiteralPath $wheelhouse -Filter "pip-*-py3-none-any.whl" -File
    if (@($pipWheel).Count -ne 1) { throw "Exactly one locked pip wheel is required in the wheelhouse." }
    $pipBootstrap = "import sys; wheel=sys.argv.pop(1); sys.path.insert(0,wheel); from pip._internal.cli.main import main; raise SystemExit(main())"
    Invoke-Checked -FilePath $buildPythonExe -Arguments @(
        "-c", $pipBootstrap, $pipWheel.FullName, "install",
        "--no-index", "--find-links", $wheelhouse, "--require-hashes",
        "--only-binary=:all:", "--no-user", "--ignore-installed", "--no-compile",
        "--target", $sitePackages, "--requirement", $requirements
    ) -Description "Installing all dependencies from the verified offline wheelhouse"

    Invoke-Checked -FilePath $buildPythonExe -Arguments @(
        "-c", "import fastapi,httpx,pydantic,pyarrow,sqlalchemy,typer,uvicorn,websocket,websockets,yaml,psutil,rich,numpy; print('dependency-smoke: OK')"
    ) -Description "Checking embedded dependencies"

    New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
    if (Test-Path -LiteralPath $destination) {
        $backupRoot = Join-Path $root "portable_runtime"
        New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
        $backup = Join-Path $backupRoot ("python_backup_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
        Move-Item -LiteralPath $destination -Destination $backup
        Write-Host "[portable] Previous tools/python preserved at: $backup"
    }
    Move-Item -LiteralPath $buildPython -Destination $destination

    $commit = "UNKNOWN"
    $sourceEpoch = 315532800
    $embeddedGit = Join-Path $root "tools\git\cmd\git.exe"
    try {
        if (Test-Path -LiteralPath $embeddedGit -PathType Leaf) {
            $commit = (& $embeddedGit -C $root rev-parse HEAD 2>$null).Trim()
            $sourceEpoch = [int64](& $embeddedGit -C $root show -s --format=%ct HEAD 2>$null).Trim()
        }
    } catch { }
    $createdAt = [DateTimeOffset]::FromUnixTimeSeconds($sourceEpoch).UtcDateTime.ToString("o")
    $manifest = [ordered]@{
        schema_version = 2
        created_at_source_date_epoch = $createdAt
        source_date_epoch = $sourceEpoch
        target = "cp314-win_amd64"
        python_version = $PythonVersion
        python_url = $downloadUrl
        python_sha256 = $expectedSha256.ToLowerInvariant()
        requirements_file = "requirements-portable.txt"
        requirements_sha256 = $requirementsHash
        wheelhouse_lock_file = "tools/wheelhouse/WHEELHOUSE_LOCK.json"
        wheelhouse_lock_sha256 = $wheelLockHash
        project_commit = $commit
        runtime_path = "tools/python/python.exe"
        runtime_data_included = $false
        isolated_from_user_site = $true
        installation_mode = "offline-require-hashes-only-binary"
    }
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    Invoke-Checked -FilePath $pythonPath -Arguments @($runtimeTool, "--root", $root, "check", "--require-embedded") `
        -Description "Running final relocatability smoke test"
    Write-Host "[portable] READY: $pythonPath"
} catch {
    if ((Test-Path -LiteralPath $destination) -and $backup) {
        $failed = Join-Path (Split-Path -Parent $backup) ("python_failed_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
        Move-Item -LiteralPath $destination -Destination $failed -ErrorAction SilentlyContinue
        Move-Item -LiteralPath $backup -Destination $destination -ErrorAction SilentlyContinue
    }
    throw
} finally {
    if (Test-Path -LiteralPath $tempParent) { Remove-Item -LiteralPath $tempParent -Recurse -Force -ErrorAction SilentlyContinue }
}
