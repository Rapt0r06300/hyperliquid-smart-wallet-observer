[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$GitExecutable = "",
    [switch]$DryRun,
    [switch]$WipOnly
)
# Backward-compatible entrypoint; one reconciliation engine, never two.
# No shard download, lock deletion, stash, reset or forced push.
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

try {
    $ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
    $driver = Join-Path $ProjectRoot "tools\alina_git_code_sync.py"
    if (-not (Test-Path -LiteralPath $driver -PathType Leaf)) {
        throw "tools\alina_git_code_sync.py est introuvable."
    }
    if (-not $GitExecutable) {
        $embedded = Join-Path $ProjectRoot "tools\git\cmd\git.exe"
        if (Test-Path -LiteralPath $embedded -PathType Leaf) {
            $GitExecutable = $embedded
        } else {
            $git = Get-Command git.exe -ErrorAction Stop
            $GitExecutable = $git.Source
        }
    }
    $python = Join-Path $ProjectRoot "tools\python\python.exe"
    $pyArgs = @()
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        $py = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($null -ne $py) {
            $python = $py.Source
            $pyArgs = @("-3")
        } else {
            $installed = Get-Command python.exe -ErrorAction Stop
            $python = $installed.Source
        }
    }
    if ($DryRun -and $WipOnly) {
        throw "DryRun et WipOnly sont incompatibles."
    }
    $command = @($driver, "--root", $ProjectRoot, "--git", $GitExecutable)
    if ($DryRun) { $command += "--dry-run" }
    if ($WipOnly) { $command += "--wip-only" }
    $env:GIT_LFS_SKIP_SMUDGE = "1"
    & $python @pyArgs @command
    exit $LASTEXITCODE
}
catch {
    Write-Host "[NO_GO] $($_.Exception.Message)" -ForegroundColor Red
    exit 2
}
