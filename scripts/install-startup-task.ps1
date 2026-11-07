# Run on Windows as the same user that paired the connector. No admin password needed.
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $env:LOCALAPPDATA 'OfficeTally\connector.json'
if (-not (Test-Path $configPath)) {
    throw 'Run scripts\start-windows.cmd and complete pairing first.'
}
$pythonLauncher = (Get-Command py.exe -ErrorAction Stop).Source
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $pythonLauncher -Argument '-m connector.launcher' -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'Upkar Agency Tally Connector' -Description 'Sync the local Tally company through the outbound office connector.' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Write-Host 'Connector startup task installed for your current Windows user.'
Write-Host 'It starts at sign-in. Keep Tally with Upkar Agency open for syncing.'
