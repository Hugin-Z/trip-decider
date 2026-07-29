[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$City,

    [string]$CityAdcode,

    [Parameter(Mandatory = $true)]
    [string]$StartAt,

    [Parameter(Mandatory = $true)]
    [string]$EndAt,

    [Parameter(Mandatory = $true)]
    [string]$InputRecordedAt,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, [int]::MaxValue)]
    [int]$PartyCount,

    [Parameter(Mandatory = $true)]
    [string[]]$TransportMode,

    [Parameter(Mandatory = $true)]
    [string[]]$MustVisit,

    [string[]]$Excluded = @(),

    [switch]$Interactive,

    [string]$Locale = 'zh-CN',

    [string]$NormalizedReplayRoot,

    [Parameter(Mandatory = $true)]
    [string]$OutputRoot
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
$hadPythonPath = Test-Path Env:PYTHONPATH
$previousPythonPath = if ($hadPythonPath) {
    (Get-Item Env:PYTHONPATH).Value
} else {
    $null
}
$exitCode = 5

try {
    if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
        throw 'Project .venv Python is missing.'
    }

    $env:PYTHONPATH = Join-Path $repoRoot 'src'

    # WU7 Stage A deliberately stops here.  Credential access and any live
    # transport belong to a separately approved Stage B after provider policy
    # confirmation.
    [Console]::Error.WriteLine(
        'AMAP_DURABLE_STORAGE_CONFIRMATION_MISSING'
    )
} finally {
    if ($hadPythonPath) {
        $env:PYTHONPATH = $previousPythonPath
    } else {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    }
}

exit $exitCode
