param(
    [string]$TaskName = 'WeiboPeopleMonitorCollector'
)

$ErrorActionPreference = 'Stop'
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "Removed task '$TaskName'."
} else {
    Write-Output "Task '$TaskName' does not exist."
}
