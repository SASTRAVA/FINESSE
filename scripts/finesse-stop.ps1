param(
    [string]$EnvFile = ".env.portable",
    [string]$DataDir = "portable-runtime/data",
    [string]$VaultDir = "portable-runtime/vault",
    [int]$WaitSeconds = 300
)
$ErrorActionPreference = "Stop"
python scripts/portable_safe_stop.py --env-file $EnvFile --data-dir $DataDir --vault-dir $VaultDir --wait-seconds $WaitSeconds
if ($LASTEXITCODE -ne 0) { throw "Portable safe stop did not complete; keep the drive connected." }
