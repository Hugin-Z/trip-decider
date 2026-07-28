$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Wu1BootstrapProblem {
    $problem = [ordered]@{
        error_code = 'ENTRY_RUNTIME_IDENTITY_ERROR'
        artifact_path = '.venv'
        json_pointer = ''
        schema_rule = 'runtimeBootstrap'
        expected = 'project .venv Python'
        actual_type = 'path'
        message = 'The runtime is not the project virtual environment.'
    }
    [Console]::Error.WriteLine(($problem | ConvertTo-Json -Compress))
}

function Invoke-Wu1PythonTransport {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonExe,

        [Parameter(Mandatory = $true)]
        [string]$PythonCode,

        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $tempPythonPath = [System.IO.Path]::Combine(
        [System.IO.Path]::GetTempPath(),
        ("trip-decider-wu1-{0}.py" -f [Guid]::NewGuid().ToString("N"))
    )
    $repoFullPath = [System.IO.Path]::GetFullPath($RepoRoot)
    $tempFullPath = [System.IO.Path]::GetFullPath($tempPythonPath)
    if ($tempFullPath.StartsWith(
        $repoFullPath + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        Write-Wu1BootstrapProblem
        return 5
    }

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    $pythonExitCode = 5
    try {
        [System.IO.File]::WriteAllText(
            $tempPythonPath,
            $PythonCode,
            $utf8NoBom
        )
        try {
            $startInfo = New-Object System.Diagnostics.ProcessStartInfo
            $startInfo.FileName = $PythonExe
            $startInfo.Arguments = '"{0}"' -f $tempPythonPath
            $startInfo.WorkingDirectory = $repoFullPath
            $startInfo.UseShellExecute = $false
            $startInfo.CreateNoWindow = $true
            $startInfo.RedirectStandardOutput = $true
            $startInfo.RedirectStandardError = $true
            $startInfo.EnvironmentVariables['PYTHONPATH'] = (
                [System.IO.Path]::Combine($repoFullPath, 'src')
            )

            $process = New-Object System.Diagnostics.Process
            $process.StartInfo = $startInfo
            [void]$process.Start()
            $pythonStdout = $process.StandardOutput.ReadToEnd()
            $pythonStderr = $process.StandardError.ReadToEnd()
            $process.WaitForExit()
            $pythonExitCode = $process.ExitCode
            [Console]::Out.Write($pythonStdout)
            [Console]::Error.Write($pythonStderr)
            $process.Dispose()
        }
        catch {
            Write-Wu1BootstrapProblem
            $pythonExitCode = 5
        }
    }
    finally {
        if (Test-Path -LiteralPath $tempPythonPath) {
            Remove-Item -LiteralPath $tempPythonPath -Force
        }
    }
    return $pythonExitCode
}

function Invoke-Wu1Verification {
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
        Write-Wu1BootstrapProblem
        return 5
    }

    $pythonCode = @'
from trip_decider.verification_entry import main

raise SystemExit(main())
'@

    Push-Location $repoRoot
    try {
        return Invoke-Wu1PythonTransport `
            -PythonExe $pythonExe `
            -PythonCode $pythonCode `
            -RepoRoot $repoRoot
    }
    finally {
        Pop-Location
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    exit (Invoke-Wu1Verification)
}
