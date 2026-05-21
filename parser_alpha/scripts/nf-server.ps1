param(
    [ValidateSet('start', 'stop', 'status', 'restart', 'menu')]
    [string]$Action = 'menu',
    [switch]$IncludeRag,
    [switch]$KillByPorts,

    # 0/-1 means: read from .env or fallback.
    # CLI parameters still override .env when explicitly set.
    [int]$RedisPort = 0,
    [int]$FlowerPort = 0,
    [int]$FrontendPort = 0,
    [int]$CeleryWorkers = -1,
    [int]$QwenWorkers = -1,
    [string]$QwenQueue = '',
    [int]$WorkerConcurrency = 0,
    [int]$QwenWorkerConcurrency = 0,
    [string]$WorkerPool = '',
    [string]$QwenWorkerPool = '',
    [string]$WorkerQueues = ''
)

$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

function Import-DotEnv {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return
    }

    Get-Content $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if (-not $line) { return }
        if ($line.StartsWith('#')) { return }
        if ($line.StartsWith('export ')) {
            $line = $line.Substring(7).Trim()
        }

        $idx = $line.IndexOf('=')
        if ($idx -le 0) { return }

        $key = $line.Substring(0, $idx).Trim()
        $value = $line.Substring($idx + 1).Trim()
        if (-not $key) { return }

        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            if ($value.Length -ge 2) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }

        [Environment]::SetEnvironmentVariable($key, $value, 'Process')
    }
}

function Get-EnvString {
    param(
        [string]$ExplicitValue,
        [string]$Name,
        [string]$DefaultValue
    )

    if ($ExplicitValue -and $ExplicitValue.Trim()) {
        return $ExplicitValue.Trim()
    }

    $value = [Environment]::GetEnvironmentVariable($Name, 'Process')
    if ($value -and $value.Trim()) {
        return $value.Trim()
    }

    return $DefaultValue
}

function Get-EnvInt {
    param(
        [int]$ExplicitValue,
        [string]$Name,
        [int]$DefaultValue,
        [switch]$AllowZero
    )

    if ($AllowZero) {
        if ($ExplicitValue -ge 0) { return $ExplicitValue }
    }
    else {
        if ($ExplicitValue -gt 0) { return $ExplicitValue }
    }

    $raw = [Environment]::GetEnvironmentVariable($Name, 'Process')
    if ($raw -and $raw.Trim()) {
        $parsed = 0
        if ([int]::TryParse($raw.Trim(), [ref]$parsed)) {
            if ($AllowZero) {
                if ($parsed -ge 0) { return $parsed }
            }
            else {
                if ($parsed -gt 0) { return $parsed }
            }
        }
        Write-Host "WARN: invalid integer in .env: $Name=$raw. Fallback: $DefaultValue"
    }

    return $DefaultValue
}

Import-DotEnv -Path (Join-Path $RepoRoot '.env')

$RedisPort = Get-EnvInt -ExplicitValue $RedisPort -Name 'REDIS_PORT' -DefaultValue 6380
$FlowerPort = Get-EnvInt -ExplicitValue $FlowerPort -Name 'FLOWER_PORT' -DefaultValue 5555
$FrontendPort = Get-EnvInt -ExplicitValue $FrontendPort -Name 'VITE_DEV_PORT' -DefaultValue 5173
$FrontendHost = Get-EnvString -ExplicitValue '' -Name 'VITE_DEV_HOST' -DefaultValue '0.0.0.0'
$ApiHost = Get-EnvString -ExplicitValue '' -Name 'API_HOST' -DefaultValue '0.0.0.0'
$ApiPort = Get-EnvInt -ExplicitValue 0 -Name 'API_PORT' -DefaultValue 8001
$QwenServicePort = Get-EnvInt -ExplicitValue 0 -Name 'QWEN_SERVICE_PORT' -DefaultValue 8767
$RagPort = Get-EnvInt -ExplicitValue 0 -Name 'RAG_PORT' -DefaultValue 8000

