param(
    [ValidateSet('start', 'stop', 'status', 'restart', 'menu')]
    [string]$Action = 'menu',
    [switch]$IncludeRag,
    [switch]$KillByPorts,
    [int]$RedisPort = 6380,
    [int]$FlowerPort = 5555
)

$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$VenvPython = Join-Path $RepoRoot 'venv\Scripts\python.exe'
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
        Ports = @(8001)
        Command = "`$host.UI.RawUI.WindowTitle='NF_BACKEND'; Set-Location '$($RepoRoot.Replace("'", "''"))\\backend'; `$env:PYTHONIOENCODING='utf-8'; & '$($VenvPython.Replace("'", "''"))' -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload"
        Optional = $false
    },
    @{
        Tag = 'NF_CELERY'
        WorkDir = Join-Path $RepoRoot 'backend'
        Ports = @()
        Command = "`$host.UI.RawUI.WindowTitle='NF_CELERY'; Set-Location '$($RepoRoot.Replace("'", "''"))\\backend'; `$env:PYTHONIOENCODING='utf-8'; & '$($VenvPython.Replace("'", "''"))' -m celery -A app.tasks.celery_app worker --loglevel=info --pool=solo"
        Optional = $false
    },
    @{
        Tag = 'NF_FLOWER'
        WorkDir = Join-Path $RepoRoot 'backend'
        Ports = @($FlowerPort)
        Command = "`$host.UI.RawUI.WindowTitle='NF_FLOWER'; Set-Location '$($RepoRoot.Replace("'", "''"))\\backend'; `$env:PYTHONIOENCODING='utf-8'; & '$($VenvPython.Replace("'", "''"))' -m celery -A app.tasks.celery_app flower --address=0.0.0.0 --port=$FlowerPort"
        Optional = $false
    },
    @{
        Tag = 'NF_QWEN'
        WorkDir = $RepoRoot
        Ports = @(8767)
        Command = "`$host.UI.RawUI.WindowTitle='NF_QWEN'; Set-Location '$($RepoRoot.Replace("'", "''"))'; `$env:PYTHONIOENCODING='utf-8'; & '$($VenvPython.Replace("'", "''"))' qwen_service/service.py"
        Optional = $false
    },
    @{
        Tag = 'NF_FRONTEND'
        WorkDir = Join-Path $RepoRoot 'frontend'
        Ports = @(80)
        Command = "`$host.UI.RawUI.WindowTitle='NF_FRONTEND'; Set-Location '$($RepoRoot.Replace("'", "''"))\\frontend'; & '$FrontendNpm' run dev -- --host 0.0.0.0 --port 80 --strictPort"
        Optional = $false
    }
)

function Ensure-RagService {
    if ($Services | Where-Object { $_.Tag -eq 'NF_RAG' }) {
        return
    }

    $script:Services += @{
        Tag = 'NF_RAG'
        WorkDir = Join-Path $RepoRoot 'rag'
        Ports = @(8000)
        Command = "`$host.UI.RawUI.WindowTitle='NF_RAG'; Set-Location '$($RepoRoot.Replace("'", "''"))\\rag'; `$env:PYTHONIOENCODING='utf-8'; & '$($VenvPython.Replace("'", "''"))' -m app.main"
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
        $ports = @(80, 8000, 8001, 8767, $FlowerPort, $RedisPort)
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
