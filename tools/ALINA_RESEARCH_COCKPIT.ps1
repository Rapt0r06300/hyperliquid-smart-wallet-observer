[CmdletBinding()]
param(
    [string]$LabRoot = $env:ALINA_RESEARCH_HOME,
    [ValidateRange(1, 60)][int]$RefreshSeconds = 1,
    [ValidateRange(0, 30)][int]$LogLines = 8
)

$ErrorActionPreference = 'SilentlyContinue'

function Write-Line([string]$Label, [object]$Value, [ConsoleColor]$Color = [ConsoleColor]::White) {
    if ($null -eq $Value) { $Value = '-' }
    Write-Host ($Label.PadRight(30) + ': ') -NoNewline -ForegroundColor DarkGray
    Write-Host $Value -ForegroundColor $Color
}
function Get-Value([object]$Object, [string]$Property, [object]$Default = '-') {
    if ($null -eq $Object) { return $Default }
    try {
        $prop = $Object.PSObject.Properties[$Property]
        if ($null -eq $prop -or $null -eq $prop.Value) { return $Default }
        $text = [string]$prop.Value
        if ([string]::IsNullOrWhiteSpace($text)) { return $Default }
        return $prop.Value
    } catch { return $Default }
}
function Read-JsonSafe([string]$Path) {
    if (-not (Test-Path $Path -PathType Leaf)) { return $null }
    try { return Get-Content $Path -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $null }
}
function Format-Duration([object]$Seconds) {
    if ($null -eq $Seconds -or [string]$Seconds -eq '-') { return '--:--:--' }
    try {
        $span = [TimeSpan]::FromSeconds([Math]::Max(0, [double]$Seconds))
        if ($span.TotalDays -ge 1) { return ('{0}j {1:00}:{2:00}:{3:00}' -f [Math]::Floor($span.TotalDays), $span.Hours, $span.Minutes, $span.Seconds) }
        return ('{0:00}:{1:00}:{2:00}' -f [Math]::Floor($span.TotalHours), $span.Minutes, $span.Seconds)
    } catch { return '--:--:--' }
}
function Get-RunnerService {
    return Get-Service -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'actions.runner.*' -or $_.DisplayName -like '*GitHub Actions Runner*' } | Select-Object -First 1
}
function Get-FreeGiB([string]$Path) {
    try {
        $root = [System.IO.Path]::GetPathRoot([System.IO.Path]::GetFullPath($Path))
        $drive = Get-PSDrive -Name $root.Substring(0,1) -ErrorAction Stop
        return [Math]::Round($drive.Free / 1GB, 2)
    } catch { return $null }
}
function Get-HeartbeatAge([object]$HeartbeatUnix) {
    if ($null -eq $HeartbeatUnix -or [string]$HeartbeatUnix -eq '-') { return $null }
    try { return [Math]::Max(0, ([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000.0) - [double]$HeartbeatUnix) } catch { return $null }
}
function Get-ProcessRuntime([object]$PidValue) {
    $result = [ordered]@{ cpu_seconds=$null; ram_mib=$null; child_processes=$null }
    try {
        $pidNumber = [int]$PidValue
        $p = Get-Process -Id $pidNumber -ErrorAction Stop
        $result.cpu_seconds = [Math]::Round([double]$p.CPU, 2)
        $result.ram_mib = [Math]::Round([double]$p.WorkingSet64 / 1MB, 1)
        $children = @(Get-CimInstance Win32_Process -Filter ("ParentProcessId=" + $pidNumber) -ErrorAction SilentlyContinue)
        $result.child_processes = $children.Count
    } catch {}
    return [pscustomobject]$result
}
function Get-StateColor([string]$State) {
    switch ($State) {
        'SUCCESS' { return [ConsoleColor]::Green }
        'SUCCESS_CACHED' { return [ConsoleColor]::Green }
        'RUNNING' { return [ConsoleColor]::Green }
        'WAITING' { return [ConsoleColor]::Cyan }
        'STARTING' { return [ConsoleColor]::Yellow }
        'STEP_DONE' { return [ConsoleColor]::Green }
        'FINALIZING' { return [ConsoleColor]::Yellow }
        'TIMEBOX_REACHED' { return [ConsoleColor]::Yellow }
        'TIMEOUT' { return [ConsoleColor]::Yellow }
        'NO_GO' { return [ConsoleColor]::Red }
        'ERROR' { return [ConsoleColor]::Red }
        'STEP_ERROR' { return [ConsoleColor]::Red }
        default { return [ConsoleColor]::White }
    }
}
function Write-Optional([object]$Object, [string]$Property, [string]$Label, [string]$Suffix = '') {
    $value = Get-Value $Object $Property $null
    if ($null -ne $value) { Write-Line $Label (([string]$value) + $Suffix) White }
}
function Write-ProgressBar([object]$Percent) {
    if ($null -eq $Percent -or [string]$Percent -eq '-') { Write-Line 'Progression précise' 'Non fournie; heartbeat utilisé.' DarkGray; return }
    try {
        $p = [Math]::Max(0,[Math]::Min(100,[double]$Percent)); $filled=[int][Math]::Round($p/5)
        Write-Line 'Progression' (('[{0}] {1:N1} %' -f (('#'*$filled)+('-'*(20-$filled))), $p)) Green
    } catch { Write-Line 'Progression' 'Indisponible' DarkGray }
}

if ([string]::IsNullOrWhiteSpace($LabRoot)) {
    Write-Host 'ALINA RESEARCH COCKPIT' -ForegroundColor Cyan
    Write-Host 'Le laboratoire n est pas encore installé sur ce PC.' -ForegroundColor Yellow
    exit 2
}
try { $LabRoot = [System.IO.Path]::GetFullPath($LabRoot) } catch { Write-Host "Chemin invalide: $LabRoot" -ForegroundColor Red; exit 2 }
$statusPath = Join-Path $LabRoot 'status\CURRENT_STATUS.json'
$syncPath = Join-Path $LabRoot 'status\GITHUB_SYNC_STATUS.json'
$oldCursor = $true
try { $oldCursor=[Console]::CursorVisible; [Console]::CursorVisible=$false } catch {}

try {
    while ($true) {
        $status = Read-JsonSafe $statusPath
        $sync = Read-JsonSafe $syncPath
        Clear-Host
        Write-Host '==============================================================================' -ForegroundColor Cyan
        Write-Host ' ALINA SMARTFLOW - COCKPIT DU LABORATOIRE AUTONOME' -ForegroundColor Cyan
        Write-Host '==============================================================================' -ForegroundColor Cyan
        Write-Host (" Mise à jour toutes les {0}s | {1}" -f $RefreshSeconds, (Get-Date).ToString('dd/MM/yyyy HH:mm:ss'))
        Write-Host ' Ctrl+C ferme uniquement cet écran.' -ForegroundColor DarkGray
        Write-Host ''

        $service = Get-RunnerService
        if ($service -and $service.Status -eq 'Running') { Write-Line 'Service runner local' 'ACTIF' Green }
        elseif ($service) { Write-Line 'Service runner local' ("SERVICE " + $service.Status) Yellow }
        else { Write-Line 'Service runner local' 'NON DÉTECTÉ' DarkGray }

        $syncAge = if ($null -ne $sync) { Get-HeartbeatAge (Get-Value $sync 'heartbeat_unix' $null) } else { $null }
        $syncRun = if ($null -ne $sync) { [string](Get-Value $sync 'github_run_id' '') } else { '' }
        $syncSha = if ($null -ne $sync) { [string](Get-Value $sync 'github_sha' '') } else { '' }
        $githubProven = $null -ne $syncAge -and $syncAge -le 600 -and -not [string]::IsNullOrWhiteSpace($syncRun) -and $syncSha.Length -eq 40
        if ($githubProven) { Write-Line 'Connexion GitHub prouvée' ("OUI - run " + $syncRun + " il y a " + [Math]::Round($syncAge,1) + " s") Green }
        else { Write-Line 'Connexion GitHub prouvée' 'NON PROUVÉE - service local != connexion GitHub' Yellow }

        Write-Line 'Dossier laboratoire' $LabRoot White
        $free = Get-FreeGiB $LabRoot
        if ($null -ne $free) { Write-Line 'Espace disque libre' ("$free Gio") $(if($free -lt 30){[ConsoleColor]::Red}elseif($free -lt 100){[ConsoleColor]::Yellow}else{[ConsoleColor]::Green}) }

        Write-Host ''
        Write-Host '--- RUNTIME -------------------------------------------------------------------' -ForegroundColor Cyan
        if ($null -eq $status) {
            Write-Line 'État' 'EN ATTENTE DU PREMIER JOB' Cyan
        } else {
            $state=[string](Get-Value $status 'state' 'INCONNU'); $color=Get-StateColor $state
            Write-Line 'État' $state $color
            $hb=Get-HeartbeatAge (Get-Value $status 'heartbeat_unix' $null)
            if ($null -ne $hb) { Write-Line 'Dernier signe de vie' (("il y a {0:N1} s" -f $hb)) $(if($hb -le 3){[ConsoleColor]::Green}elseif($hb -le 10){[ConsoleColor]::Yellow}else{[ConsoleColor]::Red}) }
            Write-Line 'Job' (Get-Value $status 'job_id' '-') White
            Write-Line 'Suite / dataset' (([string](Get-Value $status 'suite' '-')) + ' / ' + ([string](Get-Value $status 'dataset_state' '-'))) White
            Write-Line 'Mode' (Get-Value $status 'mode' '-') White
            $stepIndex=Get-Value $status 'step_index' $null; $stepTotal=Get-Value $status 'step_total' $null
            if ($null -ne $stepIndex -and $null -ne $stepTotal) { Write-Line 'Étape' ("$stepIndex / $stepTotal") Cyan }
            Write-Optional $status 'substep' 'Sous-étape'
            Write-Optional $status 'current_file' 'Fichier courant'
            Write-Line 'Action actuelle' (Get-Value $status 'action_fr' '-') $color
            Write-Line 'Temps total du job' (Format-Duration (Get-Value $status 'job_elapsed_seconds' $null)) White
            Write-Line 'Temps étape actuelle' (Format-Duration (Get-Value $status 'stage_elapsed_seconds' $null)) White
            Write-Optional $status 'eta_seconds' 'ETA' ' s'
            Write-ProgressBar (Get-Value $status 'progress_percent' $null)
            Write-Optional $status 'processed_gib' 'Gio traités'
            Write-Optional $status 'total_gib' 'Gio total'
            Write-Optional $status 'throughput_mib_s' 'Vitesse' ' MiB/s'
            Write-Optional $status 'checkpoint' 'Checkpoint'
            Write-Optional $status 'trade_count' 'Trades'
            Write-Optional $status 'refusal_count' 'Refus'
            Write-Optional $status 'top_refusal_reason' 'Cause principale refus'
            Write-Optional $status 'dataset_state' 'État dataset'
            $pidValue=Get-Value $status 'process_id' $null
            if ($null -ne $pidValue) {
                Write-Line 'PID' $pidValue DarkGray
                $runtime=Get-ProcessRuntime $pidValue
                if ($null -ne $runtime.cpu_seconds) { Write-Line 'CPU processus (cumul)' ($runtime.cpu_seconds.ToString() + ' s') White }
                if ($null -ne $runtime.ram_mib) { Write-Line 'RAM processus' ($runtime.ram_mib.ToString() + ' MiB') White }
                if ($null -ne $runtime.child_processes) { Write-Line 'Child processes' $runtime.child_processes White }
            }
            Write-Optional $status 'last_log_line' 'Dernier message moteur'
            $logPath=Get-Value $status 'log_path' $null
            if ($LogLines -gt 0 -and $null -ne $logPath -and (Test-Path $logPath -PathType Leaf)) {
                Write-Host ''; Write-Host "--- LOG ($LogLines lignes) ---------------------------------------------------------" -ForegroundColor Cyan
                Get-Content $logPath -Tail $LogLines -Encoding UTF8 | ForEach-Object { Write-Host ('  ' + $_) -ForegroundColor Gray }
            }
        }

        Write-Host ''
        Write-Host '--- SYNCHRONISATION -----------------------------------------------------------' -ForegroundColor Cyan
        if ($null -ne $sync) {
            Write-Line 'Résultats envoyés GitHub' (Get-Value $sync 'results_sent' '-') White
            Write-Line 'Artifact public allowlisté' (Get-Value $sync 'public_artifact_allowlisted' '-') White
            Write-Line 'Gros logs restent locaux' (Get-Value $sync 'gross_logs_stay_local' '-') Green
            Write-Line 'GitHub run id' (Get-Value $sync 'github_run_id' '-') DarkGray
            Write-Line 'GitHub SHA' (Get-Value $sync 'github_sha' '-') DarkGray
        } else { Write-Line 'Synchronisation GitHub' 'AUCUNE PREUVE RECENTE' Yellow }

        Write-Host ''
        Write-Host '--- SÉCURITÉ FIXE -------------------------------------------------------------' -ForegroundColor Cyan
        Write-Line 'Trading réel' 'BLOQUÉ' Green
        Write-Line 'Exécution testnet' 'BLOQUÉE' Green
        Write-Line 'Données brutes vers GitHub' 'NON' Green
        Write-Line 'Contrôle du code' 'SHA exact de main exigé' Green
        Write-Host '==============================================================================' -ForegroundColor Cyan
        Start-Sleep -Seconds $RefreshSeconds
    }
} finally { try { [Console]::CursorVisible=$oldCursor } catch {} }
