param(
    [Parameter(Mandatory = $true)][string]$Url,
    [int]$TimeoutSeconds = 120,
    [int]$IntervalSeconds = 3,
    [string]$Name = "HTTP service",
    [int[]]$AllowedStatusCodes = @(200, 204)
)

$ErrorActionPreference = "SilentlyContinue"
$deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSeconds))

while ((Get-Date) -lt $deadline) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 4
        if ($AllowedStatusCodes -contains [int]$response.StatusCode) {
            Write-Host "[OK] $Name is healthy: $Url"
            exit 0
        }
    } catch {
        try {
            $status = [int]$_.Exception.Response.StatusCode
            if ($AllowedStatusCodes -contains $status) {
                Write-Host "[OK] $Name is healthy: $Url"
                exit 0
            }
        } catch {}
    }
    Start-Sleep -Seconds ([Math]::Max(1, $IntervalSeconds))
}

Write-Host "[WARN] $Name is not healthy after ${TimeoutSeconds}s: $Url"
exit 1
