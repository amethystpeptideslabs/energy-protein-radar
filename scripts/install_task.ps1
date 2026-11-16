<#
  Registers the DealRadarSync scheduled task for the current user:
    - daily at 8:05 AM and at log on
    - StartWhenAvailable (catches up if the PC was off/asleep at 8:05)
    - 10-minute limit, runs only while you're logged on (no stored password)
#>
param([string]$RepoDir = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$script = Join-Path $RepoDir 'scripts\sync_vault.ps1'
if (-not (Test-Path $script)) { throw "Not found: $script" }
$user = "$env:USERDOMAIN\$env:USERNAME"

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""
$triggers = @(
  (New-ScheduledTaskTrigger -Daily -At '8:05AM'),
  (New-ScheduledTaskTrigger -AtLogOn -User $user)
)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName 'DealRadarSync' -Description 'Pulls Deal Radar notes from GitHub and copies them into the Obsidian vault (Deal-Radar folder).' `
  -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Registered scheduled task DealRadarSync (daily 8:05 AM + at log on) for $user"
