param(
    [string]$EnvFile = ".env.portable",
    [int]$Port = 8600,
    [int]$WaitSeconds = 180
)
$ErrorActionPreference = "Stop"
$compose = "deploy/compose.portable.yaml"
if (-not (Test-Path -LiteralPath $EnvFile) -or -not (Test-Path -LiteralPath $compose)) {
    throw "Portable env and Compose files must exist. Copy .env.portable.example to .env.portable first."
}
docker compose --env-file $EnvFile -f $compose config --quiet
if ($LASTEXITCODE -ne 0) { throw "Portable Compose configuration is invalid." }
docker compose --env-file $EnvFile -f $compose up --no-build -d
if ($LASTEXITCODE -ne 0) { throw "Portable services failed to start." }
$deadline = (Get-Date).AddSeconds($WaitSeconds)
do {
    try {
        $ready = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/readyz" -TimeoutSec 3
        if ($ready.status -eq "ready") {
            Start-Process "http://127.0.0.1:$Port/workspace/"
            Write-Output "FINESSE is ready on loopback port $Port."
            exit 0
        }
    } catch { Start-Sleep -Seconds 2 }
} while ((Get-Date) -lt $deadline)
docker compose --env-file $EnvFile -f $compose ps
throw "FINESSE did not become ready within $WaitSeconds seconds."
