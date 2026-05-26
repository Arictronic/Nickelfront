param(
    [Parameter(Mandatory = $true)]
    [string]$EnvFile,
    [Parameter(Mandatory = $true)]
    [string]$OutputCmdFile
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $EnvFile)) {
    exit 0
}

$lines = New-Object System.Collections.Generic.List[string]

foreach ($rawLine in Get-Content -LiteralPath $EnvFile -Encoding UTF8) {
    $line = [string]$rawLine
    $trimmed = $line.Trim()
    if (-not $trimmed) { continue }
    if ($trimmed.StartsWith("#")) { continue }

    $idx = $trimmed.IndexOf("=")
    if ($idx -lt 1) { continue }

    $key = $trimmed.Substring(0, $idx).Trim()
    # Remove UTF-8 BOM if .env starts with it before the first key/comment.
    $key = $key.Trim([char]0xFEFF).Trim()
    if (-not ($key -match '^[A-Za-z_][A-Za-z0-9_]*$')) { continue }

    $value = $trimmed.Substring($idx + 1)

    if ($value -match "\s+#") {
        $value = ($value -split "\s+#", 2)[0]
    }

    $value = $value.Trim()

    if (
        ($value.Length -ge 2) -and
        (
            (($value.StartsWith("'")) -and ($value.EndsWith("'"))) -or
            (($value.StartsWith('"')) -and ($value.EndsWith('"')))
        )
    ) {
        $value = $value.Substring(1, $value.Length - 2).Trim()
    }

    # The generated file is executed by cmd.exe. Double quotes keep &, |, <, > safe
    # inside SET syntax; percent signs must also be doubled to avoid expansion when
    # the temporary .cmd is CALLed.
    $escapedValue = $value.Replace('%', '%%').Replace('"', '""')
    $lines.Add(('set "{0}={1}"' -f $key, $escapedValue))
}

# Always return control to the caller even if this temporary .cmd is CALLed from
# another batch file.
$lines.Add('exit /b 0')

$outDir = Split-Path -Parent $OutputCmdFile
if ($outDir -and (-not (Test-Path -LiteralPath $outDir))) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

[System.IO.File]::WriteAllLines($OutputCmdFile, $lines, [System.Text.UTF8Encoding]::new($false))
