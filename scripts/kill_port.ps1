param([int]$Port = 8002)

$conns = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
if (-not $conns) { exit 0 }

$pids = $conns.OwningProcess | Sort-Object -Unique
foreach ($procId in $pids) {
    if ($procId -and $procId -ne 0) {
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Write-Host "Stopped PID $procId on port $Port"
        } catch {
            taskkill /F /PID $procId 2>$null
        }
    }
}
Start-Sleep -Seconds 2
