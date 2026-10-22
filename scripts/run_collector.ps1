param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$logDirectory = Join-Path $projectRoot 'logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$logPath = Join-Path $logDirectory ('collector-' + (Get-Date -Format 'yyyy-MM-dd') + '.log')

$pythonPath = $env:WEIBO_MONITOR_PYTHON
if (-not $pythonPath) {
    $venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython) {
        $pythonPath = $venvPython
    } else {
        $pythonCommand = Get-Command python.exe -ErrorAction Stop
        $pythonPath = $pythonCommand.Source
    }
}
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python executable not found: $pythonPath"
}

$createdNew = $false
$mutex = New-Object System.Threading.Mutex($true, 'Local\WeiboPeopleMonitorCollector', [ref]$createdNew)
if (-not $createdNew) {
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value ((Get-Date -Format o) + ' skipped: previous collection still running')
    exit 0
}

Push-Location $projectRoot
try {
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value ((Get-Date -Format o) + ' start')
    $arguments = @('android_collector.py', '--quiet')
    if ($DryRun) {
        $arguments += '--dry-run'
    }
    $collectorOutput = & $pythonPath @arguments 2>&1
    $collectorExitCode = $LASTEXITCODE
    $collectorOutput | Out-File -LiteralPath $logPath -Append -Encoding utf8
    if ($collectorExitCode -ne 0) {
        throw "Collector exited with code $collectorExitCode"
    }
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value ((Get-Date -Format o) + ' success')
} catch {
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value ((Get-Date -Format o) + ' error: ' + $_.Exception.Message)
    throw
} finally {
    Pop-Location
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
