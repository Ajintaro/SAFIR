# =====================================================================
# SAFIR/SINA - Pubkey eines Remote-Hosts in administrators_authorized_keys
#
# Notwendig wenn der Windows-User Mitglied der lokalen Administrators-
# Gruppe ist. Windows-OpenSSH hat einen Match-Block in sshd_config der
# fuer Admin-Konten ausschliesslich
# C:\ProgramData\ssh\administrators_authorized_keys liest. Die ACL muss
# exakt SYSTEM + Administrators (FullControl) sein, sonst lehnt sshd
# das File ab.
#
# Idempotent: erkennt ob der Key schon eingetragen ist und ueberspringt.
#
# Aufruf (Admin-PowerShell):
#   .\add-jetson-ssh-key.ps1 -PubKey "ssh-ed25519 AAAA... user@host"
#
# Oder per Pipe:
#   ssh jetson@jetson-orin "cat ~/.ssh/id_ed25519.pub" | .\add-jetson-ssh-key.ps1
# =====================================================================

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false, ValueFromPipeline = $true)]
    [string]$PubKey
)

$ErrorActionPreference = 'Stop'

# Falls per Pipe gekommen: stdin lesen
if (-not $PubKey -and -not [Console]::IsInputRedirected) {
    Write-Host "[FEHLER] Kein Pubkey uebergeben." -ForegroundColor Red
    Write-Host "  Aufruf: .\add-jetson-ssh-key.ps1 -PubKey 'ssh-ed25519 AAAA... user@host'" -ForegroundColor Yellow
    exit 1
}
if (-not $PubKey) {
    $PubKey = [Console]::In.ReadToEnd().Trim()
}

# Plausibilitaets-Check
if ($PubKey -notmatch '^(ssh-(rsa|ed25519|dss)|ecdsa-sha2-nistp\d+) [A-Za-z0-9+/=]+( .*)?$') {
    Write-Host "[FEHLER] Pubkey-Format unbekannt:" -ForegroundColor Red
    Write-Host "  '$PubKey'" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "=== Pubkey -> administrators_authorized_keys ===" -ForegroundColor Cyan
Write-Host ""

# Admin-Check
$isAdmin = (New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "[FEHLER] Bitte als Administrator ausfuehren." -ForegroundColor Red
    Read-Host "Druecke Enter zum Schliessen"
    exit 1
}

$authFile = 'C:\ProgramData\ssh\administrators_authorized_keys'
$sshDir   = 'C:\ProgramData\ssh'

if (-not (Test-Path $sshDir)) {
    Write-Host "[FEHLER] $sshDir fehlt - OpenSSH Server nicht installiert?" -ForegroundColor Red
    Write-Host "  Erst scripts\setup-ssh-server.ps1 als Admin ausfuehren." -ForegroundColor Yellow
    Read-Host "Druecke Enter zum Schliessen"
    exit 2
}

# 1) Idempotenter Add (Marker = base64-Anteil, eindeutig je Key)
$keyMarker = ($PubKey -split ' ')[1]
$existing  = if (Test-Path $authFile) { Get-Content $authFile -Raw -ErrorAction SilentlyContinue } else { '' }

Write-Host "[1/2] Pubkey eintragen..." -ForegroundColor Cyan
if ($existing -match [regex]::Escape($keyMarker)) {
    Write-Host "      Key schon enthalten - kein Append." -ForegroundColor Green
} else {
    if ($existing -and -not $existing.EndsWith("`n")) {
        Add-Content -Path $authFile -Value '' -Encoding ASCII
    }
    Add-Content -Path $authFile -Value $PubKey -Encoding ASCII
    Write-Host "      Key angehaengt." -ForegroundColor Green
}

# 2) ACL korrigieren - sshd-Pflicht: NUR SYSTEM + Administrators
Write-Host "[2/2] ACL setzen (SYSTEM + Administrators, sonst nichts)..." -ForegroundColor Cyan
icacls $authFile /inheritance:r | Out-Null
icacls $authFile /grant 'SYSTEM:F' 'BUILTIN\Administrators:F' | Out-Null
Write-Host "      OK." -ForegroundColor Green

Write-Host ""
Write-Host "--- Inhalt $authFile ---" -ForegroundColor Gray
Get-Content $authFile
Write-Host ""
Write-Host "--- ACL $authFile ---" -ForegroundColor Gray
(Get-Acl $authFile).Access | Format-Table -AutoSize IdentityReference, FileSystemRights, AccessControlType

Write-Host ""
Write-Host "=== Fertig - vom Remote-Host aus jetzt:" -ForegroundColor Green
Write-Host "  ssh <username>@<sina-tailnet-name>" -ForegroundColor White
Write-Host ""
Start-Sleep -Seconds 4
