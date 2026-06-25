$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$envFile = Join-Path $root "local\admin.env"
if (-not (Test-Path $envFile)) { Write-Host "Missing local/admin.env - run fetch_local_env.ps1"; exit 1 }
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
    $p = $_ -split '=', 2
    Set-Item -Path "env:$($p[0].Trim())" -Value $p[1].Trim()
}
$env:PYTHONPATH = $root
Write-Host "[admin] migrations..." -ForegroundColor Cyan
python -m alembic -c migrations/central/alembic.ini upgrade head
python scripts/seed_admin.py
Write-Host "[admin] http://localhost:8001" -ForegroundColor Green
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
