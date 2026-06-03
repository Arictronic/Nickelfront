$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Target = Join-Path $RepoRoot 'scripts\nf-server.ps1'
if (-not (Test-Path $Target)) {
    throw "Root launcher not found: $Target"
}
& powershell -NoProfile -ExecutionPolicy Bypass -File $Target @args
exit $LASTEXITCODE
