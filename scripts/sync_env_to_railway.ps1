# Push WhatsApp + Gemini vars from .env to Railway agent service.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/sync_env_to_railway.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$envFile = Join-Path $root ".env"
$service = "Restaurant-Watsapp-Ai-Automation"

if (-not (Test-Path $envFile)) {
    Write-Host "Missing .env in project root" -ForegroundColor Red
    exit 1
}

$vars = @{}
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
    $p = $_ -split '=', 2
    if ($p.Count -eq 2) { $vars[$p[0].Trim()] = $p[1].Trim() }
}

$keys = @(
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_VERIFY_TOKEN",
    "WHATSAPP_APP_SECRET",
    "GROQ_API_KEY",
    "GROQ_MODEL",
    "GROQ_WHISPER_MODEL",
    "AI_PROVIDER",
    "GEMINI_API_KEY",
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_VOICE_ID",
    "ELEVENLABS_MODEL_ID"
)

$toSet = @()
foreach ($k in $keys) {
    if ($vars.ContainsKey($k) -and $vars[$k]) {
        $toSet += "$k=$($vars[$k])"
    }
}

if ($vars.ContainsKey("GEMINI_API_KEY") -and $vars["GEMINI_API_KEY"]) {
    $toSet += "GOOGLE_API_KEY=$($vars['GEMINI_API_KEY'])"
}

if ($toSet.Count -eq 0) {
    Write-Host "No WhatsApp/Gemini vars found in .env" -ForegroundColor Red
    exit 1
}

Write-Host "Setting on Railway ($service):" -ForegroundColor Cyan
foreach ($pair in $toSet) {
    $name = ($pair -split '=', 2)[0]
    Write-Host "  $name"
}

Write-Host "Verifying WhatsApp token..." -ForegroundColor Cyan
& (Join-Path $PSScriptRoot "check_whatsapp_token.ps1")
if ($LASTEXITCODE -ne 0) {
    Write-Host "Aborting sync — fix WHATSAPP_ACCESS_TOKEN in .env first." -ForegroundColor Red
    exit 1
}

railway variables set @toSet --service $service
Write-Host "Done. Redeploying..." -ForegroundColor Green
railway up --detach --service $service
