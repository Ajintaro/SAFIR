# Findet laufende Python-Prozesse und ihre Terminal-Fenster
$py = Get-WmiObject Win32_Process -Filter "name='python.exe'"
foreach ($p in $py) {
    $parent = Get-WmiObject Win32_Process -Filter "ProcessId=$($p.ParentProcessId)"
    Write-Host "PID $($p.ProcessId): $($p.CommandLine)"
    Write-Host "  Parent PID $($p.ParentProcessId) $($parent.Name) :: $($parent.CommandLine)"
    $gp = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue
    if ($gp) {
        Write-Host "  MainWindowTitle $($gp.MainWindowTitle)"
    }
    Write-Host ""
}

Write-Host "--- cmd.exe with MainWindowTitle ---"
Get-Process cmd -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -ne "" } | Format-Table Id,ProcessName,MainWindowTitle -AutoSize

Write-Host "--- conhost.exe ---"
Get-Process conhost -ErrorAction SilentlyContinue | Format-Table Id,ProcessName,MainWindowTitle -AutoSize

Write-Host "--- WindowsTerminal ---"
Get-Process WindowsTerminal -ErrorAction SilentlyContinue | Format-Table Id,ProcessName,MainWindowTitle -AutoSize
