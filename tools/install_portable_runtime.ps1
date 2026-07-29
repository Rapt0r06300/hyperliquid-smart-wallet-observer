param(
    [string]$ProjectRoot = "",
    [string]$PythonVersion = "3.14.2",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$env:PYTHONNOUSERSITE = "1"
$env:PIP_USER = "0"

function Resolve-FullPath([string]$Value) {
    if (Test-Path -LiteralPath $Value) {
        return (Resolve-Path -LiteralPath $Value).Path
    }
    return [System.IO.Path]::GetFullPath($Value)
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$Description
    )
    Write-Host "[portable] $Description"
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$root = Resolve-FullPath $ProjectRoot
$requirements = Join-Path $root "requirements-portable.txt"
if (-not (Test-Path -LiteralPath $requirements)) {
    throw "requirements-portable.txt is missing: $requirements"
}
$requirementsHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $requirements).Hash
if (-not $IsWindows -and $PSVersionTable.PSVersion.Major -ge 6) {
    throw "This runtime builder currently targets Windows 10/11 x64 only."
}
$arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
if ($arch -notin @("X64", "x64", "AMD64")) {
    throw "Unsupported architecture '$arch'. The current portable bundle targets Windows x64."
}

$runtimeRoot = Join-Path $root "portable_runtime"
$destination = Join-Path $runtimeRoot "python"
$manifestPath = Join-Path $runtimeRoot "portable_runtime_manifest.json"
$pythonPath = Join-Path $destination "python.exe"

if ((Test-Path -LiteralPath $pythonPath) -and -not $Force) {
    Write-Host "[portable] Existing embedded runtime detected; verifying it."
    & $pythonPath (Join-Path $root "tools\portable_runtime.py") --root $root check --require-embedded
    $manifestMatches = $false
    if (($LASTEXITCODE -eq 0) -and (Test-Path -LiteralPath $manifestPath)) {
        try {
            $existingManifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
            $manifestMatches = (
                [string]$existingManifest.python_version -eq $PythonVersion -and
                [string]$existingManifest.requirements_sha256 -eq $requirementsHash -and
                [bool]$existingManifest.isolated_from_user_site
            )
        } catch {
            $manifestMatches = $false
        }
    }
    if ($manifestMatches) {
        Write-Host "[portable] Runtime already ready: $pythonPath"
        exit 0
    }
    throw "Existing portable runtime is incomplete or outdated. Re-run with -Force to rebuild it safely."
}

$artifactName = "python-$PythonVersion-embed-amd64.zip"
$downloadUrl = "https://www.python.org/ftp/python/$PythonVersion/$artifactName"
$knownHashes = @{
    "3.14.2" = "F05E28D161C6B15AF64A7CB7F08B4A22B3A6B03EEE71BAEE24EA557B3BDD5798"
}
if (-not $knownHashes.ContainsKey($PythonVersion)) {
    throw "No audited SHA256 is configured for Python $PythonVersion."
}
$expectedSha256 = $knownHashes[$PythonVersion]

$tempParent = Join-Path ([System.IO.Path]::GetTempPath()) ("hypersmart-portable-" + [guid]::NewGuid().ToString("N"))
$downloadPath = Join-Path $tempParent $artifactName
$buildPython = Join-Path $tempParent "python"
$getPipPath = Join-Path $tempParent "get-pip.py"
$backup = $null

