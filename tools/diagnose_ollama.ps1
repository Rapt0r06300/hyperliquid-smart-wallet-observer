param(
  [string]$HostUrl = "http://127.0.0.1:11434"
)

$ErrorActionPreference = "Continue"
Write-Host "[HyperSmart] Diagnostic Ollama local (read-only explainer)"
$cmd = Get-Command ollama -ErrorAction SilentlyContinue
if ($null -eq $cmd) {
  Write-Host "ollama_installed=false"
  Write-Host "recommendation=Run tools\\install_ollama_optional.ps1, then restart the launcher."
  exit 0
}

Write-Host "ollama_installed=true"
Write-Host "ollama_path=$($cmd.Source)"
try {
  $version = & ollama --version 2>$null
  Write-Host "ollama_version=$version"
} catch {
  Write-Host "ollama_version_error=$($_.Exception.Message)"
}

try {
  $tags = Invoke-RestMethod -Uri "$HostUrl/api/tags" -Method Get -TimeoutSec 2
  Write-Host "ollama_api=true"
  Write-Host "models_count=$($tags.models.Count)"
  $tags.models | ForEach-Object { Write-Host "model=$($_.name)" }
  Write-Host "native_generate_endpoint=$HostUrl/api/generate"
  Write-Host "openai_compatible_endpoint=$HostUrl/v1/chat/completions"
} catch {
  Write-Host "ollama_api=false"
  Write-Host "api_error=$($_.Exception.Message)"
}

Write-Host "hot_path=false"
Write-Host "env_HYPERSMART_V13_OLLAMA_ENABLED=$env:HYPERSMART_V13_OLLAMA_ENABLED"
Write-Host "env_HYPERSMART_V13_OLLAMA_MODEL=$env:HYPERSMART_V13_OLLAMA_MODEL"
Write-Host "env_OLLAMA_BASE_URL=$env:OLLAMA_BASE_URL"
Write-Host "usage=offline explanations only; never opens/closes paper positions."
