param(
    [Parameter(Mandatory = $true)][string]$HostName,
    [Parameter(Mandatory = $true)][int]$Port,
    [int]$TimeoutSeconds = 60,
    [int]$IntervalSeconds = 2,
    [string]$Name = "TCP service"
)

$ErrorActionPreference = "SilentlyContinue"
$deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSeconds))

while ((Get-Date) -lt $deadline) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect($HostName, $Port, $null, $null)
        if ($iar.AsyncWaitHandle.WaitOne(1200, $false) -and $client.Connected) {
            $client.Close()
            Write-Host "[OK] $Name is reachable at ${HostName}:${Port}"
            exit 0
        }
    } catch {
    } finally {
        $client.Close()
    }
    Start-Sleep -Seconds ([Math]::Max(1, $IntervalSeconds))
}

Write-Host "[WARN] $Name is not reachable at ${HostName}:${Port} after ${TimeoutSeconds}s"
exit 1
