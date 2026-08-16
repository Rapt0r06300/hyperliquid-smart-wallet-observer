[CmdletBinding()]
param(
    [string]$LabRoot = $env:ALINA_RESEARCH_HOME
)

$ErrorActionPreference = 'SilentlyContinue'
$failures = New-Object System.Collections.Generic.List[string]

function Row([string]$Name, [bool]$Ok, [string]$Detail) {
    $color = if ($Ok) { [ConsoleColor]::Green } else { [ConsoleColor]::Red }
    $mark = if ($Ok) { 'OK' } else { 'ECHEC' }
    Write-Host ($Name.PadRight(34) + ' : ') -NoNewline
    Write-Host ($mark.PadRight(6) + ' ' + $Detail) -ForegroundColor $color
    if (-not $Ok) { $failures.Add($Name) | Out-Null }
}

Write-Host ''
Write-Host '================================================================================' -ForegroundColor Cyan
Write-Host ' ALINA SMARTFLOW - DIAGNOSTIC DU RUNNER SELF-HOSTED' -ForegroundColor Cyan
Write-Host '================================================================================' -ForegroundColor Cyan

$machineLab = [Environment]::GetEnvironmentVariable('ALINA_RESEARCH_HOME', 'Machine')
if ([string]::IsNullOrWhiteSpace($LabRoot)) { $LabRoot = $machineLab }
$labOk = -not [string]::IsNullOrWhiteSpace($LabRoot)
Row 'Variable ALINA_RESEARCH_HOME' $labOk ([string]$LabRoot)

if ($labOk) {
    try { $LabRoot = [System.IO.Path]::GetFullPath($LabRoot) } catch { $labOk = $false }
}
Row 'Dossier laboratoire' ($labOk -and (Test-Path $LabRoot -PathType Container)) $LabRoot

$service = Get-Service -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like 'actions.runner.*' -or $_.DisplayName -like '*GitHub Actions Runner*' } |
    Select-Object -First 1
Row 'Service GitHub Actions Runner' ($null -ne $service) $(if ($service) { $service.Name } else { 'introuvable' })
Row 'Runner en cours d execution' ($service -and $service.Status -eq 'Running') $(if ($service) { [string]$service.Status } else { 'absent' })

if ($service) {
    $svcInfo = Get-CimInstance Win32_Service -Filter "Name='$($service.Name)'"
    Row 'Service configuré en automatique' ($svcInfo -and $svcInfo.StartMode -eq 'Auto') $(if ($svcInfo) { [string]$svcInfo.StartMode } else { 'inconnu' })
    if ($svcInfo) { Write-Host ('Chemin service'.PadRight(34) + ' : ' + $svcInfo.PathName) -ForegroundColor DarkGray }
}

$runnerPython = [Environment]::GetEnvironmentVariable('ALINA_PYTHON_EXE', 'Machine')
if ([string]::IsNullOrWhiteSpace($runnerPython)) { $runnerPython = $env:ALINA_PYTHON_EXE }
$pythonPathOk = -not [string]::IsNullOrWhiteSpace($runnerPython)
if ($pythonPathOk) {
    try { $runnerPython = [System.IO.Path]::GetFullPath($runnerPython) } catch { $pythonPathOk = $false }
}
if ($pythonPathOk) { $pythonPathOk = Test-Path $runnerPython -PathType Leaf }
Row 'Variable ALINA_PYTHON_EXE' $pythonPathOk $(if ($runnerPython) { [string]$runnerPython } else { 'absente' })

$pythonOk = $false
$pythonDetail = 'absent ou invalide'
if ($pythonPathOk) {
    $version = (& $runnerPython -c "import sys; print('.'.join(map(str, sys.version_info[:3]))); raise SystemExit(0 if sys.version_info >= (3,11) else 2)" 2>$null | Select-Object -Last 1)
    $pythonOk = $LASTEXITCODE -eq 0
    if ($pythonOk) { $pythonDetail = "Python $version | $runnerPython" }
}
Row 'Python persistant 3.11+' $pythonOk $pythonDetail

$git = Get-Command git -ErrorAction SilentlyContinue
Row 'Git for Windows' ($null -ne $git) $(if ($git) { $git.Source } else { 'git.exe absent' })

if ($labOk -and (Test-Path $LabRoot -PathType Container)) {
    foreach ($relative in @('datasets','jobs\requests','results\github','status','job_logs','checkpoints','tools','runtime','runtime\python')) {
        Row ("Sous-dossier $relative") (Test-Path (Join-Path $LabRoot $relative) -PathType Container) (Join-Path $LabRoot $relative)
    }
    $expectedPython = Join-Path $LabRoot 'runtime\python\Scripts\python.exe'
    Row 'Python dans ALINA_RESEARCH_HOME' ($pythonPathOk -and ([System.IO.Path]::GetFullPath($runnerPython) -eq [System.IO.Path]::GetFullPath($expectedPython))) $expectedPython

    $root = [System.IO.Path]::GetPathRoot($LabRoot)
    $drive = Get-PSDrive -Name $root.Substring(0,1) -ErrorAction SilentlyContinue
    if ($drive) {
        $free = [Math]::Round($drive.Free / 1GB, 2)
        Row 'Réserve disque >= 25 Gio' ($free -ge 25) ("$free Gio libres")
    }
    Row 'Cockpit copié' (Test-Path (Join-Path $LabRoot 'tools\ALINA_RESEARCH_COCKPIT.ps1') -PathType Leaf) (Join-Path $LabRoot 'tools\ALINA_RESEARCH_COCKPIT.ps1')
    Row 'Lanceur cockpit local' (Test-Path (Join-Path $LabRoot 'LANCER_COCKPIT_ALINA.cmd') -PathType Leaf) (Join-Path $LabRoot 'LANCER_COCKPIT_ALINA.cmd')
}

Write-Host ''
Write-Host 'Sécurité fixe : mainnet=0 | testnet execution=0 | paper/read-only pour les jobs autonomes.' -ForegroundColor Green
if ($failures.Count -eq 0) {
    Write-Host 'DIAGNOSTIC FINAL : RUNNER PRÊT' -ForegroundColor Green
    exit 0
}
Write-Host ('DIAGNOSTIC FINAL : ' + $failures.Count + ' point(s) à corriger') -ForegroundColor Red
$failures | ForEach-Object { Write-Host (' - ' + $_) -ForegroundColor Red }
exit 2
