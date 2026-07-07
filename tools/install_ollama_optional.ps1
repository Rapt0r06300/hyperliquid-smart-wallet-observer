param(
  [string]$Model = "llama3.2",
  [switch]$SkipModelPull
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$LogDir = Join-Path $Root "logs"
$LogPath = Join-Path $LogDir "ollama_install.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Log($msg) {
  $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
  Write-Host $line
  Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
}

function Test-OllamaApi {
  param([string]$HostUrl = "http://127.0.0.1:11434")
  try {
    Invoke-RestMethod -Uri "$HostUrl/api/tags" -Method Get -TimeoutSec 2 | Out-Null
    return $true
  } catch {
    return $false
  }
}

function Ensure-OllamaApi {
  param([string]$HostUrl = "http://127.0.0.1:11434")
  if (Test-OllamaApi -HostUrl $HostUrl) { return $true }
  Log "ollama_api_waiting=true"
  try {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) {
      Start-Process -FilePath $cmd.Source -ArgumentList "serve" -WindowStyle Hidden -ErrorAction SilentlyContinue | Out-Null
    }
  } catch {
    Log "ollama_serve_start_error=$($_.Exception.Message)"
  }
  for ($i = 1; $i -le 30; $i++) {
    Start-Sleep -Seconds 1
    if (Test-OllamaApi -HostUrl $HostUrl) {
      Log "ollama_api_ready_after_seconds=$i"
      return $true
    }
  }
  Log "ollama_api_ready=false"
  return $false
}

Log "HyperSmart Ollama optional installer starting."
Log "Purpose: local read-only/offline explanations. No hot-path decisions. No real orders."

$cmd = Get-Command ollama -ErrorAction SilentlyContinue
if ($null -eq $cmd) {
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if ($null -eq $winget) {
    Log "winget_not_found=true"
    Log "Install Ollama manually from https://ollama.com/download, then rerun tools\\diagnose_ollama.ps1."
    exit 2
  }
  Log "Installing Ollama via winget id=Ollama.Ollama"
  & winget install --id Ollama.Ollama -e --silent --accept-package-agreements --accept-source-agreements
  Log "winget_install_exit=$LASTEXITCODE"
} else {
  Log "ollama_already_installed=$($cmd.Source)"
}

$cmd = Get-Command ollama -ErrorAction SilentlyContinue
if ($null -eq $cmd) {
  Log "ollama_still_missing=true"
  exit 3
}

try {
  $version = & ollama --version
  Log "ollama_version=$version"
} catch {
  Log "ollama_version_error=$($_.Exception.Message)"
}

if (-not $SkipModelPull) {
  if (Ensure-OllamaApi) {
    Log "Pulling model=$Model"
    & ollama pull $Model
    Log "ollama_pull_exit=$LASTEXITCODE"
  } else {
    Log "model_pull_skipped=ollama_api_unavailable"
    exit 4
  }
}

Log "Set HYPERSMART_V13_OLLAMA_ENABLED=1 to enable dashboard explanations."
Log "Installer done."