$CeleryWorkers = Get-EnvInt -ExplicitValue $CeleryWorkers -Name 'CELERY_WORKERS' -DefaultValue 3 -AllowZero
$QwenWorkers = Get-EnvInt -ExplicitValue $QwenWorkers -Name 'QWEN_QUEUE_WORKERS' -DefaultValue 5 -AllowZero
$QwenQueue = Get-EnvString -ExplicitValue $QwenQueue -Name 'QWEN_QUEUE_NAME' -DefaultValue 'qwen'
$WorkerConcurrency = Get-EnvInt -ExplicitValue $WorkerConcurrency -Name 'WORKER_CONCURRENCY' -DefaultValue 1
$QwenWorkerConcurrency = Get-EnvInt -ExplicitValue $QwenWorkerConcurrency -Name 'QWEN_WORKER_CONCURRENCY' -DefaultValue 1
$WorkerPool = Get-EnvString -ExplicitValue $WorkerPool -Name 'WORKER_POOL' -DefaultValue 'solo'
$QwenWorkerPool = Get-EnvString -ExplicitValue $QwenWorkerPool -Name 'QWEN_WORKER_POOL' -DefaultValue $WorkerPool
$WorkerQueues = Get-EnvString -ExplicitValue $WorkerQueues -Name 'WORKER_QUEUES' -DefaultValue 'celery'

Write-Host 'Nickelfront startup configuration from .env / CLI:'
Write-Host "  CELERY_WORKERS=$CeleryWorkers"
Write-Host "  WORKER_CONCURRENCY=$WorkerConcurrency"
Write-Host "  WORKER_POOL=$WorkerPool"
Write-Host "  WORKER_QUEUES=$WorkerQueues"
Write-Host "  QWEN_QUEUE_WORKERS=$QwenWorkers"
Write-Host "  QWEN_QUEUE_NAME=$QwenQueue"
Write-Host "  QWEN_WORKER_CONCURRENCY=$QwenWorkerConcurrency"
Write-Host "  QWEN_WORKER_POOL=$QwenWorkerPool"

$VenvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $VenvPython)) {
    $VenvPython = Join-Path $RepoRoot 'venv\Scripts\python.exe'
}
if (-not (Test-Path $VenvPython)) {
    throw "Python virtual environment not found. Create it from repo root: python -m venv .venv; .venv\Scripts\activate; pip install -r requirements.txt"
}
$FrontendNpm = 'npm'

function Resolve-RedisBinary {
    $cmd = Get-Command redis-server -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $common = @(
        'C:\Program Files\Redis\redis-server.exe',
        'C:\Redis\redis-server.exe'
    )
    foreach ($path in $common) {
        if (Test-Path $path) {
            return $path
        }
    }

    return $null
}

$RedisBinary = Resolve-RedisBinary
$RedisCommand = $null
if ($RedisBinary) {
    $RedisCommand = "`$host.UI.RawUI.WindowTitle='NF_REDIS'; Set-Location '$($RepoRoot.Replace("'", "''"))'; & '$($RedisBinary.Replace("'", "''"))' --port $RedisPort"
}

$Services = @(
    @{
        Tag = 'NF_REDIS'
        WorkDir = $RepoRoot
        Ports = @($RedisPort)
        Command = $RedisCommand
        Optional = $true
    },
    @{
        Tag = 'NF_BACKEND'
        WorkDir = Join-Path $RepoRoot 'backend'
        Ports = @($ApiPort)
        Command = "`$host.UI.RawUI.WindowTitle='NF_BACKEND'; Set-Location '$($RepoRoot.Replace("'", "''"))\backend'; `$env:PYTHONIOENCODING='utf-8'; & '$($VenvPython.Replace("'", "''"))' -m uvicorn app.main:app --host $ApiHost --port $ApiPort --reload"
        Optional = $false
    },
    @{
        Tag = 'NF_FLOWER'
        WorkDir = Join-Path $RepoRoot 'backend'
        Ports = @($FlowerPort)
        Command = "`$host.UI.RawUI.WindowTitle='NF_FLOWER'; Set-Location '$($RepoRoot.Replace("'", "''"))\backend'; `$env:PYTHONIOENCODING='utf-8'; & '$($VenvPython.Replace("'", "''"))' -m celery -A app.tasks.celery_app flower --address=0.0.0.0 --port=$FlowerPort"
        Optional = $false
    },
    @{
        Tag = 'NF_QWEN'
        WorkDir = $RepoRoot
        Ports = @($QwenServicePort)
        Command = "`$host.UI.RawUI.WindowTitle='NF_QWEN'; Set-Location '$($RepoRoot.Replace("'", "''"))'; `$env:PYTHONIOENCODING='utf-8'; & '$($VenvPython.Replace("'", "''"))' qwen_service/service.py"
        Optional = $false
    },
    @{
        Tag = 'NF_FRONTEND'
        WorkDir = Join-Path $RepoRoot 'frontend'
        Ports = @($FrontendPort)
        Command = "`$host.UI.RawUI.WindowTitle='NF_FRONTEND'; Set-Location '$($RepoRoot.Replace("'", "''"))\frontend'; & '$FrontendNpm' run dev -- --host $FrontendHost --port $FrontendPort --strictPort"
        Optional = $false
    }
)

