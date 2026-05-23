@echo off

chcp 65001 >nul

setlocal

title Nickelfront Qwen parallel chat test

echo ==========================================
echo Nickelfront Qwen parallel chat test
echo Single-file BAT: no temp .ps1, no extra files, no self-restart
echo Window will stay open after finish/error
echo ==========================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $p='%~f0'; $s=Get-Content -LiteralPath $p -Raw -Encoding UTF8; $m='### POWERSHELL_TEST_START ###'; $i=$s.LastIndexOf($m); if($i -lt 0){throw 'Embedded PowerShell block not found'}; $code=$s.Substring($i + $m.Length); Invoke-Expression $code"
set "EXITCODE=%ERRORLEVEL%"

echo.
echo ==========================================
echo BAT finished with exit code %EXITCODE%.
echo Window stayed in current console. You can close it manually.
echo ==========================================
echo.

pause
endlocal
exit /b %EXITCODE%

### POWERSHELL_TEST_START ###
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

try {
    $utf8 = New-Object System.Text.UTF8Encoding -ArgumentList $false
    [Console]::InputEncoding = $utf8
    [Console]::OutputEncoding = $utf8
    $OutputEncoding = $utf8
} catch {
    # Encoding setup is best-effort for old consoles.
}

$BackendUrl = 'http://127.0.0.1:8001'
$email = 'admin@admin.com'
$password = 'admin'
$ChatCount = 5

function Short-Text {
    param(
        [AllowNull()][object]$Value,
        [int]$MaxLength = 160
    )

    if ($null -eq $Value) { return '' }
    $text = [string]$Value
    $text = $text -replace "`r", ' ' -replace "`n", ' '
    if ($text.Length -le $MaxLength) { return $text }
    return $text.Substring(0, $MaxLength) + '...'
}

function Get-RequestErrorText {
    param([object]$ErrorRecord)

    $parts = @()

    if ($ErrorRecord.ErrorDetails -and $ErrorRecord.ErrorDetails.Message) {
        $parts += [string]$ErrorRecord.ErrorDetails.Message
    }

    if ($ErrorRecord.Exception -and $ErrorRecord.Exception.Message) {
        $parts += [string]$ErrorRecord.Exception.Message
    }

    try {
        $response = $ErrorRecord.Exception.Response
        if ($response -and $response.GetResponseStream()) {
            $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
            $body = $reader.ReadToEnd()
            if ($body) { $parts += $body }
        }
    } catch {
        # Some exception types do not expose a readable response body.
    }

    $text = ($parts | Where-Object { $_ } | Select-Object -First 1)
    return (Short-Text $text 300)
}

Write-Host ''
Write-Host '=== Nickelfront Qwen parallel test ===' -ForegroundColor Cyan
Write-Host ('Backend: ' + $BackendUrl)
Write-Host ('Login: ' + $email)
Write-Host ('Chats: ' + $ChatCount)
Write-Host 'Mode: 5 separate Qwen chats, each prompt asks for one short token.'
Write-Host ''

try {
    Write-Host 'Checking backend /docs...' -ForegroundColor Yellow
    $null = Invoke-RestMethod -Uri ($BackendUrl + '/docs') -Method Get -TimeoutSec 10
    Write-Host 'Backend /docs OK' -ForegroundColor Green
} catch {
    Write-Host ''
    Write-Host 'BACKEND ERROR:' -ForegroundColor Red
    Write-Host (Get-RequestErrorText $_) -ForegroundColor Red
    Write-Host ''
    exit 1
}

Write-Host ''
Write-Host 'Logging in...' -ForegroundColor Yellow
$loginBodyObj = @{ email = $email; password = $password }
$loginBody = ConvertTo-Json -InputObject $loginBodyObj -Depth 5

try {
    $login = Invoke-RestMethod -Uri ($BackendUrl + '/api/v1/auth/login') -Method Post -ContentType 'application/json' -Body $loginBody -TimeoutSec 30
} catch {
    Write-Host ''
    Write-Host 'LOGIN ERROR:' -ForegroundColor Red
    Write-Host (Get-RequestErrorText $_) -ForegroundColor Red
    Write-Host ''
    exit 1
}

