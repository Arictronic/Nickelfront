param(
    [switch]$NoPause
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $Root
$StartedAt = Get-Date

function Write-Step([string]$Message) {
    Write-Host "[STEP] $Message"
}

function Write-Ok([string]$Message) {
    Write-Host "[OK] $Message"
}

function Write-Warn([string]$Message) {
    Write-Host "[WARN] $Message"
}

function Write-Err([string]$Message) {
    Write-Host "[ERROR] $Message"
}

function Set-DefaultEnv([string]$Name, [string]$Value) {
    $current = [Environment]::GetEnvironmentVariable($Name, 'Process')
    if ([string]::IsNullOrWhiteSpace($current)) {
        [Environment]::SetEnvironmentVariable($Name, $Value, 'Process')
    }
}

function Read-DotEnvValue([string]$Value) {
    $v = $Value.Trim()
    if (($v.StartsWith('"') -and $v.EndsWith('"')) -or ($v.StartsWith("'") -and $v.EndsWith("'"))) {
        $v = $v.Substring(1, $v.Length - 2)
    }
    return $v
}

function Import-DotEnv([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Warn ".env not found: $Path. Defaults will be used."
        return
    }

    Get-Content -LiteralPath $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if ([string]::IsNullOrWhiteSpace($line)) { return }
        if ($line.StartsWith('#')) { return }
        $idx = $line.IndexOf('=')
        if ($idx -le 0) { return }

        $key = $line.Substring(0, $idx).Trim()
        $value = Read-DotEnvValue $line.Substring($idx + 1)
        if ($key -match '^[A-Za-z_][A-Za-z0-9_]*$') {
            [Environment]::SetEnvironmentVariable($key, $value, 'Process')
        }
    }
}

function Get-Env([string]$Name) {
    return [Environment]::GetEnvironmentVariable($Name, 'Process')
}

function Is-On([string]$Name) {
    $v = (Get-Env $Name)
    return -not ($v -match '^(0|false|no|off)$')
}

function Wait-Tcp([string]$HostName, [int]$Port, [int]$TimeoutSeconds, [string]$Name) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $client = [Net.Sockets.TcpClient]::new()
        try {
            $iar = $client.BeginConnect($HostName, $Port, $null, $null)
            if ($iar.AsyncWaitHandle.WaitOne(1000, $false) -and $client.Connected) {
                $client.EndConnect($iar)
                return $true
            }
        } catch {
        } finally {
            $client.Close()
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)

    Write-Warn "$Name is not reachable at $HostName`:$Port after ${TimeoutSeconds}s."
    return $false
}

function Wait-Http([string]$Url, [int]$TimeoutSeconds, [string]$Name) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -Uri $Url -Method GET -UseBasicParsing -TimeoutSec 3
            if ([int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 500) {
                return $true
            }
        } catch {
        }
        Start-Sleep -Milliseconds 700
    } while ((Get-Date) -lt $deadline)

    Write-Warn "$Name is not healthy at $Url after ${TimeoutSeconds}s."
    return $false
}

function Start-CmdWindow([string]$Title, [string]$ScriptPath, [string[]]$Arguments = @()) {
    if (-not (Test-Path -LiteralPath $ScriptPath)) {
        Write-Warn "$Title was not started because script was not found: $ScriptPath"
        return
    }

    $quotedScript = '"' + $ScriptPath + '"'
    $argText = if ($Arguments.Count -gt 0) {
        ' ' + (($Arguments | ForEach-Object { '"' + ($_ -replace '"','\"') + '"' }) -join ' ')
    } else {
        ''
    }

    $cmdLine = 'call ' + $quotedScript + $argText
    Start-Process -FilePath 'cmd.exe' -ArgumentList @('/k', $cmdLine) -WorkingDirectory $Root -WindowStyle Normal | Out-Null
}

Import-DotEnv (Join-Path $Root '.env')

# Defaults. Empty values from .env are treated as missing.
Set-DefaultEnv 'START_REDIS' '1'
Set-DefaultEnv 'START_QWEN_SERVICE' '1'
Set-DefaultEnv 'START_BACKEND' '1'
Set-DefaultEnv 'START_FRONTEND' '1'
Set-DefaultEnv 'START_QWEN_WORKERS' '1'
Set-DefaultEnv 'START_CONTENT_WORKERS' '1'
Set-DefaultEnv 'START_WORKERS' '1'
Set-DefaultEnv 'START_FLOWER' '1'

