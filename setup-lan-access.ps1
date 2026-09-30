# One-time setup so other computers on the office network can open the Supply Chain Portal.
# Run in PowerShell *as Administrator* from the project folder:
#   powershell -ExecutionPolicy Bypass -File .\setup-lan-access.ps1
#
# What it does:
#   1. Marks the current Wi-Fi/Ethernet network as Private (Windows blocks incoming
#      connections on Public networks).
#   2. Allows incoming TCP port 80 (the portal) on Private and Domain networks only.
# Undo: Remove-NetFirewallRule -DisplayName 'Supply Chain Portal (HTTP 80)'

$ErrorActionPreference = 'Stop'
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host 'Please right-click PowerShell, choose "Run as administrator", and run this script again.' -ForegroundColor Yellow
    exit 1
}

$profiles = Get-NetConnectionProfile | Where-Object { $_.IPv4Connectivity -ne 'Disconnected' -and $_.InterfaceAlias -notmatch 'vEthernet|VPN' }
foreach ($profile in $profiles) {
    if ($profile.NetworkCategory -eq 'Public') {
        Set-NetConnectionProfile -InterfaceIndex $profile.InterfaceIndex -NetworkCategory Private
        Write-Host "Network '$($profile.Name)' on $($profile.InterfaceAlias) set to Private."
    } else {
        Write-Host "Network '$($profile.Name)' on $($profile.InterfaceAlias) is already $($profile.NetworkCategory)."
    }
}

$ruleName = 'Supply Chain Portal (HTTP 80)'
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort 80 `
        -Action Allow -Profile Private, Domain | Out-Null
    Write-Host "Firewall rule '$ruleName' added."
} else {
    Write-Host "Firewall rule '$ruleName' already exists."
}

$ip = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias $profiles[0].InterfaceAlias).IPAddress
Write-Host ''
Write-Host "Done. From another computer on this network open:  http://$ip/" -ForegroundColor Green
