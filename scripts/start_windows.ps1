# Build (if needed) and start the FinAlly container. Safe to run repeatedly.
param([switch]$Build)

$ErrorActionPreference = 'Stop'

$Image     = 'finally:latest'
$Container = 'finally'
$Volume    = 'finally-data'
$Port      = 8000

function Invoke-DockerQuiet {
    # In Windows PowerShell 5.1 a native command's stderr becomes a terminating
    # NativeCommandError while $ErrorActionPreference is 'Stop'. These probes are
    # expected to fail sometimes, so relax it for the call and read $LASTEXITCODE.
    $ErrorActionPreference = 'Continue'
    docker @args 2>$null | Out-Null
}

Set-Location (Join-Path $PSScriptRoot '..')

Invoke-DockerQuiet image inspect $Image
if ($Build -or $LASTEXITCODE -ne 0) {
    Write-Host "Building $Image ..."
    docker build -t $Image .
    if ($LASTEXITCODE -ne 0) { throw 'Docker build failed.' }
}

if (docker ps -q -f "name=^$Container$") {
    Write-Host "Already running at http://localhost:$Port"
    exit 0
}

# Remove a stopped container of the same name so the run below is idempotent.
Invoke-DockerQuiet rm $Container

$envArgs = @()
if (Test-Path .env) {
    $envArgs = @('--env-file', '.env')
} else {
    Write-Host 'No .env found; starting with defaults (simulator prices, chat needs a key).'
}

docker run -d --name $Container -v "${Volume}:/app/db" -p "${Port}:8000" @envArgs $Image | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Failed to start container.' }

Write-Host "FinAlly is starting at http://localhost:$Port"
Start-Process "http://localhost:$Port"
