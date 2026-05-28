param(
    [Parameter(Mandatory = $true)]
    [string]$EnvFile,
    [Parameter(Mandatory = $true)]
    [string]$OutputCmdFile
)

$ErrorActionPreference = "Stop"

function Add-Value([System.Collections.Specialized.OrderedDictionary]$Map, [string]$Key, [string]$Value, [bool]$Overwrite = $true) {
    if (-not ($Key -match '^[A-Za-z_][A-Za-z0-9_]*$')) { return }
    if ($Overwrite -or -not $Map.Contains($Key)) {
        $Map[$Key] = $Value
    }
}

function Strip-OuterQuotes([string]$Value) {
    $v = $Value.Trim()
    if ($v.Length -ge 2) {
        if (($v.StartsWith('"') -and $v.EndsWith('"')) -or ($v.StartsWith("'") -and $v.EndsWith("'"))) {
            return $v.Substring(1, $v.Length - 2)
        }
    }
    return $v
}

function Escape-CmdSetValue([string]$Value) {
    if ($null -eq $Value) { return "" }
    $v = [string]$Value
    $v = $v.Replace('^', '^^')
    $v = $v.Replace('%', '%%')
    $v = $v.Replace('!', '^!')
    $v = $v.Replace('&', '^&')
    $v = $v.Replace('|', '^|')
    $v = $v.Replace('<', '^<')
    $v = $v.Replace('>', '^>')
    $v = $v.Replace('"', '^"')
    return $v
}

if (-not (Test-Path -LiteralPath $EnvFile)) {
    [System.IO.File]::WriteAllLines($OutputCmdFile, @('exit /b 0'), [System.Text.UTF8Encoding]::new($false))
    exit 0
}

$values = [ordered]@{}

foreach ($rawLine in Get-Content -LiteralPath $EnvFile -Encoding UTF8) {
    $line = [string]$rawLine
    $trimmed = $line.Trim()
    if (-not $trimmed) { continue }
    if ($trimmed.StartsWith('#')) { continue }

    if ($trimmed.StartsWith('export ')) {
        $trimmed = $trimmed.Substring(7).Trim()
    }

    $idx = $trimmed.IndexOf('=')
    if ($idx -lt 1) { continue }

    $key = $trimmed.Substring(0, $idx).Trim().Trim([char]0xFEFF).Trim()
    if (-not ($key -match '^[A-Za-z_][A-Za-z0-9_]*$')) { continue }

    $value = $trimmed.Substring($idx + 1).Trim()
    if ($value -match '\s+#') {
        $value = ($value -split '\s+#', 2)[0].Trim()
    }
    $value = Strip-OuterQuotes $value
    Add-Value $values $key $value $true
}

try {
    if ($values.Contains('DATABASE_URL') -and $values['DATABASE_URL']) {
        $dbUrl = [string]$values['DATABASE_URL']
        if ($dbUrl.StartsWith('postgresql+')) {
            $dbUrl = 'postgresql://' + $dbUrl.Split('://', 2)[1]
        }
        $u = [Uri]$dbUrl
        if ($u.Host) { Add-Value $values 'POSTGRES_HOST' $u.Host $false }
        if ($u.Port -gt 0) { Add-Value $values 'POSTGRES_PORT' ([string]$u.Port) $false }
        $dbName = $u.AbsolutePath.Trim('/')
        if ($dbName) { Add-Value $values 'POSTGRES_DB' ([Uri]::UnescapeDataString($dbName)) $false }
        if ($u.UserInfo) {
            $parts = $u.UserInfo.Split(':', 2)
            if ($parts.Count -ge 1 -and $parts[0]) { Add-Value $values 'POSTGRES_USER' ([Uri]::UnescapeDataString($parts[0])) $false }
            if ($parts.Count -ge 2 -and $parts[1]) { Add-Value $values 'POSTGRES_PASSWORD' ([Uri]::UnescapeDataString($parts[1])) $false }
        }
    }
} catch {}

try {
    $redisSource = $null
    if ($values.Contains('REDIS_URL') -and $values['REDIS_URL']) {
        $redisSource = [string]$values['REDIS_URL']
    } elseif ($values.Contains('CELERY_BROKER_URL') -and $values['CELERY_BROKER_URL']) {
        $redisSource = [string]$values['CELERY_BROKER_URL']
        Add-Value $values 'REDIS_URL' $redisSource $false
    }
    if ($redisSource) {
        $u = [Uri]$redisSource
        if ($u.Host) { Add-Value $values 'REDIS_HOST' $u.Host $false }
        if ($u.Port -gt 0) { Add-Value $values 'REDIS_PORT' ([string]$u.Port) $false }
    }
} catch {}

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add('@echo off')
foreach ($entry in $values.GetEnumerator()) {
    $escaped = Escape-CmdSetValue ([string]$entry.Value)
    $lines.Add(('set "{0}={1}"' -f $entry.Key, $escaped))
}
$lines.Add('exit /b 0')

$outDir = Split-Path -Parent $OutputCmdFile
if ($outDir -and (-not (Test-Path -LiteralPath $outDir))) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}
[System.IO.File]::WriteAllLines($OutputCmdFile, $lines, [System.Text.UTF8Encoding]::new($false))
