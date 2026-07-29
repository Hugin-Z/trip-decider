[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
$powerShellExe = Join-Path $PSHOME 'powershell.exe'
$startHead = '3d3336b96453150b952a2b83fb49c34fe0e94368'
$runToken = [Guid]::NewGuid().ToString('N')
$temporaryArtifacts = New-Object 'System.Collections.Generic.List[string]'
$runtimeHash = '34E7A01CD0FBA5EC50F24BFF872226F5D9E4E9021B646F3019AC93443FDB04C1'
$testHash = '443905617A067838C9BED34B63308F8F23403A373425E4FE53BEA523840A0962'

function Assert-True {
    param(
        [Parameter(Mandatory = $true)]
        [bool]$Condition,

        [Parameter(Mandatory = $true)]
        [string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

function Invoke-CapturedProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )
    $token = [Guid]::NewGuid().ToString('N')
    $tempRoot = [IO.Path]::GetTempPath()
    $stdoutPath = Join-Path $tempRoot "trip-decider-wu7-$token.stdout"
    $stderrPath = Join-Path $tempRoot "trip-decider-wu7-$token.stderr"
    $temporaryArtifacts.Add($stdoutPath)
    $temporaryArtifacts.Add($stderrPath)
    try {
        $process = Start-Process `
            -FilePath $FilePath `
            -ArgumentList $Arguments `
            -WorkingDirectory $repoRoot `
            -NoNewWindow `
            -Wait `
            -PassThru `
            -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath
        $stdout = if (Test-Path -LiteralPath $stdoutPath) {
            [IO.File]::ReadAllText($stdoutPath, [Text.Encoding]::UTF8)
        } else {
            ''
        }
        $stderr = if (Test-Path -LiteralPath $stderrPath) {
            [IO.File]::ReadAllText($stderrPath, [Text.Encoding]::UTF8)
        } else {
            ''
        }
        [Console]::Out.Write($stdout)
        [Console]::Error.Write($stderr)
        return [PSCustomObject]@{
            ExitCode = $process.ExitCode
            Stdout = $stdout
            Stderr = $stderr
            Combined = $stdout + $stderr
            Label = $Label
        }
    } finally {
        foreach ($path in @($stdoutPath, $stderrPath)) {
            if (Test-Path -LiteralPath $path) {
                Remove-Item -LiteralPath $path -Force
            }
        }
    }
}

function Invoke-ProjectPython {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )
    $hadPythonPath = Test-Path Env:PYTHONPATH
    $previousPythonPath = if ($hadPythonPath) {
        (Get-Item Env:PYTHONPATH).Value
    } else {
        $null
    }
    try {
        $env:PYTHONPATH = Join-Path $repoRoot 'src'
        return Invoke-CapturedProcess `
            -FilePath $pythonExe `
            -Arguments $Arguments `
            -Label $Label
    } finally {
        if ($hadPythonPath) {
            $env:PYTHONPATH = $previousPythonPath
        } else {
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        }
    }
}

function Invoke-TemporaryPython {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Code,

        [Parameter(Mandatory = $true)]
        [string]$Label,

        [string[]]$ScriptArguments = @()
    )
    $scriptPath = Join-Path (
        [IO.Path]::GetTempPath()
    ) "trip-decider-wu7-$runToken-$([Guid]::NewGuid().ToString('N')).py"
    $temporaryArtifacts.Add($scriptPath)
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    try {
        [IO.File]::WriteAllText($scriptPath, $Code, $utf8NoBom)
        return Invoke-ProjectPython `
            -Arguments (@($scriptPath) + $ScriptArguments) `
            -Label $Label
    } finally {
        if (Test-Path -LiteralPath $scriptPath) {
            Remove-Item -LiteralPath $scriptPath -Force
        }
    }
}

function Assert-Environment {
    Assert-True `
        (Test-Path -LiteralPath $pythonExe -PathType Leaf) `
        'Project .venv Python is missing'
    $code = @'
import importlib.metadata
import json
import re
import site
import sys
from pathlib import Path

repo = Path.cwd().resolve()
venv = (repo / ".venv").resolve()
assert Path(sys.executable).resolve() == (venv / "Scripts" / "python.exe").resolve()
assert Path(sys.prefix).resolve() == venv
site_paths = tuple(Path(value).resolve() for value in site.getsitepackages())
assert site_paths
assert all(venv == path or venv in path.parents for path in site_paths)

def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()

expected = {}
for line in (repo / "requirements.lock").read_text(encoding="utf-8").splitlines():
    assert line and line.count("==") == 1
    name, version = line.split("==", 1)
    expected[normalized(name)] = version
actual = {}
for distribution in importlib.metadata.distributions():
    name = distribution.metadata["Name"]
    if not name:
        continue
    key = normalized(name)
    if key not in {"pip", "setuptools"}:
        actual[key] = distribution.version
assert actual == expected
print(json.dumps({"lock_packages": len(expected), "project_venv": True}, sort_keys=True))
'@
    $result = Invoke-TemporaryPython `
        -Code $code `
        -Label 'WU7 project venv and exact lock'
    Assert-True ($result.ExitCode -eq 0) 'Venv or lock validation failed'
    $pipCheck = Invoke-CapturedProcess `
        -FilePath $pythonExe `
        -Arguments @('-m', 'pip', 'check') `
        -Label 'WU7 pip check'
    Assert-True ($pipCheck.ExitCode -eq 0) 'pip check failed'
}

function Assert-ScopeAndHistory {
    Assert-True `
        ((& git -C $repoRoot branch --show-current).Trim() -eq 'main') `
        'Branch is not main'
    Assert-True (@(& git -C $repoRoot remote).Count -eq 0) 'Git remotes exist'
    Assert-True (@(& git -C $repoRoot stash list).Count -eq 0) 'Git stashes exist'

    $allowed = @(
        'plans/work-unit-7-live-place-resolution.md',
        'src/trip_decider/live_place_resolution.py',
        'tests/test_wu7_live_place_resolution.py',
        'scripts/run_live_place_resolution.ps1',
        'scripts/verify_wu7_live_place_resolution.ps1',
        'docs/reviews/work-unit-7-live-place-resolution-review.md'
    )
    $observed = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($path in @(& git -C $repoRoot diff --name-only "$startHead..HEAD")) {
        if (-not [string]::IsNullOrWhiteSpace($path)) {
            [void]$observed.Add($path.Replace('\', '/'))
        }
    }
    foreach ($path in @(& git -C $repoRoot diff --name-only)) {
        if (-not [string]::IsNullOrWhiteSpace($path)) {
            [void]$observed.Add($path.Replace('\', '/'))
        }
    }
    foreach ($path in @(& git -C $repoRoot ls-files --others --exclude-standard)) {
        if (-not [string]::IsNullOrWhiteSpace($path)) {
            [void]$observed.Add($path.Replace('\', '/'))
        }
    }
    foreach ($path in $observed) {
        Assert-True ($allowed -contains $path) "Path outside WU7 scope: $path"
    }
    Assert-True `
        ($observed.Count -eq 5 -or $observed.Count -eq 6) `
        'WU7 path count is not in the C4-C5 window'

    $expectedMessages = @(
        'docs: record WU7 live place resolution plan',
        'chore: add live place resolution interface',
        'test: add failing live place resolution cases',
        'feat: implement structured live place resolution',
        'chore: add live place resolution run and verification entries',
        'docs: prepare WU7 live place resolution review'
    )
    $actualMessages = @(
        & git -C $repoRoot log --reverse --format='%s' "$startHead..HEAD"
    )
    Assert-True `
        ($actualMessages.Count -ge 4 -and $actualMessages.Count -le 6) `
        'WU7 commit count is outside the C4-C5 window'
    for ($index = 0; $index -lt $actualMessages.Count; $index++) {
        Assert-True `
            ($actualMessages[$index] -eq $expectedMessages[$index]) `
            "WU7 commit message mismatch at index $index"
    }
    if ($actualMessages.Count -eq 6) {
        Assert-True ($observed.Count -eq 6) 'Final WU7 scope is not six paths'
    }

    $planHash = (
        Get-FileHash `
            -LiteralPath (Join-Path $repoRoot 'plans\work-unit-7-live-place-resolution.md') `
            -Algorithm SHA256
    ).Hash
    Assert-True `
        ($planHash -eq 'CADA19D6BE716842AE6893A6793E31B0DB90B652903CBCE1388DEEF6073A815D') `
        'Approved Plan hash changed'
    Assert-True `
        ((Get-FileHash `
            -LiteralPath (Join-Path $repoRoot 'src\trip_decider\live_place_resolution.py') `
            -Algorithm SHA256).Hash -eq $runtimeHash) `
        'WU7 runtime hash changed after C3'
    Assert-True `
        ((Get-FileHash `
            -LiteralPath (Join-Path $repoRoot 'tests\test_wu7_live_place_resolution.py') `
            -Algorithm SHA256).Hash -eq $testHash) `
        'WU7 test hash changed after C2'

    $protectedChanges = @(
        & git -C $repoRoot diff --name-only $startHead |
            Where-Object { $allowed -notcontains $_.Replace('\', '/') }
    )
    Assert-True ($protectedChanges.Count -eq 0) 'Protected tracked input changed'
    Assert-True `
        (@(Get-ChildItem `
            -LiteralPath (Join-Path $repoRoot 'schemas') `
            -Filter '*.schema.json' `
            -File).Count -eq 11) `
        'Schema count changed'
    $diffCheck = Invoke-CapturedProcess `
        -FilePath 'git' `
        -Arguments @('-C', $repoRoot, 'diff', '--check', "$startHead..HEAD") `
        -Label 'WU7 committed diff check'
    Assert-True ($diffCheck.ExitCode -eq 0) 'Committed diff check failed'
    $workCheck = Invoke-CapturedProcess `
        -FilePath 'git' `
        -Arguments @('-C', $repoRoot, 'diff', '--check') `
        -Label 'WU7 working diff check'
    Assert-True ($workCheck.ExitCode -eq 0) 'Working diff check failed'
}

function Assert-SourceBoundaries {
    $code = @'
import re
import sys
from pathlib import Path

repo = Path(sys.argv[1]).resolve()
paths = (
    repo / "src" / "trip_decider" / "live_place_resolution.py",
    repo / "tests" / "test_wu7_live_place_resolution.py",
    repo / "scripts" / "run_live_place_resolution.ps1",
)
texts = {path: path.read_text(encoding="utf-8") for path in paths}
runtime = texts[paths[0]]
run_script = texts[paths[2]]
combined = "\n".join(texts.values())
for token in (
    "AMAP_PERSISTENCE_POLICY_UNRESOLVED",
    "LIVE_SMOKE_NOT_AUTHORIZED_STORAGE_POLICY_UNRESOLVED",
    "synthetic_test_data",
    "GCJ-02",
    "run_failure_evidenced_acquisition",
):
    assert token in runtime
assert "restapi.amap.com" not in runtime
assert not re.search(
    r"(?m)^\s*(?:from\s+(?:urllib\.request|httpx|requests|socket)"
    r"|import\s+(?:urllib\.request|httpx|requests|socket))\b",
    runtime,
)
assert "AMAP_WEB_SERVICE_KEY" not in runtime
assert "AMAP_WEB_SERVICE_KEY" not in run_script
assert "-Key" not in run_script
assert "AMAP_DURABLE_STORAGE_CONFIRMATION_MISSING" in run_script
assert "Invoke-Expression" not in combined
assert "silent_fallback" not in combined
assert not re.search(r"\b(?:infer|guess)_", runtime)
secret = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret)"
    r"\s*[:=]\s*['\"][A-Za-z0-9_-]{8,}"
)
assert not secret.search(combined)
print("WU7_SOURCE_BOUNDARIES=PASS")
'@
    $result = Invoke-TemporaryPython `
        -Code $code `
        -Label 'WU7 source, secret, and fallback audit' `
        -ScriptArguments @($repoRoot)
    Assert-True ($result.ExitCode -eq 0) 'Source boundary audit failed'
}

function Assert-TestsAndCounts {
    $targeted = Invoke-ProjectPython `
        -Arguments @(
            '-m',
            'unittest',
            'tests.test_wu7_live_place_resolution',
            '-v'
        ) `
        -Label 'WU7 six synthetic contract cases'
    Assert-True ($targeted.ExitCode -eq 0) 'WU7 targeted tests failed'
    Assert-True `
        ($targeted.Combined -match 'Ran 6 tests') `
        'WU7 targeted test count is not six'

    $modules = @(
        'tests.test_schema_validation',
        'tests.test_fixture_validation',
        'tests.wu1c_contract_compatibility_cases',
        'tests.test_wu2_adapters',
        'tests.test_wu2a_acquisition_harness',
        'tests.test_wu2_recovery',
        'tests.test_wu2r_failure_evidence',
        'tests.test_wu2r_resume',
        'tests.test_wu2r_downstream_recovery',
        'tests.test_wu3_evidence_runtime',
        'tests.test_wu4_unscheduled_activity_contract',
        'tests.test_wu4_coarse_planner',
        'tests.test_wu5_e2e_demo',
        'tests.test_wu7_live_place_resolution'
    )
    $regression = Invoke-ProjectPython `
        -Arguments (@('-m', 'unittest') + $modules + @('-v')) `
        -Label 'WU7 full regression'
    Assert-True ($regression.ExitCode -eq 0) 'WU7 full regression failed'
    Assert-True `
        ($regression.Combined -match 'Ran 216 tests') `
        'WU7 full regression count is not 216'

    $code = @'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve() / "fixtures"
fixture_dirs = sorted(path for path in root.iterdir() if path.is_dir())
documents = 0
dirty_cases = 0
for fixture in fixture_dirs:
    case = json.loads((fixture / "case.json").read_text(encoding="utf-8"))
    documents += len(case["documents"])
    dirty_cases += len(case["dirty_cases"])
assert (len(fixture_dirs), documents, dirty_cases) == (7, 40, 7)
print("FIXTURES=7")
print("DOCUMENTS=40")
print("DIRTY_CASES=7")
'@
    $counts = Invoke-TemporaryPython `
        -Code $code `
        -Label 'WU7 fixture counts' `
        -ScriptArguments @($repoRoot)
    Assert-True ($counts.ExitCode -eq 0) 'Fixture counts changed'
}

function Assert-LiveGateAndEnvironment {
    $runScript = Join-Path $repoRoot 'scripts\run_live_place_resolution.ps1'
    $outputRoot = Join-Path (
        [IO.Path]::GetTempPath()
    ) "trip-decider-wu7-$runToken-live-output"
    Assert-True (-not (Test-Path -LiteralPath $outputRoot)) 'Live output already exists'
    $hadPythonPath = Test-Path Env:PYTHONPATH
    $previousPythonPath = if ($hadPythonPath) {
        (Get-Item Env:PYTHONPATH).Value
    } else {
        $null
    }
    $hadKey = Test-Path Env:AMAP_WEB_SERVICE_KEY
    $previousKey = if ($hadKey) {
        (Get-Item Env:AMAP_WEB_SERVICE_KEY).Value
    } else {
        $null
    }
    try {
        $env:PYTHONPATH = 'wu7-verifier-pythonpath-sentinel'
        $env:AMAP_WEB_SERVICE_KEY = 'wu7-verifier-secret-sentinel'
        $arguments = @(
            '-NoProfile',
            '-ExecutionPolicy',
            'Bypass',
            '-File',
            $runScript,
            '-City',
            'SyntheticCity',
            '-StartAt',
            '2026-08-05T08:00:00+08:00',
            '-EndAt',
            '2026-08-06T20:00:00+08:00',
            '-InputRecordedAt',
            '2026-07-29T12:00:00+08:00',
            '-PartyCount',
            '1',
            '-TransportMode',
            'walking',
            '-MustVisit',
            'SyntheticPlace',
            '-OutputRoot',
            $outputRoot
        )
        $result = Invoke-CapturedProcess `
            -FilePath $powerShellExe `
            -Arguments $arguments `
            -Label 'WU7 policy-unresolved live gate'
        Assert-True ($result.ExitCode -eq 5) 'Live gate exit code is not 5'
        Assert-True `
            ($result.Stderr.Trim() -eq 'AMAP_DURABLE_STORAGE_CONFIRMATION_MISSING') `
            'Live gate status token mismatch'
        Assert-True `
            ([string]::IsNullOrEmpty($result.Stdout)) `
            'Live gate wrote stdout'
        Assert-True `
            (-not (Test-Path -LiteralPath $outputRoot)) `
            'Live gate created real provider output'
        Assert-True `
            ($env:PYTHONPATH -ceq 'wu7-verifier-pythonpath-sentinel') `
            'Parent PYTHONPATH changed'
        Assert-True `
            ($env:AMAP_WEB_SERVICE_KEY -ceq 'wu7-verifier-secret-sentinel') `
            'Parent key environment changed'
    } finally {
        if ($hadPythonPath) {
            $env:PYTHONPATH = $previousPythonPath
        } else {
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        }
        if ($hadKey) {
            $env:AMAP_WEB_SERVICE_KEY = $previousKey
        } else {
            Remove-Item Env:AMAP_WEB_SERVICE_KEY -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $outputRoot) {
            throw 'Unauthorized live output requires manual inspection'
        }
    }
}

function Assert-NoResidue {
    foreach ($path in $temporaryArtifacts) {
        Assert-True `
            (-not (Test-Path -LiteralPath $path)) `
            "Temporary verification artifact remains: $path"
    }
    $residue = @(
        Get-ChildItem `
            -LiteralPath ([IO.Path]::GetTempPath()) `
            -Filter "trip-decider-wu7-$runToken-*" `
            -Force `
            -ErrorAction SilentlyContinue
    )
    Assert-True ($residue.Count -eq 0) 'WU7 temporary residue remains'
}

try {
    Assert-Environment
    Assert-ScopeAndHistory
    Assert-SourceBoundaries
    Assert-TestsAndCounts
    Assert-LiveGateAndEnvironment
    Assert-NoResidue

    Write-Output 'WU7_VERIFICATION=PASS'
    Write-Output 'TESTS=216'
    Write-Output 'SCHEMAS=11'
    Write-Output 'FIXTURES_DOCUMENTS_DIRTY_CASES=7/40/7'
    Write-Output 'REAL_NETWORK_CALLS=0'
    Write-Output 'REAL_AMAP_OUTPUT_FILES=0'
    Write-Output 'LLM_CALLS=0'
    Write-Output 'TEMPORARY_RESIDUE=0'
    Write-Output (
        'LIVE_SMOKE_STATUS=' +
        'LIVE_SMOKE_NOT_AUTHORIZED_STORAGE_POLICY_UNRESOLVED'
    )
    Write-Output (
        'FINAL_STATUS=' +
        'BLOCKED_PENDING_AMAP_STORAGE_CONFIRMATION'
    )
} finally {
    foreach ($path in $temporaryArtifacts) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force
        }
    }
}
