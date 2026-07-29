[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$repoRoot = [IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot '..')
)
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
$sourceRoot = Join-Path $repoRoot 'src'
$productModule = Join-Path $sourceRoot 'trip_decider\product_web.py'
$bindAddress = '127.0.0.1'
$port = 8765
$productUrl = "http://${bindAddress}:${port}/"

if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw 'Project .venv Python was not found. Create the project .venv before starting trip-decider.'
}
if (-not (Test-Path -LiteralPath $productModule -PathType Leaf)) {
    throw 'trip_decider.product_web was not found.'
}

$portProbe = [Net.Sockets.TcpListener]::new(
    [Net.IPAddress]::Parse($bindAddress),
    $port
)
$portProbe.Server.ExclusiveAddressUse = $true
$portAvailable = $false
try {
    $portProbe.Start()
    $portAvailable = $true
} catch [Net.Sockets.SocketException] {
    $portAvailable = $false
} finally {
    $portProbe.Stop()
}

if (-not $portAvailable) {
    Write-Host (
        "Port ${bindAddress}:${port} is already in use. " +
        'Close the existing service, then run this script again.'
    ) -ForegroundColor Red
    exit 2
}

$hadPythonPath = Test-Path Env:PYTHONPATH
$previousPythonPath = if ($hadPythonPath) {
    (Get-Item Env:PYTHONPATH).Value
} else {
    $null
}

$serverProcess = $null
$serverExitCode = 1

try {
    $env:PYTHONPATH = $sourceRoot

    $serverProcess = Start-Process `
        -FilePath $pythonExe `
        -ArgumentList @(
            '-m'
            'trip_decider.product_web'
            '--host'
            $bindAddress
            '--port'
            [string]$port
        ) `
        -WorkingDirectory $repoRoot `
        -NoNewWindow `
        -PassThru

    $ready = $false
    $readyDeadline = [DateTime]::UtcNow.AddSeconds(15)
    while ([DateTime]::UtcNow -lt $readyDeadline) {
        $serverProcess.Refresh()
        if ($serverProcess.HasExited) {
            throw "trip-decider exited before becoming ready (exit code $($serverProcess.ExitCode))."
        }

        try {
            $response = Invoke-WebRequest `
                -Uri $productUrl `
                -UseBasicParsing `
                -TimeoutSec 1
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
                $ready = $true
                break
            }
        } catch {
            # Readiness failures are expected while the local server is starting.
        }

        Start-Sleep -Milliseconds 200
    }

    if (-not $ready) {
        throw "trip-decider did not become ready at ${productUrl} within 15 seconds."
    }

    Write-Host "trip-decider is ready: ${productUrl}" -ForegroundColor Green
    Write-Host 'Press Ctrl+C in this window to stop the product.'
    Start-Process -FilePath $productUrl

    while (-not $serverProcess.HasExited) {
        Start-Sleep -Milliseconds 250
        $serverProcess.Refresh()
    }
    $serverExitCode = $serverProcess.ExitCode
} finally {
    if ($null -ne $serverProcess) {
        $serverProcess.Refresh()
        if (-not $serverProcess.HasExited) {
            # Ctrl+C is delivered to the shared console first, allowing the
            # Python server to handle KeyboardInterrupt and close normally.
            if (-not $serverProcess.WaitForExit(1500)) {
                $serverProcess.Kill()
                $serverProcess.WaitForExit()
            }
        }
    }

    if ($hadPythonPath) {
        $env:PYTHONPATH = $previousPythonPath
    } else {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    }
}

if ($serverExitCode -ne 0) {
    exit $serverExitCode
}
