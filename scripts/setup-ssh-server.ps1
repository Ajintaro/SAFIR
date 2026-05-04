# =====================================================================
# SAFIR/SINA - OpenSSH Server Setup (einmalige Admin-Action)
#
# Installiert die Windows-OpenSSH-Server-Capability, startet den
# sshd-Dienst und legt eine Firewall-Regel fuer TCP/22 an.
#
# Aufruf: rechtsklick "mit PowerShell ausfuehren" als Admin, oder
# manuell aus Admin-Shell: powershell -ExecutionPolicy Bypass -File
# C:\Users\Rettung\Documents\SAFIR\scripts\setup-ssh-server.ps1
# =====================================================================

$ErrorActionPreference = 'Continue'

Write-Host ""
Write-Host "=== SAFIR/SINA  OpenSSH-Server-Setup ===" -ForegroundColor Cyan
Write-Host ""

# 1) Admin-Check
$isAdmin = (New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "[FEHLER] Dieses Skript muss als Administrator laufen." -ForegroundColor Red
    Write-Host "Rechtsklick -> 'Mit PowerShell ausfuehren' (Admin)." -ForegroundColor Yellow
    Read-Host "Druecke Enter zum Schliessen"
    exit 1
}

# 2) Capability installieren (idempotent)
Write-Host "[1/4] OpenSSH Server Capability pruefen..." -ForegroundColor Cyan
$cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0'
Write-Host "      Aktueller Status: $($cap.State)"
if ($cap.State -ne 'Installed') {
    Write-Host "      Installiere..." -ForegroundColor Yellow
    Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0' | Out-Null
    Write-Host "      OK." -ForegroundColor Green
} else {
    Write-Host "      Schon installiert." -ForegroundColor Green
}

# 3) sshd-Service starten + auf Automatic setzen
Write-Host "[2/4] sshd-Service konfigurieren..." -ForegroundColor Cyan
$svc = Get-Service sshd -ErrorAction SilentlyContinue
if (-not $svc) {
    Write-Host "      [FEHLER] sshd-Service nicht gefunden trotz Installation." -ForegroundColor Red
    exit 2
}
Set-Service -Name sshd -StartupType Automatic
if ($svc.Status -ne 'Running') {
    Start-Service sshd
}
$svc = Get-Service sshd
Write-Host "      Status: $($svc.Status), StartType: $((Get-Service sshd | Select-Object -ExpandProperty StartType))" -ForegroundColor Green

# Plus ssh-agent (fuer Key-Agent-Forwarding falls spaeter gebraucht)
Set-Service -Name ssh-agent -StartupType Automatic
Start-Service ssh-agent -ErrorAction SilentlyContinue

# 4) Firewall-Regel
Write-Host "[3/4] Firewall-Regel pruefen..." -ForegroundColor Cyan
$rule = Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue
if (-not $rule) {
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' `
        -DisplayName 'OpenSSH Server (sshd)' `
        -Enabled True -Direction Inbound -Protocol TCP `
        -Action Allow -LocalPort 22 | Out-Null
    Write-Host "      Regel angelegt." -ForegroundColor Green
} else {
    Write-Host "      Regel existiert ($($rule.Enabled))." -ForegroundColor Green
}

# 5) Default-Shell auf PowerShell setzen (statt cmd.exe) - angenehmer beim SSH'en
Write-Host "[4/4] Default-Shell auf PowerShell..." -ForegroundColor Cyan
$pwsh = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
New-ItemProperty -Path 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell -Value $pwsh -PropertyType String -Force | Out-Null
Write-Host "      DefaultShell -> $pwsh" -ForegroundColor Green

Write-Host ""
Write-Host "=== Fertig ===" -ForegroundColor Green
Write-Host "sshd laeuft auf Port 22. Naechster Schritt:" -ForegroundColor Cyan
Write-Host "  - Jetson-Public-Key in C:\Users\Rettung\.ssh\authorized_keys" -ForegroundColor White
Write-Host "  - Test vom Jetson: ssh Rettung@desktop-45t6p3p" -ForegroundColor White
Write-Host ""
Write-Host "Du kannst dieses Fenster jetzt schliessen." -ForegroundColor Gray
Start-Sleep -Seconds 3
