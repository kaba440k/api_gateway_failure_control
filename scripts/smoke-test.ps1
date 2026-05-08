$ErrorActionPreference = "Stop"

$Gateway = if ($env:GATEWAY_URL) { $env:GATEWAY_URL } else { "http://localhost:10000" }

function Invoke-Json {
    param(
        [Parameter(Mandatory = $true)][string]$Method,
        [Parameter(Mandatory = $true)][string]$Path,
        [object]$Body = $null
    )

    $params = @{
        Method = $Method
        Uri = "$Gateway$Path"
        TimeoutSec = 10
    }

    if ($null -ne $Body) {
        $params.ContentType = "application/json"
        $params.Body = ($Body | ConvertTo-Json -Depth 10)
    }

    Invoke-RestMethod @params
}

Write-Host "Reset circuit breaker and disable fault injection"
Invoke-Json -Method Post -Path "/control/circuit/reset" | Out-Null
Invoke-Json -Method Post -Path "/control/faults/unstable-service" -Body @{
    enabled = $false
    error_rate = 0
    latency_ms = 0
} | Out-Null

Write-Host "Protected call without failure"
$normal = Invoke-Json -Method Get -Path "/protected/unstable"
if (-not $normal.ok) {
    throw "Expected successful protected call"
}

Write-Host "Enable unstable-service failure"
Invoke-Json -Method Post -Path "/control/faults/unstable-service" -Body @{
    enabled = $true
    error_rate = 1
    latency_ms = 150
} | Out-Null

Write-Host "Trigger failures until circuit breaker opens"
$last = $null
for ($i = 0; $i -lt 4; $i++) {
    $last = Invoke-Json -Method Get -Path "/protected/unstable"
    Start-Sleep -Milliseconds 300
}

if ($last.breaker_state -ne "OPEN") {
    throw "Expected OPEN breaker state, got $($last.breaker_state)"
}

Write-Host "Restore normal state"
Invoke-Json -Method Post -Path "/control/faults/unstable-service" -Body @{
    enabled = $false
    error_rate = 0
    latency_ms = 0
} | Out-Null
Invoke-Json -Method Post -Path "/control/circuit/reset" | Out-Null

Write-Host "Smoke test passed"
