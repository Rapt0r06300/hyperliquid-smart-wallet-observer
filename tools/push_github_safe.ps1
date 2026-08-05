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

# ---------------------------------------------------------------------------
# ROBUSTESSE 1 : purge des verrous .lock PERIMES.
#
# Un fichier .git\...\*.lock ne represente un vrai danger que si (a) une
# operation git (merge / rebase / cherry-pick / revert / bisect) est en cours,
# ou (b) un autre process 'git' tourne encore. Dans TOUS les autres cas c'est
# un residu (typiquement laisse par un pont distant qui ne peut pas faire
# 'del'), et il bloque a tort fetch/push. On le retire alors en securite.
# ---------------------------------------------------------------------------
function Clear-StaleGitLocks {
    param([string]$GitDir)

    # (a) Operation git reellement en cours -> on NE touche a rien, on refuse.
    $opMarkers = [ordered]@{
        "MERGE_HEAD"       = "un merge est en cours"
        "CHERRY_PICK_HEAD" = "un cherry-pick est en cours"
        "REVERT_HEAD"      = "un revert est en cours"
        "BISECT_LOG"       = "un bisect est en cours"
        "rebase-apply"     = "un rebase est en cours"
        "rebase-merge"     = "un rebase est en cours"
    }
    foreach ($marker in $opMarkers.Keys) {
        if (Test-Path -LiteralPath (Join-Path $GitDir $marker)) {
            throw "Operation Git en cours ($($opMarkers[$marker])). Termine-la ou annule-la a la main avant de pousser. Aucun verrou n'a ete supprime."
        }
    }

    # (b) Un autre process 'git' tourne ? Les verrous sont peut-etre legitimes.
    $gitProcs = @(Get-Process -Name git -ErrorAction SilentlyContinue)
    if ($gitProcs.Count -gt 0) {
        $pids = ($gitProcs | ForEach-Object { $_.Id }) -join ', '
        throw "Un autre process 'git' est actif (PID $pids). Ferme-le puis relance. Aucun verrou n'a ete supprime."
    }

    # (c) Aucune operation + aucun git actif => tout *.lock est PERIME -> retrait.
    $locks = @(Get-ChildItem -LiteralPath $GitDir -Recurse -Filter "*.lock" -File -Force -ErrorAction SilentlyContinue)
    foreach ($lock in $locks) {
        try {
            Remove-Item -LiteralPath $lock.FullName -Force -ErrorAction Stop
            Write-Host "      [VERROU PERIME RETIRE] $($lock.FullName)" -ForegroundColor DarkYellow
        }
        catch {
            throw "Verrou perime impossible a retirer : $($lock.FullName). $($_.Exception.Message)"
        }
    }

    # (d) Menage des dossiers-poubelle laisses par un pont distant (best-effort).
    foreach ($trash in @("_locks_trash", "zz_oldlocks")) {
        $p = Join-Path $GitDir $trash
        if (Test-Path -LiteralPath $p) {
            Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

# ---------------------------------------------------------------------------
# ROBUSTESSE 2 : verite reseau sans verrou local.
# 'git ls-remote' lit les refs de GitHub directement : il n'ecrit AUCUN .lock
# local. C'est notre preuve de push fiable, insensible aux residus locaux.
# ---------------------------------------------------------------------------
function Get-RemoteMainSha {
    $line = Get-GitText @("ls-remote", "origin", "refs/heads/main")
    if (-not $line) { return "" }
    return (($line -split "\s+")[0]).Trim()
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
        $label = "$BundleName ($sourceRef)"
        if (Test-Git @("merge-base", "--is-ancestor", $localRef, "main")) {
            Write-Host "      [DEJA INTEGRE] $label" -ForegroundColor DarkGray
        }
        elseif (Test-Git @("merge-base", "--is-ancestor", "main", $localRef)) {
            Merge-IntoMain -Ref $localRef -Label $label
        }
        else {
            # Un ancien bundle peut representer une ligne de travail deja
            # remplacee par main. On conserve sa reference nommee pour audit,
            # mais on ne fabrique jamais automatiquement un merge conflictuel.
            Write-Host "      [ARCHIVE SANS MERGE] $label diverge de main; reference conservee: $localRef" -ForegroundColor Yellow
        }
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

    # ROBUSTESSE 1 : on purge les verrous perimes AVANT toute commande qui ecrit.
    Write-Step "Controle des verrous Git perimes..."
    Clear-StaleGitLocks -GitDir $gitDir

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

    # ROBUSTESSE 2 : preuve du push par GitHub lui-meme (ls-remote, zero verrou local).
    $localSha = Get-GitText @("rev-parse", "main")
    $remoteSha = Get-RemoteMainSha
    if (-not $remoteSha) {
        throw "Impossible de relire origin/main via ls-remote apres le push."
    }
    if ($localSha -ne $remoteSha) {
        throw "Verification finale incoherente : main=$localSha, origin/main(GitHub)=$remoteSha."
    }

    # ROBUSTESSE 3 : la mise a jour du ref de SUIVI local est purement COSMETIQUE.
    # Le push est deja prouve reussi ci-dessus. Si ce fetch bute sur un residu,
    # on l'IGNORE : jamais un push reussi ne doit etre rapporte en echec.
    try {
        Clear-StaleGitLocks -GitDir $gitDir
        Invoke-Git @("fetch", "--prune", "origin", "main")
    }
    catch {
        Write-Host "  [INFO] Suivi local origin/main non rafraichi (cosmetique, sans impact sur le push) : $($_.Exception.Message)" -ForegroundColor DarkGray
    }

    $shortSha = Get-GitText @("rev-parse", "--short=12", "main")
    $remoteUrl = Get-GitText @("remote", "get-url", "origin")
    Write-Host "`n  [OK] main local et origin/main (GitHub) sont identiques : $shortSha" -ForegroundColor Green
    Write-Host "       $remoteUrl" -ForegroundColor Green
    exit 0
}
catch {
    Write-Host "`n  [ERREUR] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  Aucun push force ni reset destructeur n'a ete effectue." -ForegroundColor Yellow
    exit 1
}