Set-DefaultEnv 'REDIS_HOST' 'localhost'
Set-DefaultEnv 'REDIS_PORT' '6380'
Set-DefaultEnv 'API_HOST' '0.0.0.0'
Set-DefaultEnv 'API_PORT' '8001'
Set-DefaultEnv 'QWEN_SERVICE_HOST' '127.0.0.1'
Set-DefaultEnv 'QWEN_SERVICE_PORT' '8767'
Set-DefaultEnv 'FRONTEND_PORT' '5173'
Set-DefaultEnv 'VITE_PORT' (Get-Env 'FRONTEND_PORT')
Set-DefaultEnv 'FLOWER_PORT' '5555'

Set-DefaultEnv 'REDIS_WAIT_SECONDS' '45'
Set-DefaultEnv 'BACKEND_WAIT_SECONDS' '180'
Set-DefaultEnv 'QWEN_WAIT_SECONDS' '90'
Set-DefaultEnv 'DEFER_HEAVY_SERVICES_SECONDS' '0'
Set-DefaultEnv 'REQUIRE_QWEN_FOR_QWEN_WORKERS' '0'

Set-DefaultEnv 'CELERY_WORKERS' '1'
Set-DefaultEnv 'WORKER_CONCURRENCY' '5'
Set-DefaultEnv 'WORKER_POOL' 'threads'
Set-DefaultEnv 'WORKER_QUEUES' 'celery'
Set-DefaultEnv 'QWEN_QUEUE_WORKERS' '1'
Set-DefaultEnv 'QWEN_QUEUE_NAME' 'qwen'
Set-DefaultEnv 'QWEN_WORKER_CONCURRENCY' '5'
Set-DefaultEnv 'QWEN_WORKER_POOL' 'threads'
Set-DefaultEnv 'CONTENT_WORKERS' '1'
Set-DefaultEnv 'CONTENT_QUEUE_NAME' 'content'
Set-DefaultEnv 'CONTENT_WORKER_CONCURRENCY' '5'
Set-DefaultEnv 'CONTENT_WORKER_POOL' 'threads'

$redisHost = Get-Env 'REDIS_HOST'
$redisPort = [int](Get-Env 'REDIS_PORT')
$apiPort = [int](Get-Env 'API_PORT')
$apiHost = Get-Env 'API_HOST'
$apiHealthHost = if ($apiHost -and $apiHost -ne '0.0.0.0' -and $apiHost -ne '::') { $apiHost } else { '127.0.0.1' }
$apiHealthUrl = "http://$apiHealthHost`:$apiPort/health"
$qwenHost = Get-Env 'QWEN_SERVICE_HOST'
$qwenPort = [int](Get-Env 'QWEN_SERVICE_PORT')
$qwenHealthUrl = "http://$qwenHost`:$qwenPort/health"
$frontendPort = Get-Env 'FRONTEND_PORT'

Write-Host ''
Write-Host '============================================================'
Write-Host 'Nickelfront local startup'
Write-Host ('Started at:   ' + $StartedAt.ToString('dd.MM.yyyy HH:mm:ss,ff'))
Write-Host 'Mode:         PowerShell orchestrator, parallel core startup'
Write-Host '============================================================'
Write-Host "Redis:        $(Get-Env 'START_REDIS')  $redisHost`:$redisPort"
Write-Host "Qwen service: $(Get-Env 'START_QWEN_SERVICE')  $qwenHost`:$qwenPort"
Write-Host "Backend:      $(Get-Env 'START_BACKEND')  $apiHealthUrl"
Write-Host "Frontend:     $(Get-Env 'START_FRONTEND')  port=$frontendPort"
Write-Host "Workers:      qwen=$(Get-Env 'START_QWEN_WORKERS'), content=$(Get-Env 'START_CONTENT_WORKERS'), regular=$(Get-Env 'START_WORKERS'), flower=$(Get-Env 'START_FLOWER')"
Write-Host '============================================================'
Write-Host ''

Write-Step 'Starting Redis, Qwen service and Backend in parallel...'

if (Is-On 'START_REDIS') {
    if (Wait-Tcp $redisHost $redisPort 2 'Redis') {
        Write-Ok 'Redis is already running.'
    } else {
        Start-CmdWindow 'Redis' (Join-Path $Root 'scripts\run_redis.bat')
    }
}

if (Is-On 'START_QWEN_SERVICE') {
    if (Wait-Tcp $qwenHost $qwenPort 2 'Qwen service') {
        Write-Ok 'Qwen service is already running.'
    } else {
        Start-CmdWindow 'Qwen Service' (Join-Path $Root 'scripts\run_qwen_service.bat')
    }
}

if (Is-On 'START_BACKEND') {
    if (Wait-Http $apiHealthUrl 2 'Backend API') {
        Write-Ok 'Backend API is already healthy.'
    } else {
        Start-CmdWindow 'Backend' (Join-Path $Root 'scripts\run_backend.bat')
    }
}

