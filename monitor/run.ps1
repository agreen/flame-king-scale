[CmdletBinding()]
param(
    [switch]$ProbeOnFirstSeen,
    [double]$ProbeEveryMinutes = 0,
    [int]$NotifySeconds = 15,
    [double]$MaxRuntimeMinutes = 0,
    [double]$SilenceSeconds = 10,
    [double]$StatusSeconds = 60,
    [string]$Name = "Gas Monitor",
    [string]$LogDirectory = "",
    [switch]$QuietAdvertisements,
    [switch]$KeepAwake
)

$ErrorActionPreference = "Stop"
$MonitorDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$VirtualEnvironment = Join-Path $MonitorDirectory ".venv"
$Python = Join-Path $VirtualEnvironment "Scripts\python.exe"
$Requirements = Join-Path $MonitorDirectory "requirements.txt"
$Monitor = Join-Path $MonitorDirectory "flame_king_monitor.py"

if (-not (Test-Path -LiteralPath $Python)) {
    Write-Host "Creating the monitor's private Python environment..."
    py -3 -m venv $VirtualEnvironment
}

& $Python -c "import bleak" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing the Bluetooth dependency..."
    & $Python -m pip install --disable-pip-version-check -r $Requirements
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install the Bluetooth dependency."
    }
}

$MonitorArgs = @(
    $Monitor,
    "--notify-seconds", $NotifySeconds,
    "--probe-every-minutes", $ProbeEveryMinutes,
    "--max-runtime-minutes", $MaxRuntimeMinutes,
    "--silence-seconds", $SilenceSeconds,
    "--status-seconds", $StatusSeconds,
    "--name", $Name
)

if ($ProbeOnFirstSeen) {
    $MonitorArgs += "--probe-on-first-seen"
}
if ($QuietAdvertisements) {
    $MonitorArgs += "--quiet-advertisements"
}
if ($KeepAwake) {
    $MonitorArgs += "--keep-awake"
}
if ($LogDirectory) {
    $MonitorArgs += @("--log-dir", $LogDirectory)
}

& $Python @MonitorArgs
exit $LASTEXITCODE
