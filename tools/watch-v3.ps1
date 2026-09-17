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
$runPath = Join-Path $runRoot $RunId
$statusPath = Join-Path $runPath "STATUS.json"

$pipelineSteps = @(
    "Validate configuration",
    "Snapshot governed source data",
    "Build point-in-time observation panels",
    "Compile feature/target registry",
    "Build features",
    "Build targets",
    "Scan single features",
    "Scan canonical duals at r3",
    "Reuse fused scan for r5",
    "Reuse fused scan for r10/exact duals",
    "Audit exhaustive coverage",
    "Consolidate r3/r5/r10 surfaces",
    "Compute cell-level specialist diagnostics",
    "Compute temporal-fold diagnostics",
    "Reconcile the trial ledger",
    "Build the Parquet/DuckDB analysis bundle",
    "Verify evidence completeness and sealed-data status",
    "Analyze and publish results to GitHub"
)

function Get-PipelineStep([string]$stage) {
    if ($stage -match '^core:validate-config$') { return 1 }
    if ($stage -match '^core:snapshot$') { return 2 }
    if ($stage -match '^core:(build-panel|panel:)') { return 3 }
    if ($stage -match '^core:compile-registry$') { return 4 }
    if ($stage -match '^core:(build-features|feature:)') { return 5 }
    if ($stage -match '^core:(build-targets|targets:)') { return 6 }
    if ($stage -match '^core:(scan-singles|singles:)') { return 7 }
    if ($stage -match '^core:(scan-duals-coarse|duals:)') { return 8 }
    if ($stage -match '^core:scan-duals-fine$') { return 9 }
    if ($stage -match '^core:exact-duals$') { return 10 }
    if ($stage -match '^core:audit-exhaustiveness$') {
        if (-not (Test-Path (Join-Path $runPath 'checkpoints\audit-exhaustiveness.json'))) { return 11 }
        $v3Stages = @(
            @{ Number = 12; Marker = 'resolution_diagnostics.json' },
            @{ Number = 13; Marker = 'cell_specialist.json' },
            @{ Number = 14; Marker = 'cell_temporal.json' },
            @{ Number = 15; Marker = 'trial_ledger.json' },
            @{ Number = 16; Marker = 'analysis_bundle.json' }
        )
        foreach ($item in $v3Stages) {
            if (-not (Test-Path (Join-Path $runPath ("v3_checkpoints\" + $item.Marker)))) {
                return $item.Number
            }
        }
        return 17
    }
    if ($stage -eq 'complete') { return 17 }
    return 1
}

function Clear-Watcher {
    if (-not $Once) {
        try { [Console]::Clear() } catch {}
    }
}

do {
    try {
        $status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
        $completed = if ($null -ne $status.completed) { [double]$status.completed } else { 0.0 }
        $expected = if ($null -ne $status.expected) { [double]$status.expected } else { 0.0 }
        $percent = if ($expected -gt 0) { [math]::Min(100.0, 100.0 * $completed / $expected) } else { 0.0 }
        $stepNumber = Get-PipelineStep ([string]$status.stage)
        $stepName = $pipelineSteps[$stepNumber - 1]

        # Exact core stage-start events carry overall 11-stage counts, not
        # within-stage units. Show zero until useful substage telemetry arrives.
        if ([string]$status.stage -match '^core:(validate-config|snapshot|build-panel|compile-registry|build-features|build-targets|scan-singles|scan-duals-coarse|scan-duals-fine|exact-duals|audit-exhaustiveness)$') {
            $completed = 0.0
            $expected = 1.0
            $percent = 0.0
        }

        if ($stepNumber -ge 12) {
            $completed = 0.0
            $expected = 1.0
            $percent = 0.0
        }

        # Singles publishes one atomic parquet per completed feature block but
        # does not emit an in-stage STATUS counter. Derive exact block progress.
        if ([string]$status.stage -eq 'core:scan-singles') {
            $completed = 0.0
            $expected = 0.0
            $featureRoot = Join-Path $runPath 'cache\features'
            $packedRoot = Join-Path $runPath 'cache\bins\packed'
            $singleRoot = Join-Path $runPath 'single_results'
            if (Test-Path $featureRoot) {
                foreach ($grid in Get-ChildItem -LiteralPath $featureRoot -Directory) {
                    $stems = @(
                        @(Get-ChildItem -LiteralPath $grid.FullName -Filter '*.json' -File -ErrorAction SilentlyContinue).BaseName
                        @(Get-ChildItem -LiteralPath (Join-Path $packedRoot $grid.Name) -Filter '*.json' -File -ErrorAction SilentlyContinue).BaseName
                    ) | Sort-Object -Unique
                    $expected += $stems.Count
                    $completed += @(Get-ChildItem -LiteralPath (Join-Path $singleRoot $grid.Name) -Filter '*.parquet' -File -ErrorAction SilentlyContinue).Count
                }
            }
            $percent = if ($expected -gt 0) { [math]::Min(100.0, 100.0 * $completed / $expected) } else { 0.0 }
        }

        Clear-Watcher
        Write-Host "Quant Pipeline V3" -ForegroundColor Cyan
        Write-Host "Run:      $RunId"
        Write-Host ("Pipeline: {0} / 18 - {1}" -f $stepNumber, $stepName) -ForegroundColor Yellow
        Write-Host "Substep:  $($status.stage)"
        Write-Host ("Progress: {0:g} / {1:g}" -f $completed, $expected)
        Write-Host ("Percent:  {0:N1}% through this step" -f $percent) -ForegroundColor Green
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