Write-Step 'Waiting for required core services...'

if (Is-On 'START_REDIS') {
    if (-not (Wait-Tcp $redisHost $redisPort ([int](Get-Env 'REDIS_WAIT_SECONDS')) 'Redis')) {
        Write-Err 'Redis did not become ready. Startup stopped before frontend/workers.'
        exit 1
    }
    Write-Ok 'Redis is ready.'
}

if (Is-On 'START_BACKEND') {
    if (-not (Wait-Http $apiHealthUrl ([int](Get-Env 'BACKEND_WAIT_SECONDS')) 'Backend API')) {
        Write-Err 'Backend API is not healthy. Startup stopped before frontend/workers.'
        exit 1
    }
    Write-Ok 'Backend API is healthy.'
}

$qwenReady = $false
if (Is-On 'START_QWEN_SERVICE') {
    $qwenReady = Wait-Tcp $qwenHost $qwenPort ([int](Get-Env 'QWEN_WAIT_SECONDS')) 'Qwen service'
    if ($qwenReady) { Write-Ok 'Qwen service is ready.' } else { Write-Warn 'Qwen service is not ready; backend can still work.' }
}

if (Is-On 'START_FRONTEND') {
    Write-Step 'Starting frontend...'
    Start-CmdWindow 'Frontend' (Join-Path $Root 'scripts\run_frontend.bat')
}

$delay = [int](Get-Env 'DEFER_HEAVY_SERVICES_SECONDS')
if ($delay -gt 0) {
    Write-Step "Waiting ${delay}s before workers..."
    Start-Sleep -Seconds $delay
}

if ((Get-Env 'REQUIRE_QWEN_FOR_QWEN_WORKERS') -match '^(1|true|yes|on)$' -and -not $qwenReady) {
    [Environment]::SetEnvironmentVariable('START_QWEN_WORKERS', '0', 'Process')
    Write-Warn 'Qwen workers are disabled because Qwen service is not ready and REQUIRE_QWEN_FOR_QWEN_WORKERS=1.'
}

if (Is-On 'START_QWEN_WORKERS') {
    Write-Step 'Starting Qwen gateway workers...'
    $count = [int](Get-Env 'QWEN_QUEUE_WORKERS')
    for ($i = 1; $i -le $count; $i++) {
        Start-CmdWindow "Qwen Gateway $i" (Join-Path $Root 'scripts\run_qwen_worker.bat') @("$i", (Get-Env 'QWEN_QUEUE_NAME'), (Get-Env 'QWEN_WORKER_POOL'), (Get-Env 'QWEN_WORKER_CONCURRENCY'))
    }
}

if (Is-On 'START_CONTENT_WORKERS') {
    Write-Step 'Starting content workers...'
    $count = [int](Get-Env 'CONTENT_WORKERS')
    for ($i = 1; $i -le $count; $i++) {
        Start-CmdWindow "Content Worker $i" (Join-Path $Root 'scripts\run_worker.bat') @("content-$i", (Get-Env 'CONTENT_WORKER_CONCURRENCY'), (Get-Env 'CONTENT_WORKER_POOL'), (Get-Env 'CONTENT_QUEUE_NAME'))
    }
}

if (Is-On 'START_WORKERS') {
    Write-Step 'Starting regular workers...'
    $count = [int](Get-Env 'CELERY_WORKERS')
    for ($i = 1; $i -le $count; $i++) {
        Start-CmdWindow "Worker $i" (Join-Path $Root 'scripts\run_worker.bat') @("$i", (Get-Env 'WORKER_CONCURRENCY'), (Get-Env 'WORKER_POOL'), (Get-Env 'WORKER_QUEUES'))
    }
}

if (Is-On 'START_FLOWER') {
    Write-Step 'Starting Flower...'
    Start-CmdWindow 'Flower' (Join-Path $Root 'scripts\run_flower.bat')
}

$FinishedAt = Get-Date
Write-Host ''
Write-Host '============================================================'
Write-Host 'Nickelfront startup commands were issued.'
Write-Host ('Started at:   ' + $StartedAt.ToString('dd.MM.yyyy HH:mm:ss,ff'))
Write-Host ('Finished at:  ' + $FinishedAt.ToString('dd.MM.yyyy HH:mm:ss,ff'))
Write-Host "Open frontend: http://127.0.0.1:$frontendPort"
Write-Host "Backend docs:  http://127.0.0.1:$apiPort/docs"
Write-Host '============================================================'
Write-Host ''

exit 0
