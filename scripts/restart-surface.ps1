# Beendet laufende Python-Prozesse die SAFIR Backend hosten und startet
# start-surface.cmd neu. Benoetigt UAC-Elevation weil der alte Prozess
# unter einem anderen User laeuft (the_s vs Jaimy).

param(
    [switch]$SkipRestart
)

Write-Host "Suche laufende Python-Prozesse..."
$pyProcs = Get-Process python -ErrorAction SilentlyContinue
if (-not $pyProcs) {
    Write-Host "Keine python.exe laeuft."
} else {
    foreach ($p in $pyProcs) {
        Write-Host "Beende PID $($p.Id) (gestartet $($p.StartTime))..."
        try {
            Stop-Process -Id $p.Id -Force -ErrorAction Stop
            Write-Host "  OK."
        } catch {
            Write-Host "  FEHLER: $_"
        }
    }
    Start-Sleep -Seconds 2
}

# Verify gone
$stillRunning = Get-Process python -ErrorAction SilentlyContinue
if ($stillRunning) {
    Write-Host "WARNUNG: Es laufen noch python.exe-Prozesse:"
    $stillRunning | Format-Table Id,StartTime -AutoSize
    exit 1
}

if ($SkipRestart) {
    Write-Host "SkipRestart gesetzt, Backend nicht neu gestartet."
    exit 0
}

Write-Host ""
Write-Host "Starte Surface-Backend mit Auto-Reload neu..."
$startCmd = "C:\Users\the_s\Documents\SAFIR\backend\start-surface.cmd"
Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $startCmd -WindowStyle Normal
Write-Host "Backend-Terminal geoeffnet. Warte 5 Sekunden auf Start..."
Start-Sleep -Seconds 5

# Verify endpoint
try {
    $resp = Invoke-RestMethod -Uri "http://localhost:8080/api/status" -Method Get -TimeoutSec 5
    Write-Host "API /api/status OK. device=$($resp.device) patients=$($resp.patients_total)"
} catch {
    Write-Host "API /api/status antwortet noch nicht: $_"
}