$token = $login.access_token
if (-not $token) {
    Write-Host 'No access_token in login response' -ForegroundColor Red
    exit 1
}

Write-Host 'Login OK' -ForegroundColor Green

Write-Host ''
Write-Host 'Checking Qwen health...' -ForegroundColor Yellow
try {
    $health = Invoke-RestMethod -Uri ($BackendUrl + '/api/v1/qwen/health') -Method Get -TimeoutSec 20
    Write-Host ('Qwen health: status={0}; available={1}; model={2}' -f $health.status, $health.available, $health.model)
    if (-not $health.available) {
        Write-Host 'Qwen health says unavailable. The chat test will still run to show real endpoint behavior.' -ForegroundColor Yellow
    }
} catch {
    Write-Host 'Qwen health check failed. The chat test will still run to show real endpoint behavior.' -ForegroundColor Yellow
    Write-Host (Get-RequestErrorText $_) -ForegroundColor Yellow
}

Write-Host ''
Write-Host ('Starting ' + $ChatCount + ' parallel Qwen chat requests...') -ForegroundColor Yellow
Write-Host ''

$globalStart = Get-Date
$jobs = @()

foreach ($i in 1..$ChatCount) {
    Write-Host ('Starting job ' + $i)

    $jobs += Start-Job -ScriptBlock {
        param($i, $token, $globalStart, $BackendUrl)

        try {
            $utf8 = New-Object System.Text.UTF8Encoding -ArgumentList $false
            [Console]::InputEncoding = $utf8
            [Console]::OutputEncoding = $utf8
            $OutputEncoding = $utf8
        } catch {
            # Best-effort inside background PowerShell job.
        }

        function Decode-Text {
            param([AllowNull()][object]$Value)
            if ($null -eq $Value) { return '' }
            $text = [string]$Value
            if ($text -match 'Ð|Ñ') {
                try {
                    $bytes = [System.Text.Encoding]::GetEncoding(1252).GetBytes($text)
                    $fixed = [System.Text.Encoding]::UTF8.GetString($bytes)
                    if ($fixed) { return $fixed }
                } catch { }
            }
            return $text
        }

        function Get-JobErrorText {
            param([object]$ErrorRecord)

            $text = ''
            if ($ErrorRecord.ErrorDetails -and $ErrorRecord.ErrorDetails.Message) {
                $text = [string]$ErrorRecord.ErrorDetails.Message
            } elseif ($ErrorRecord.Exception -and $ErrorRecord.Exception.Message) {
                $text = [string]$ErrorRecord.Exception.Message
            }

            $text = Decode-Text $text
            $text = $text -replace "`r", ' ' -replace "`n", ' '
            if ($text.Length -gt 300) {
                $text = $text.Substring(0, 300) + '...'
            }
            return $text
        }

        $headers = @{
            Authorization = ('Bearer ' + $token)
            'Content-Type' = 'application/json'
        }

        $bodyObject = @{
            message = ('Parallel test chat #' + $i + '. Answer with exactly one short token: OK' + $i)
            thinking_enabled = $false
            search_enabled = $false
            auto_continue = $false
        }

        $body = ConvertTo-Json -InputObject $bodyObject -Depth 5
        $start = Get-Date

        try {
            $result = Invoke-RestMethod -Uri ($BackendUrl + '/api/v1/qwen/messages') -Method Post -Headers $headers -Body $body -TimeoutSec 420
            $end = Get-Date

            $responseText = ''
            if ($result.response) {
                $responseText = [string]$result.response
                if ($responseText.Length -gt 120) {
                    $responseText = $responseText.Substring(0, 120) + '...'
                }
            }

            $errorText = ''
            if ($result.error) {
                $errorText = Decode-Text $result.error
                if ($errorText.Length -gt 160) {
                    $errorText = $errorText.Substring(0, 160) + '...'
                }
            }

            [PSCustomObject]@{
                chat = $i
                started_at_sec = [Math]::Round(($start - $globalStart).TotalSeconds, 2)
                finished_at_sec = [Math]::Round(($end - $globalStart).TotalSeconds, 2)
                duration_sec = [Math]::Round(($end - $start).TotalSeconds, 2)
                session_id = [string]$result.session_id
                error = $errorText
                response_start = $responseText
            }
        } catch {
            $end = Get-Date
            [PSCustomObject]@{
                chat = $i
                started_at_sec = [Math]::Round(($start - $globalStart).TotalSeconds, 2)
                finished_at_sec = [Math]::Round(($end - $globalStart).TotalSeconds, 2)
                duration_sec = [Math]::Round(($end - $start).TotalSeconds, 2)
                session_id = ''
                error = (Get-JobErrorText $_)
                response_start = ''
            }
        }
    } -ArgumentList $i, $token, $globalStart, $BackendUrl
}

