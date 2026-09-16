param(
    [string]$RunId = "v3_discovery",
    [int]$RefreshSeconds = 2,
    [switch]$Once
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$machineConfig = Join-Path $repoRoot "configs\machines\local.yaml"

$runRootLine = Select-String -LiteralPath $machineConfig -Pattern '^\s*run_root\s*:' | Select-Object -First 1
if (-not $runRootLine) {
    throw "run_root was not found in $machineConfig"
}

$runRoot = ($runRootLine.Line -replace '^\s*run_root\s*:\s*', '').Trim().Trim("'", '"')
$statusPath = Join-Path (Join-Path $runRoot $RunId) "STATUS.json"

function Clear-Watcher {
    if (-not $Once) {
        try { [Console]::Clear() } catch {}
    }
}

do {
    try {
        $status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
        $completed = [double]($status.completed ?? 0)
        $expected = [double]($status.expected ?? 0)
        $percent = if ($expected -gt 0) { [math]::Min(100.0, 100.0 * $completed / $expected) } else { 0.0 }

        Clear-Watcher
        Write-Host "Quant Pipeline V3" -ForegroundColor Cyan
        Write-Host "Run:      $RunId"
        Write-Host "Step:     $($status.stage)" -ForegroundColor Yellow
        Write-Host ("Progress: {0:g} / {1:g}" -f $completed, $expected)
        Write-Host ("Percent:  {0:N1}%" -f $percent) -ForegroundColor Green
        Write-Host ""
        Write-Host "Refreshes every $RefreshSeconds seconds. Press Ctrl+C to stop." -ForegroundColor DarkGray
    }
    catch {
        Clear-Watcher
        Write-Host "Waiting for status: $statusPath" -ForegroundColor Yellow
        Write-Host $_.Exception.Message -ForegroundColor Red
    }

    if (-not $Once) {
        Start-Sleep -Seconds $RefreshSeconds
    }
} while (-not $Once)
