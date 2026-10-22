param(
    [ValidateRange(1, 60)]
    [int]$IntervalMinutes = 5,
    [string]$TaskName = 'WeiboPeopleMonitorCollector'
)

$ErrorActionPreference = 'Stop'
$runner = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'run_collector.ps1')).Path
$powerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
$actionArgs = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $runner + '"'
$action = New-ScheduledTaskAction -Execute $powerShell -Argument $actionArgs

# Align the first run to the next interval boundary measured from midnight.
# With the default 5-minute interval this produces :00, :05, :10 ... :55.
$now = Get-Date
$minutesSinceMidnight = ($now - $now.Date).TotalMinutes
$nextSlot = ([Math]::Floor($minutesSinceMidnight / $IntervalMinutes) + 1) * $IntervalMinutes
$firstRun = $now.Date.AddMinutes($nextSlot)
$trigger = New-ScheduledTaskTrigger -Once -At $firstRun `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3)

$task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Description 'Read-only MuMu UI snapshot collector for the Weibo people dashboard.'
Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
Write-Output "Installed task '$TaskName' every $IntervalMinutes minute(s), first run $($firstRun.ToString('yyyy-MM-dd HH:mm:ss')). It runs only while this user is logged on."