try {
    New-Item -ItemType Directory -Force -Path $buildPython | Out-Null
    Write-Host "[portable] Downloading official CPython embedded runtime:"
    Write-Host "[portable] $downloadUrl"
    Invoke-WebRequest -Uri $downloadUrl -OutFile $downloadPath -UseBasicParsing
    $actualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $downloadPath).Hash.ToUpperInvariant()
    if ($actualSha256 -ne $expectedSha256) {
        throw "CPython SHA256 mismatch. Expected $expectedSha256, got $actualSha256."
    }
    Expand-Archive -LiteralPath $downloadPath -DestinationPath $buildPython -Force

    $pthFile = Get-ChildItem -LiteralPath $buildPython -Filter "python*._pth" -File | Select-Object -First 1
    if ($null -eq $pthFile) {
        throw "Embedded Python path configuration file was not found."
    }
    @(
        "python314.zip"
        "."
        "Lib\site-packages"
        "..\..\src"
        "..\.."
        "..\..\tools"
    ) | Set-Content -LiteralPath $pthFile.FullName -Encoding ASCII

    $buildPythonExe = Join-Path $buildPython "python.exe"
    New-Item -ItemType Directory -Force -Path (Join-Path $buildPython "Lib\site-packages") | Out-Null
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPipPath -UseBasicParsing
    Invoke-Checked -FilePath $buildPythonExe -Arguments @(
        $getPipPath,
        "--no-warn-script-location",
        "--no-user"
    ) -Description "Installing pip into the embedded runtime"
    Invoke-Checked -FilePath $buildPythonExe -Arguments @(
        "-m", "pip", "--isolated", "install",
        "--disable-pip-version-check",
        "--no-warn-script-location",
        "--upgrade",
        "--ignore-installed",
        "--no-user",
        "--requirement", $requirements
    ) -Description "Installing HyperSmart runtime and research dependencies"

    Invoke-Checked -FilePath $buildPythonExe -Arguments @(
        "-c",
        "import fastapi,httpx,pydantic,sqlalchemy,typer,uvicorn,websocket,websockets,yaml,psutil,rich,numpy; print('dependency-smoke: OK')"
    ) -Description "Checking embedded dependencies"

    New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
    if (Test-Path -LiteralPath $destination) {
        $backup = Join-Path $runtimeRoot ("python_backup_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
        Move-Item -LiteralPath $destination -Destination $backup
        Write-Host "[portable] Previous runtime preserved at: $backup"
    }
    Move-Item -LiteralPath $buildPython -Destination $destination

    $commit = ""
    try {
        $commit = (& git -C $root rev-parse --short HEAD 2>$null).Trim()
    } catch { }
    $manifest = [ordered]@{
        schema_version = 1
        created_at = (Get-Date).ToUniversalTime().ToString("o")
        target = "windows-x64"
        python_version = $PythonVersion
        python_url = $downloadUrl
        python_sha256 = $expectedSha256
        requirements_file = "requirements-portable.txt"
        requirements_sha256 = $requirementsHash
        project_commit = $commit
        relocatable_paths = @("..\..\src", "..\..", "..\..\tools", "Lib\site-packages")
        runtime_data_included = $false
        isolated_from_user_site = $true
    }
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    @"
HyperSmart embedded Python runtime
==================================
Target: Windows 10/11 x64
Python: $PythonVersion
Source: $downloadUrl
SHA256: $expectedSha256

This directory is relocatable with the HyperSmart project folder.
Do not move this directory away from the project root.
"@ | Set-Content -LiteralPath (Join-Path $runtimeRoot "README.txt") -Encoding UTF8

    Invoke-Checked -FilePath $pythonPath -Arguments @(
        (Join-Path $root "tools\portable_runtime.py"),
        "--root", $root,
        "check", "--require-embedded"
    ) -Description "Running the final relocatability smoke test"
    Write-Host ""
    Write-Host "[portable] READY: $pythonPath"
    Write-Host "[portable] Copying the project folder now carries its own Python runtime."
} catch {
    if ((Test-Path -LiteralPath $destination) -and $backup) {
        $failed = Join-Path $runtimeRoot ("python_failed_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
        Move-Item -LiteralPath $destination -Destination $failed -ErrorAction SilentlyContinue
        Move-Item -LiteralPath $backup -Destination $destination -ErrorAction SilentlyContinue
    }
    throw
} finally {
    if (Test-Path -LiteralPath $tempParent) {
        Remove-Item -LiteralPath $tempParent -Recurse -Force -ErrorAction SilentlyContinue
    }
}