Write-Host ''
Write-Host 'Waiting for jobs...' -ForegroundColor Yellow
Write-Host ''

$results = @()
foreach ($job in $jobs) {
    try {
        $one = Receive-Job -Job $job -Wait
        if ($one) { $results += $one }
    } finally {
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    }
}

$results = $results | Sort-Object chat

Write-Host ''
Write-Host '=== RESULTS ===' -ForegroundColor Cyan
if ($results.Count -gt 0) {
    $results |
        Select-Object chat, started_at_sec, finished_at_sec, duration_sec, session_id, error, response_start |
        Format-Table -AutoSize
} else {
    Write-Host 'No results returned from jobs.' -ForegroundColor Red
}

Write-Host ''
Write-Host '=== PARALLEL CHECK ===' -ForegroundColor Cyan
if ($results.Count -gt 0) {
    $errors = @($results | Where-Object { $_.error })
    $ok = @($results | Where-Object { -not $_.error })

    $startedAll = $results | Measure-Object -Property started_at_sec -Minimum -Maximum
    $startSpreadAll = [Math]::Round($startedAll.Maximum - $startedAll.Minimum, 2)
    Write-Host ('Start spread all jobs: {0} sec' -f $startSpreadAll)
    Write-Host ('Successful rows:       {0}/{1}' -f $ok.Count, $results.Count)

    if ($ok.Count -gt 1) {
        $finished = $ok | Measure-Object -Property finished_at_sec -Minimum -Maximum
        $duration = $ok | Measure-Object -Property duration_sec -Minimum -Maximum
        $finishSpread = [Math]::Round($finished.Maximum - $finished.Minimum, 2)
        $durationSpread = [Math]::Round($duration.Maximum - $duration.Minimum, 2)

        Write-Host ('Finish spread OK rows: {0} sec' -f $finishSpread)
        Write-Host ('Duration spread OK:    {0} sec' -f $durationSpread)
    }

    if ($errors.Count -eq $results.Count) {
        Write-Host 'Result: all requests ended with errors. This checks endpoint failure, not real Qwen generation parallelism.' -ForegroundColor Red
    } elseif ($errors.Count -gt 0) {
        Write-Host 'Result: generation was partly parallel, but at least one request failed. Fix the first error before judging final parallel capacity.' -ForegroundColor Red
    } elseif ($ok.Count -gt 1 -and $finishSpread -le 8 -and $durationSpread -le 8) {
        Write-Host 'Result: successful Qwen generations look parallel.' -ForegroundColor Green
    } else {
        Write-Host 'Result: possible queue/serialization ladder among successful rows. Check Qwen worker count, queue settings, and backend endpoint path.' -ForegroundColor Yellow
    }
}

Write-Host ''
Write-Host 'How to read:' -ForegroundColor Cyan
Write-Host 'GOOD: started_at_sec almost equal, finished_at_sec almost equal.'
Write-Host 'GOOD: duration_sec values are close to each other.'
Write-Host 'BAD: finished_at_sec looks like ladder: 20, 40, 60, 80, 100.'
Write-Host 'BAD: all rows have Qwen unavailable/error, because then generation was not tested.'
Write-Host ''

if ($results.Count -eq 0) { exit 2 }
if (@($results | Where-Object { $_.error }).Count -gt 0) { exit 3 }
exit 0