if ($CeleryWorkers -gt 0) {
    for ($i = 1; $i -le $CeleryWorkers; $i++) {
        $script:Services += @{
            Tag = "NF_CELERY_$i"
            WorkDir = Join-Path $RepoRoot 'backend'
            Ports = @()
            Command = "`$host.UI.RawUI.WindowTitle='NF_CELERY_$i'; Set-Location '$($RepoRoot.Replace("'", "''"))\backend'; `$env:PYTHONIOENCODING='utf-8'; & '$($VenvPython.Replace("'", "''"))' -m celery -A app.tasks.celery_app worker --loglevel=info --pool=$WorkerPool --concurrency=$WorkerConcurrency -Q $WorkerQueues -E --without-gossip --without-mingle -n worker-$i@`$env:COMPUTERNAME"
            Optional = $false
        }
    }
}

if ($QwenWorkers -gt 0) {
    for ($i = 1; $i -le $QwenWorkers; $i++) {
        $script:Services += @{
            Tag = "NF_QWEN_GATEWAY_$i"
            WorkDir = Join-Path $RepoRoot 'backend'
            Ports = @()
            Command = "`$host.UI.RawUI.WindowTitle='NF_QWEN_GATEWAY_$i'; Set-Location '$($RepoRoot.Replace("'", "''"))\backend'; `$env:PYTHONIOENCODING='utf-8'; `$env:QWEN_GATEWAY_WORKER='1'; & '$($VenvPython.Replace("'", "''"))' -m celery -A app.tasks.celery_app worker --loglevel=info --pool=$QwenWorkerPool --concurrency=$QwenWorkerConcurrency -Q $QwenQueue -E --without-gossip --without-mingle -n qwen-$i@`$env:COMPUTERNAME"
            Optional = $false
        }
    }
}

