# Creates (or updates) the "GTM Talent Engine - follow-ups" task in the Windows
# Task Scheduler: every weekday at 09:00. If the PC is off at that time, it runs
# as soon as it is turned on (StartWhenAvailable). Nothing is sent: the script
# only creates and closes tasks in Attio.
param([string]$At = "09:00")

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$dir\run_hidden.vbs`"" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "GTM Talent Engine - follow-ups" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "Done: 'GTM Talent Engine - follow-ups' runs every weekday at $At."
Write-Host "Run it now: Start-ScheduledTask -TaskName 'GTM Talent Engine - follow-ups'"
Write-Host "Remove it:  Unregister-ScheduledTask -TaskName 'GTM Talent Engine - follow-ups' -Confirm:`$false"
