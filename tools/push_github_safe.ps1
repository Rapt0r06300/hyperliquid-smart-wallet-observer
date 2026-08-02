[CmdletBinding()]
param(
    [Parameter()]
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),

    [Parameter()]
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step {
    param([string]$Message)
    Write-Host "  $Message" -ForegroundColor Cyan
}

function Invoke-Git {
    param([string[]]$GitArgs)

    & git @GitArgs
    if ($LASTEXITCODE -ne 0) {
        throw "git $($GitArgs -join ' ') a echoue (code $LASTEXITCODE)."
    }
}

function Get-GitText {
    param([string[]]$GitArgs)

    $output = & git @GitArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($GitArgs -join ' ') a echoue : $($output -join [Environment]::NewLine)"
    }
    return (($output | Out-String).Trim())
}

function Test-Git {
    param([string[]]$GitArgs)

    & git @GitArgs *> $null
    return ($LASTEXITCODE -eq 0)
}

function Merge-IntoMain {
    param(
        [string]$Ref,
        [string]$Label
    )

    if (Test-Git @("merge-base", "--is-ancestor", $Ref, "main")) {
        Write-Host "      [DEJA INTEGRE] $Label" -ForegroundColor DarkGray
        return
    }

    if ($DryRun) {
        Write-Host "      [DRY-RUN] $Label devrait etre integre dans main." -ForegroundColor Yellow
        return
    }

    try {
        if (Test-Git @("merge-base", "--is-ancestor", "main", $Ref)) {
            Invoke-Git @("merge", "--ff-only", $Ref)
        }
        else {
            Invoke-Git @("merge", "--no-edit", $Ref)
        }
    }
    catch {
        & git merge --abort *> $null
        throw "Conflit pendant l'integration de $Label. La tentative a ete annulee sans perdre les commits. $($_.Exception.Message)"
    }
}

function Import-Bundle {
    param([string]$BundleName)

    $bundlePath = Join-Path $ProjectRoot $BundleName
    if (-not (Test-Path -LiteralPath $bundlePath -PathType Leaf)) {
        return
    }

    Write-Step "Verification du bundle historique $BundleName..."
    Invoke-Git @("bundle", "verify", $bundlePath)
    $heads = Get-GitText @("bundle", "list-heads", $bundlePath)
    $bundleKey = ([IO.Path]::GetFileNameWithoutExtension($BundleName) -replace "[^A-Za-z0-9._-]", "-")
    $foundBranch = $false

    foreach ($line in ($heads -split "`r?`n")) {
        if ($line -notmatch "^([0-9a-fA-F]{40,64})\s+(refs/heads/.+)$") {
            continue
        }

        $foundBranch = $true
        $sourceRef = $Matches[2]
        $branchPart = ($sourceRef -replace "^refs/heads/", "") -replace "[^A-Za-z0-9._/-]", "-"
        $localRef = "refs/remotes/hypersmart-bundles/$bundleKey/$branchPart"

        if ($DryRun) {
            Write-Host "      [DRY-RUN] branche $sourceRef detectee dans $BundleName." -ForegroundColor Yellow
            continue
        }

        Invoke-Git @("fetch", "--no-tags", "--force", $bundlePath, "$sourceRef`:$localRef")
        Merge-IntoMain -Ref $localRef -Label "$BundleName ($sourceRef)"
    }

    if (-not $foundBranch) {
        Write-Host "      [INFO] Aucun refs/heads/* importable dans $BundleName." -ForegroundColor DarkGray
    }
}

function Reconcile-OriginMain {
    Write-Step "Reconciliation de main avec origin/main..."
    Merge-IntoMain -Ref "refs/remotes/origin/main" -Label "origin/main"
}

try {
    $ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd("\", "/")
    Set-Location -LiteralPath $ProjectRoot

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git est introuvable dans le PATH."
    }
    if (-not (Test-Git @("rev-parse", "--is-inside-work-tree"))) {
        throw "$ProjectRoot n'est pas un depot Git."
    }

    $branch = Get-GitText @("branch", "--show-current")
    if ($branch -ne "main") {
        throw "Branche active '$branch'. Ce bouton travaille uniquement sur main."
    }

    $gitDirText = Get-GitText @("rev-parse", "--git-dir")
    $gitDir = if ([IO.Path]::IsPathRooted($gitDirText)) {
        $gitDirText
    }
    else {
        Join-Path $ProjectRoot $gitDirText
    }
    $operationMarkers = @("index.lock", "MERGE_HEAD", "rebase-apply", "rebase-merge")
    foreach ($marker in $operationMarkers) {
        if (Test-Path -LiteralPath (Join-Path $gitDir $marker)) {
            throw "Operation Git en cours ou verrou present : $marker. Le script refuse de le supprimer automatiquement."
        }
    }

    $dirty = Get-GitText @("status", "--porcelain")
    if ($dirty) {
        if (-not $DryRun) {
            throw "Le working tree contient des changements non commites. Committe-les d'abord afin que le push soit complet et explicite.`n$dirty"
        }
        Write-Host "  [DRY-RUN] Changements locaux detectes; aucun commit ne sera cree." -ForegroundColor Yellow
    }

    Write-Step "Recuperation de origin/main via sa reference distante nommee..."
    Invoke-Git @("fetch", "--prune", "origin", "main")
    Reconcile-OriginMain

    Import-Bundle -BundleName "hypersmart_launcher.bundle"
    Import-Bundle -BundleName "hypersmart_428.bundle"

    if ($DryRun) {
        Write-Host "`n  [DRY-RUN OK] Verification terminee; aucun merge et aucun push effectues." -ForegroundColor Green
        exit 0
    }

    # Referme la petite fenetre de course si GitHub avance pendant l'import des bundles.
    Invoke-Git @("fetch", "--prune", "origin", "main")
    Reconcile-OriginMain

    Write-Step "Envoi exclusif de la branche locale main vers origin/main..."
    Invoke-Git @("push", "origin", "main:main")

    Invoke-Git @("fetch", "--prune", "origin", "main")
    $localSha = Get-GitText @("rev-parse", "main")
    $remoteSha = Get-GitText @("rev-parse", "refs/remotes/origin/main")
    if ($localSha -ne $remoteSha) {
        throw "Verification finale incoherente : main=$localSha, origin/main=$remoteSha."
    }

    $shortSha = Get-GitText @("rev-parse", "--short=12", "main")
    $remoteUrl = Get-GitText @("remote", "get-url", "origin")
    Write-Host "`n  [OK] main et origin/main sont identiques : $shortSha" -ForegroundColor Green
    Write-Host "       $remoteUrl" -ForegroundColor Green
    exit 0
}
catch {
    Write-Host "`n  [ERREUR] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  Aucun push force, reset destructeur ou suppression de verrou n'a ete effectue." -ForegroundColor Yellow
    exit 1
}