function Ensure-RagService {
    if ($Services | Where-Object { $_.Tag -eq 'NF_RAG' }) {
        return
    }

    $script:Services += @{
        Tag = 'NF_RAG'
        WorkDir = Join-Path $RepoRoot 'rag'
        Ports = @($RagPort)
        Command = "`$host.UI.RawUI.WindowTitle='NF_RAG'; Set-Location '$($RepoRoot.Replace("'", "''"))'; `$env:PYTHONIOENCODING='utf-8'; & powershell -NoProfile -ExecutionPolicy Bypass -File '$($PSScriptRoot.Replace("'", "''"))\..\..\scripts\run_rag_venv.ps1' -NoPause"
        Optional = $false
    }
}

if ($IncludeRag) {
    Ensure-RagService
}

function Get-TaggedShells {
    param([string]$Tag)
    Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" |
        Where-Object {
            ($_.CommandLine -like "*WindowTitle='$Tag'*") -or
            ($_.CommandLine -like "*$Tag*")
        }
}

function Get-ChildProcessIds {
    param([int]$ParentPid)

    $all = @()
    $queue = New-Object System.Collections.Generic.Queue[int]
    $queue.Enqueue($ParentPid)

    while ($queue.Count -gt 0) {
        $current = $queue.Dequeue()
        $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $current" | Select-Object -ExpandProperty ProcessId
        foreach ($child in $children) {
            if ($all -notcontains $child) {
                $all += $child
                $queue.Enqueue($child)
            }
        }
    }

    return $all
}

function Stop-Pids {
    param([int[]]$Pids, [string]$Reason)
    foreach ($targetPid in ($Pids | Sort-Object -Descending -Unique)) {
        if ($targetPid -gt 0) {
            Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue
            Write-Host "[$Reason] stopped PID $targetPid"
        }
    }
}

function Show-Status {
    foreach ($svc in $Services) {
        $tag = $svc.Tag
        $shells = Get-TaggedShells -Tag $tag
        if (-not $shells) {
            Write-Host "[$tag] stopped"
            continue
        }

        $pids = @($shells.ProcessId)
        Write-Host "[$tag] running, shell PID(s): $($pids -join ', ')"
    }
}

function Start-Services {
    foreach ($svc in $Services) {
        $tag = $svc.Tag

        if (-not $svc.Command) {
            if ($svc.Optional) {
                Write-Host "[$tag] skipped: command not available (install redis-server or adjust script)"
                continue
            }
            throw "[$tag] Command is empty"
        }

        $existing = Get-TaggedShells -Tag $tag
        if ($existing) {
            Write-Host "[$tag] already running (PID: $(@($existing.ProcessId) -join ', '))"
            continue
        }

        foreach ($port in $svc.Ports) {
            $busy = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
            if ($busy) {
                $owners = ($busy | Select-Object -ExpandProperty OwningProcess -Unique) -join ', '
                Write-Host "[$tag] WARN: port $port already in use by PID(s): $owners"
            }
        }

        $arg = "-NoExit -ExecutionPolicy Bypass -Command $($svc.Command)"
        $proc = Start-Process -FilePath 'powershell.exe' -WorkingDirectory $svc.WorkDir -ArgumentList $arg -PassThru
        Start-Sleep -Milliseconds 250
        Write-Host "[$tag] started, shell PID: $($proc.Id)"
    }
}

function Stop-Services {
    foreach ($svc in $Services) {
        $tag = $svc.Tag
        $shells = Get-TaggedShells -Tag $tag
        if (-not $shells) {
            Write-Host "[$tag] already stopped"
            continue
        }

        foreach ($shell in $shells) {
            $shellPid = [int]$shell.ProcessId
            $children = Get-ChildProcessIds -ParentPid $shellPid
            Stop-Pids -Pids $children -Reason $tag
            Stop-Pids -Pids @($shellPid) -Reason $tag
        }
    }

    if ($KillByPorts) {
        $ports = @($FrontendPort, 8000, 8001, 8767, $FlowerPort, $RedisPort)
        foreach ($port in $ports | Sort-Object -Unique) {
            $listeners = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
            $owners = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
            Stop-Pids -Pids $owners -Reason "PORT:$port"
        }
    }
}

function Invoke-Menu {
    Write-Host ''
    Write-Host 'Nickelfront Server Control'
    Write-Host '1) Start services'
    Write-Host '2) Stop services'
    Write-Host '3) Restart services'
    Write-Host '4) Show status'
    Write-Host '5) Stop services + kill by ports'
    Write-Host '6) Exit'
    $choice = Read-Host 'Choose action [1-6]'

    switch ($choice) {
        '1' {
            $ragChoice = Read-Host 'Include RAG service? [y/N]'
            if ($ragChoice -match '^(y|yes|д|да)$') {
                Ensure-RagService
            }
            Start-Services
            Show-Status
        }
        '2' {
            Stop-Services
            Show-Status
        }
        '3' {
            $ragChoice = Read-Host 'Include RAG service after restart? [y/N]'
            if ($ragChoice -match '^(y|yes|д|да)$') {
                Ensure-RagService
            }
            Stop-Services
            Start-Sleep -Milliseconds 500
            Start-Services
            Show-Status
        }
        '4' {
            Show-Status
        }
        '5' {
            $script:KillByPorts = $true
            Stop-Services
            Show-Status
        }
        default {
            Write-Host 'Exit.'
        }
    }
}

switch ($Action) {
    'start' {
        Start-Services
        Show-Status
    }
    'stop' {
        Stop-Services
        Show-Status
    }
    'restart' {
        Stop-Services
        Start-Sleep -Milliseconds 500
        Start-Services
        Show-Status
    }
    'status' {
        Show-Status
    }
    'menu' {
        Invoke-Menu
    }
}
