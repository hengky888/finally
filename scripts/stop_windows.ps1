# Stop and remove the FinAlly container. The data volume is left intact.
$ErrorActionPreference = 'Stop'

$Container = 'finally'

function Invoke-DockerQuiet {
    # See start_windows.ps1: native stderr is terminating under 'Stop' in PS 5.1.
    $ErrorActionPreference = 'Continue'
    docker @args 2>$null | Out-Null
}

if (-not (docker ps -aq -f "name=^$Container$")) {
    Write-Host 'Not running.'
    exit 0
}

Invoke-DockerQuiet stop $Container
Invoke-DockerQuiet rm $Container

Write-Host "Stopped. Data volume 'finally-data' kept."
