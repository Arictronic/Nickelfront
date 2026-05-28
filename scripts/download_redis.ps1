param(
    [Parameter(Mandatory = $true)][string]$ProjectRoot,
    [string]$Url = "https://github.com/tporadowski/redis/releases/download/v5.0.14.1/Redis-x64-5.0.14.1.zip"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath $ProjectRoot).Path
$redisDir = Join-Path $root "redis"
$redisExe = Join-Path $redisDir "redis-server.exe"

if (Test-Path -LiteralPath $redisExe) {
    Write-Host "[OK] Redis already exists: $redisExe"
    exit 0
}

if (-not (Test-Path -LiteralPath $redisDir)) {
    New-Item -ItemType Directory -Path $redisDir -Force | Out-Null
}

$tmpZip = Join-Path $env:TEMP ("nickelfront_redis_" + [guid]::NewGuid().ToString("N") + ".zip")
try {
    Write-Host "[INFO] Downloading portable Redis..."
    Write-Host "[INFO] URL: $Url"
    Invoke-WebRequest -Uri $Url -OutFile $tmpZip -UseBasicParsing
    Expand-Archive -LiteralPath $tmpZip -DestinationPath $redisDir -Force
} finally {
    if (Test-Path -LiteralPath $tmpZip) {
        Remove-Item -LiteralPath $tmpZip -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path -LiteralPath $redisExe)) {
    throw "Redis download/extract finished, but redis-server.exe was not found at $redisExe"
}

Write-Host "[OK] Redis installed: $redisExe"
exit 0
