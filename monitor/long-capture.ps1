[CmdletBinding()]
param(
    [double]$Hours = 4
)

$ErrorActionPreference = "Stop"
if ($Hours -le 0) {
    throw "Hours must be greater than zero."
}

$MonitorDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $MonitorDirectory "run.ps1"

& $Runner `
    -MaxRuntimeMinutes ($Hours * 60) `
    -SilenceSeconds 30 `
    -StatusSeconds 60 `
    -QuietAdvertisements `
    -KeepAwake

exit $LASTEXITCODE
