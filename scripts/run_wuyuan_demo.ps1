[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,

    [switch]$OpenReport
)

$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot '..')
)
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
$anchorRoot = Join-Path $repoRoot 'fixtures\jiangxi_multi_identity_smoke'
$planningInputRoot = Join-Path $repoRoot 'examples\wuyuan-two-day'

if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw 'Project .venv Python is required.'
}

$hadPythonPath = Test-Path Env:PYTHONPATH
$previousPythonPath = if ($hadPythonPath) {
    (Get-Item Env:PYTHONPATH).Value
} else {
    $null
}
$childExitCode = 1
$checkedOutputRoot = $null

try {
    $env:PYTHONPATH = Join-Path $repoRoot 'src'
    $checkedOutputRoot = [IO.Path]::GetFullPath($OutputRoot)
    $outputParent = [IO.Path]::GetDirectoryName($checkedOutputRoot)
    if (Test-Path -LiteralPath $checkedOutputRoot) {
        throw 'OutputRoot must not exist.'
    }
    if (
        [string]::IsNullOrWhiteSpace($outputParent) -or
        -not (Test-Path -LiteralPath $outputParent -PathType Container)
    ) {
        throw 'OutputRoot parent must be an existing directory.'
    }

    & $pythonExe @(
        '-m'
        'trip_decider.e2e_demo'
        '--anchor-root'
        $anchorRoot
        '--planning-input-root'
        $planningInputRoot
        '--output-root'
        $checkedOutputRoot
    )
    $childExitCode = $LASTEXITCODE
} finally {
    if ($hadPythonPath) {
        $env:PYTHONPATH = $previousPythonPath
    } else {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    }
}

if ($childExitCode -ne 0) {
    exit $childExitCode
}

$reportPath = Join-Path $checkedOutputRoot 'report\index.html'
if ($OpenReport) {
    if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
        throw 'E2E succeeded without the expected HTML report.'
    }
    Start-Process -FilePath $reportPath
}
