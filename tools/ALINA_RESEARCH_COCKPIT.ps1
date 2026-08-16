[CmdletBinding()]
param(
    [string]$LabRoot = $env:ALINA_RESEARCH_HOME,
    [ValidateRange(1, 60)]
    [int]$RefreshSeconds = 1,
    [ValidateRange(0, 30)]
    [int]$LogLines = 8
)

$ErrorActionPreference = 'SilentlyContinue'

function Write-Line([string]$Label, [object]$Value, [ConsoleColor]$Color = [ConsoleColor]::White) {
    if ($null -eq $Value) { $Value = '-' }
    Write-Host ($Label.PadRight(28) + ': ') -NoNewline -ForegroundColor DarkGray
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
    } catch {
        return $Default
    }
}

function Get-BoolText([object]$Value, [string]$TrueText = 'OUI', [string]$FalseText = 'NON') {
    if ($Value -eq $true) { return $TrueText }
    if ($Value -eq $false) { return $FalseText }
    return 'EN ATTENTE'
}

function Read-JsonSafe([string]$Path) {
    if (-not (Test-Path $Path -PathType Leaf)) { return $null }
    try {
        return Get-Content $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Format-Duration([object]$Seconds) {
    if ($null -eq $Seconds -or [string]$Seconds -eq '-') { return '--:--:--' }
    try {
        $value = [Math]::Max(0, [double]$Seconds)
        $span = [TimeSpan]::FromSeconds($value)
        if ($span.TotalDays -ge 1) {
            return ('{0}j {1:00}:{2:00}:{3:00}' -f [Math]::Floor($span.TotalDays), $span.Hours, $span.Minutes, $span.Seconds)
        }
        return ('{0:00}:{1:00}:{2:00}' -f [Math]::Floor($span.TotalHours), $span.Minutes, $span.Seconds)
    } catch {
        return '--:--:--'
    }
}

function Get-RunnerService {
    return Get-Service -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like 'actions.runner.*' -or $_.DisplayName -like '*GitHub Actions Runner*' } |
        Select-Object -First 1
}

function Get-FreeGiB([string]$Path) {
    try {
        $full = [System.IO.Path]::GetFullPath($Path)
        $root = [System.IO.Path]::GetPathRoot($full)
        $drive = Get-PSDrive -Name $root.Substring(0, 1) -ErrorAction Stop
        return [Math]::Round($drive.Free / 1GB, 2)
    } catch {
        return $null
    }
}

function Get-HeartbeatAge([object]$HeartbeatUnix) {
    if ($null -eq $HeartbeatUnix -or [string]$HeartbeatUnix -eq '-') { return $null }
    try {
        $now = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0
        return [Math]::Max(0, $now - [double]$HeartbeatUnix)
    } catch {
        return $null
    }
}

function Get-StateColor([string]$State) {
    switch ($State) {
        'SUCCESS' { return [ConsoleColor]::Green }
        'SUCCESS_CACHED' { return [ConsoleColor]::Green }
        'WAITING' { return [ConsoleColor]::Cyan }
        'RUNNING' { return [ConsoleColor]::Green }
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

function Write-ProgressBar([object]$Percent) {
    if ($null -eq $Percent -or [string]$Percent -eq '-') {
        Write-Line 'Progression précise' 'Non fournie; le signe de vie confirme que le moteur travaille.' DarkGray
        return
    }
    try {
        $p = [Math]::Max(0, [Math]::Min(100, [double]$Percent))
        $filled = [int][Math]::Round($p / 5)
        $bar = ('#' * $filled) + ('-' * (20 - $filled))
        Write-Line 'Progression' ('[{0}] {1:N1} %' -f $bar, $p) Green
    } catch {
        Write-Line 'Progression' 'Indisponible' DarkGray
    }
}

if ([string]::IsNullOrWhiteSpace($LabRoot)) {
    Write-Host ''
    Write-Host 'ALINA RESEARCH COCKPIT' -ForegroundColor Cyan
    Write-Host 'Le laboratoire n est pas encore installé sur ce PC.' -ForegroundColor Yellow
    Write-Host 'C est normal avant la première installation du runner.'
    Write-Host 'L installateur créera automatiquement ALINA_RESEARCH_HOME.'
    exit 2
}

try {
    $LabRoot = [System.IO.Path]::GetFullPath($LabRoot)
} catch {
    Write-Host "Chemin du laboratoire invalide : $LabRoot" -ForegroundColor Red
    exit 2
}

$statusPath = Join-Path $LabRoot 'status\CURRENT_STATUS.json'
$syncPath = Join-Path $LabRoot 'status\GITHUB_SYNC_STATUS.json'
$oldCursor = $true
try {
    $oldCursor = [Console]::CursorVisible
    [Console]::CursorVisible = $false
} catch {}

try {
    while ($true) {
        Clear-Host
        $nowText = (Get-Date).ToString('dd/MM/yyyy HH:mm:ss')
        Write-Host '==============================================================================' -ForegroundColor Cyan
        Write-Host ' ALINA SMARTFLOW - COCKPIT DU LABORATOIRE AUTONOME' -ForegroundColor Cyan
        Write-Host '==============================================================================' -ForegroundColor Cyan
        Write-Host " Mise à jour : toutes les $RefreshSeconds seconde(s) | Heure : $nowText"
        Write-Host ' Ctrl+C ferme uniquement cet écran. Le laboratoire continue son travail.' -ForegroundColor DarkGray
        Write-Host ''

        $service = Get-RunnerService
        if ($service -and $service.Status -eq 'Running') {
            Write-Line 'Passerelle GitHub' 'EN LIGNE - prête à recevoir les jobs' Green
        } elseif ($service) {
            Write-Line 'Passerelle GitHub' ("SERVICE " + $service.Status) Yellow
        } else {
            Write-Line 'Passerelle GitHub' 'Service runner non détecté' Red
        }
        Write-Line 'Dossier du laboratoire' $LabRoot White
        $free = Get-FreeGiB $LabRoot
        if ($null -ne $free) {
            $diskColor = if ($free -lt 30) { [ConsoleColor]::Red } elseif ($free -lt 100) { [ConsoleColor]::Yellow } else { [ConsoleColor]::Green }
            Write-Line 'Espace disque libre' ("$free Gio") $diskColor
        }

        Write-Host ''
        Write-Host '--- CE QUE FAIT ALINA MAINTENANT ---------------------------------------------' -ForegroundColor Cyan

        $status = Read-JsonSafe $statusPath
        $sync = Read-JsonSafe $syncPath

        if ($null -eq $status) {
            Write-Line 'État' 'EN ATTENTE DU PREMIER JOB' Cyan
            Write-Line 'Explication' 'Aucun calcul n a encore démarré dans ce laboratoire.' DarkGray
            Write-Line 'Ce qui se passe' 'Le runner attend silencieusement un travail envoyé par GitHub.' White
        } else {
            $state = [string](Get-Value $status 'state' 'INCONNU')
            $stateColor = Get-StateColor $state
            $heartbeatAge = Get-HeartbeatAge (Get-Value $status 'heartbeat_unix' $null)
            Write-Line 'État' $state $stateColor
            if ($null -ne $heartbeatAge) {
                $heartbeatColor = if ($heartbeatAge -le 3) { [ConsoleColor]::Green } elseif ($heartbeatAge -le 10) { [ConsoleColor]::Yellow } else { [ConsoleColor]::Red }
                Write-Line 'Dernier signe de vie' (("il y a {0:N1} s" -f $heartbeatAge)) $heartbeatColor
                if ($heartbeatAge -gt 10 -and $state -in @('RUNNING','STARTING','FINALIZING')) {
                    Write-Host '  ATTENTION : plus de signe de vie récent. Le worker peut être arrêté.' -ForegroundColor Red
                }
            }
            Write-Line 'Job' (Get-Value $status 'job_id' '-') White
            Write-Line 'Suite de données' (Get-Value $status 'suite' '-') White
            Write-Line 'Mode' (Get-Value $status 'mode' '-') White
            $stepIndex = Get-Value $status 'step_index' $null
            $stepTotal = Get-Value $status 'step_total' $null
            if ($null -ne $stepIndex -and $null -ne $stepTotal) {
                Write-Line 'Étape' ("$stepIndex / $stepTotal") Cyan
            }
            Write-Line 'Action actuelle' (Get-Value $status 'action_fr' '-') $stateColor
            Write-Line 'Explication' (Get-Value $status 'message_fr' '-') White
            Write-Line 'Temps total du job' (Format-Duration (Get-Value $status 'job_elapsed_seconds' $null)) White
            Write-Line 'Temps étape actuelle' (Format-Duration (Get-Value $status 'stage_elapsed_seconds' $null)) White
            Write-ProgressBar (Get-Value $status 'progress_percent' $null)
            $nextAction = Get-Value $status 'next_action_fr' $null
            if ($null -ne $nextAction) { Write-Line 'Ensuite' $nextAction Cyan }
            $workspace = Get-Value $status 'workspace' $null
            if ($null -ne $workspace) { Write-Line 'Workspace utilisé' $workspace DarkGray }
            $pidValue = Get-Value $status 'process_id' $null
            if ($null -ne $pidValue) { Write-Line 'Processus calcul' $pidValue DarkGray }
            $lastLine = Get-Value $status 'last_log_line' $null
            if ($null -ne $lastLine) { Write-Line 'Dernier message moteur' $lastLine Yellow }

            $logPath = Get-Value $status 'log_path' $null
            if ($LogLines -gt 0 -and $null -ne $logPath -and (Test-Path $logPath -PathType Leaf)) {
                Write-Host ''
                Write-Host "--- DERNIÈRES LIGNES DU JOURNAL ($LogLines) ------------------------------------" -ForegroundColor Cyan
                Get-Content $logPath -Tail $LogLines -Encoding UTF8 | ForEach-Object {
                    Write-Host ('  ' + $_) -ForegroundColor Gray
                }
            }
        }

        Write-Host ''
        Write-Host '--- APRÈS LE CALCUL : OÙ SONT LES RÉSULTATS ? --------------------------------' -ForegroundColor Cyan
        $currentState = if ($null -ne $status) { [string](Get-Value $status 'state' '') } else { '' }
        $calculationDone = $currentState -in @('SUCCESS','SUCCESS_CACHED','NO_GO','TIMEBOX_REACHED','TIMEOUT','ERROR','STEP_ERROR')
        Write-Line 'CALCUL TERMINÉ' (Get-BoolText $calculationDone) $(if ($calculationDone) { [ConsoleColor]::Green } else { [ConsoleColor]::Cyan })

        if ($null -ne $sync) {
            $sent = Get-Value $sync 'results_sent' $null
            $reportCount = Get-Value $sync 'report_count' 0
            $waiting = Get-Value $sync 'waiting_for_analysis' $null
            $requeued = Get-Value $sync 'requeued' $false
            $syncJob = [string](Get-Value $sync 'job_id' '')
            $currentJob = if ($null -ne $status) { [string](Get-Value $status 'job_id' '') } else { '' }
            $sameJob = (-not [string]::IsNullOrWhiteSpace($currentJob)) -and ($syncJob -eq $currentJob)
            if ($sameJob) {
                $sentColor = if ($sent -eq $true) { [ConsoleColor]::Green } elseif ($sent -eq $false) { [ConsoleColor]::Red } else { [ConsoleColor]::Yellow }
                Write-Line 'Résultats envoyés GitHub' (Get-BoolText $sent) $sentColor
                Write-Line 'Rapports remontés' $reportCount White
                Write-Line 'Gros logs conservés localement' 'OUI' Green
                if ($requeued -eq $true) {
                    Write-Line 'En attente prochaine analyse' 'NON - le même job reprend automatiquement' Yellow
                } else {
                    Write-Line 'En attente prochaine analyse' (Get-BoolText $waiting) $(if ($waiting -eq $true) { [ConsoleColor]::Green } else { [ConsoleColor]::Yellow })
                }
                $syncMessage = Get-Value $sync 'message_fr' $null
                if ($null -ne $syncMessage) { Write-Line 'Synchronisation' $syncMessage DarkGray }
            } else {
                Write-Line 'Résultats envoyés GitHub' 'EN ATTENTE - aucune synchro du job actuel reçue' Yellow
                Write-Line 'Gros logs conservés localement' 'OUI' Green
                Write-Line 'En attente prochaine analyse' 'EN ATTENTE' Yellow
            }
        } else {
            if ($calculationDone) {
                Write-Line 'Résultats envoyés GitHub' 'EN COURS / EN ATTENTE DE CONFIRMATION' Yellow
                Write-Line 'Rapports remontés' 'EN ATTENTE' Yellow
            } else {
                Write-Line 'Résultats envoyés GitHub' 'PAS ENCORE - le calcul travaille' DarkGray
                Write-Line 'Rapports remontés' '0 pour le moment' DarkGray
            }
            Write-Line 'Gros logs conservés localement' 'OUI' Green
            Write-Line 'En attente prochaine analyse' 'PAS ENCORE' DarkGray
        }

        Write-Host ''
        Write-Host '--- SÉCURITÉ FIXE DU LABORATOIRE ---------------------------------------------' -ForegroundColor Cyan
        Write-Line 'Trading réel' 'BLOQUÉ' Green
        Write-Line 'Exécution testnet' 'BLOQUÉE' Green
        Write-Line 'Collecte live FULL/COLD' 'BLOQUÉE' Green
        Write-Line 'Données brutes vers GitHub' 'NON - uniquement de petits rapports' Green
        Write-Line 'Contrôle du code' 'SHA exact de main exigé avant chaque job' Green
        Write-Host ''
        Write-Host 'Cet écran est un moniteur : il explique ce qui se passe mais ne trade rien.' -ForegroundColor DarkGray
        Write-Host '==============================================================================' -ForegroundColor Cyan

        Start-Sleep -Seconds $RefreshSeconds
    }
} finally {
    try { [Console]::CursorVisible = $oldCursor } catch {}
}
