$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$case = Join-Path $root ("runtime\portable-build\e2e-" + [Guid]::NewGuid().ToString("N"))
$source = Join-Path $case "source"
$release = Join-Path $source "release"
$target = Join-Path $case "installed\Projet invest"
$cache = Join-Path $case "cache"
New-Item -ItemType Directory -Path (Join-Path $source "data"), (Join-Path $source "empty"), $release | Out-Null
[IO.File]::WriteAllBytes((Join-Path $source "data\payload.bin"), [Text.Encoding]::UTF8.GetBytes(("alina-" * 10000)))
[IO.File]::WriteAllText((Join-Path $source "README.txt"), "copie exacte", [Text.UTF8Encoding]::new($false))
$python = Join-Path $root "portable_runtime\python_backup_20260813_224532\python.exe"

& $python -m hl_observer.ops.full_folder_release plan --root $source --output $release --head ("c" * 40)
if ($LASTEXITCODE -ne 0) { throw "Plan de test échoué." }
Push-Location $source
try {
    & "C:\Program Files\7-Zip\7z.exe" a (Join-Path $release "Alina-SmartFlow-Full.7z") -t7z -mx=1 -mmt=1 -v1m -scsUTF-8 ("@" + (Join-Path $release "archive-members.txt")) | Out-Null
} finally {
    Pop-Location
}
if ($LASTEXITCODE -ne 0) { throw "Archive de test échouée." }
& $python -m hl_observer.ops.full_folder_release finalize --root $source --output $release --tag smoke-e2e --head ("c" * 40) --repository Rapt0r06300/hyperliquid-smart-wallet-observer
if ($LASTEXITCODE -ne 0) { throw "Manifeste de test échoué." }

$manifest = Join-Path $release "ALINA_FULL_FOLDER_RELEASE.json"
$hash = (Get-FileHash -Algorithm SHA256 $manifest).Hash.ToLowerInvariant()
$template = Get-Content -Raw (Join-Path $root "tools\full_folder_installer\ReleaseInfo.template.cs")
$info = $template.Replace("__REPOSITORY__", "Rapt0r06300/hyperliquid-smart-wallet-observer").Replace("__TAG__", "smoke-e2e").Replace("__GIT_HEAD__", ("c" * 40)).Replace("__MANIFEST_SHA256__", $hash).Replace("__MANIFEST_URL__", "http://127.0.0.1:18765/ALINA_FULL_FOLDER_RELEASE.json")
$infoPath = Join-Path $release "ReleaseInfo.generated.cs"
[IO.File]::WriteAllText($infoPath, $info, [Text.UTF8Encoding]::new($false))
$installer = Join-Path $case "Installer.exe"
& "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /optimize+ /target:exe /platform:anycpu /out:$installer /reference:System.Web.Extensions.dll /resource:"C:\Program Files\7-Zip\7z.exe,Alina.Embedded.7z.exe" /resource:"C:\Program Files\7-Zip\7z.dll,Alina.Embedded.7z.dll" (Join-Path $root "tools\full_folder_installer\AlinaFullInstaller.cs") $infoPath
if ($LASTEXITCODE -ne 0) { throw "Compilation de test échouée." }

$serverArguments = @("-m", "http.server", "18765", "--bind", "127.0.0.1", "--directory", ('"' + $release + '"'))
$server = Start-Process -FilePath $python -ArgumentList $serverArguments -WindowStyle Hidden -PassThru
try {
    Start-Sleep -Milliseconds 800
    & $installer --yes --base-url http://127.0.0.1:18765 --destination $target --cache $cache
    if ($LASTEXITCODE -ne 0) { throw "Installateur de test échoué." }
} finally {
    Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
}

if ((Get-FileHash (Join-Path $source "data\payload.bin")).Hash -ne (Get-FileHash (Join-Path $target "data\payload.bin")).Hash) {
    throw "Le contenu installé diffère."
}
if (-not (Test-Path (Join-Path $target "empty") -PathType Container)) { throw "Le dossier vide n'a pas été restauré." }
Write-Host "E2E_INSTALLER_OK"
Get-Item $installer | Select-Object FullName, Length
