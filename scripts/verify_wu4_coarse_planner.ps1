[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$startHead = 'e3660ee4fb93e27b27e7486b8bc1b1c75a67da21'
$approvedPlanHash = '463A57AC09A8C6671CE67C1EB753BAFBD30B454F5D313B2EFC0F8A0DECED5DD0'
$runtimeHash = '8098F75190E279419D704E9135B896DE84D88691D4B2A942142671C870E25D8C'
$testHash = '1A9A090F32E9C785F36034A23B66D76F0173EDA95069882F514E3AFCE4C289E4'
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'

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

function Assert-FileHash {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RelativePath,

        [Parameter(Mandatory = $true)]
        [string]$Expected
    )

    $path = Join-Path $repoRoot ($RelativePath.Replace('/', '\'))
    Assert-True `
        (Test-Path -LiteralPath $path -PathType Leaf) `
        "Missing frozen file: $RelativePath"
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    Assert-True ($actual -eq $Expected) "Frozen hash mismatch: $RelativePath"
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
    $stdoutPath = Join-Path $tempRoot "trip-decider-wu4-cp-$token.stdout"
    $stderrPath = Join-Path $tempRoot "trip-decider-wu4-cp-$token.stderr"
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

function Invoke-TemporaryPython {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Code,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    $token = [Guid]::NewGuid().ToString('N')
    $scriptPath = Join-Path `
        ([IO.Path]::GetTempPath()) `
        "trip-decider-wu4-cp-$token.py"
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    try {
        [IO.File]::WriteAllText($scriptPath, $Code, $utf8NoBom)
        return Invoke-CapturedProcess `
            -FilePath $pythonExe `
            -Arguments @($scriptPath) `
            -Label $Label
    } finally {
        if (Test-Path -LiteralPath $scriptPath) {
            Remove-Item -LiteralPath $scriptPath -Force
        }
    }
}

function Assert-PythonEnvironment {
    Assert-True `
        (Test-Path -LiteralPath $pythonExe -PathType Leaf) `
        'Project .venv Python is missing'

    $code = @'
import json
import site
import sys
from pathlib import Path

repo = Path.cwd().resolve()
venv = (repo / ".venv").resolve()
executable = Path(sys.executable).resolve()
prefix = Path(sys.prefix).resolve()
site_paths = [Path(value).resolve() for value in site.getsitepackages()]

assert executable == (venv / "Scripts" / "python.exe").resolve()
assert prefix == venv
assert site_paths
assert all(venv == path or venv in path.parents for path in site_paths)
print(json.dumps({
    "executable_in_project_venv": True,
    "prefix_in_project_venv": True,
    "site_packages_in_project_venv": True,
}, sort_keys=True))
'@
    $origin = Invoke-TemporaryPython `
        -Code $code `
        -Label 'project venv origin'
    Assert-True ($origin.ExitCode -eq 0) 'Project venv origin check failed'
}

function Assert-LockedEnvironment {
    $expected = @{}
    foreach ($line in Get-Content -LiteralPath (Join-Path $repoRoot 'requirements.lock')) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        Assert-True `
            ($line -match '^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)$') `
            "Invalid lock line: $line"
        $name = $matches[1].ToLowerInvariant().Replace('_', '-')
        Assert-True (-not $expected.ContainsKey($name)) "Duplicate lock entry: $name"
        $expected[$name] = $matches[2]
    }

    $pipList = Invoke-CapturedProcess `
        -FilePath $pythonExe `
        -Arguments @('-m', 'pip', 'list', '--format=json') `
        -Label 'locked package inventory'
    Assert-True ($pipList.ExitCode -eq 0) 'pip list failed'
    $actual = @{}
    foreach ($item in (ConvertFrom-Json -InputObject $pipList.Stdout)) {
        $name = ([string]$item.name).ToLowerInvariant().Replace('_', '-')
        if ($name -in @('pip', 'setuptools')) {
            continue
        }
        $actual[$name] = [string]$item.version
    }
    Assert-True `
        ($actual.Count -eq $expected.Count) `
        'Locked and installed package counts differ'
    foreach ($name in $expected.Keys) {
        Assert-True ($actual.ContainsKey($name)) "Locked package missing: $name"
        Assert-True `
            ($actual[$name] -eq $expected[$name]) `
            "Locked package version mismatch: $name"
    }

    $pipCheck = Invoke-CapturedProcess `
        -FilePath $pythonExe `
        -Arguments @('-m', 'pip', 'check') `
        -Label 'pip check'
    Assert-True ($pipCheck.ExitCode -eq 0) 'pip check failed'
    Assert-True `
        ($pipCheck.Combined -match 'No broken requirements found') `
        'pip check did not report a clean environment'
}

function Assert-FrozenHashes {
    Assert-FileHash `
        'plans/work-unit-4-coarse-planner.md' `
        $approvedPlanHash
    Assert-FileHash 'src/trip_decider/coarse_planner.py' $runtimeHash
    Assert-FileHash 'tests/test_wu4_coarse_planner.py' $testHash
    Assert-FileHash `
        'PLAN.md' `
        '563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456'
    Assert-FileHash `
        'requirements.lock' `
        'BFE485EFB4105DC01C475D21EFB7858FD8468A69EBD0056363FBD9C84E6C6927'
    Assert-FileHash `
        'pyproject.toml' `
        'FD6622AA930E4BFA5986F26274EFA42B2512089050B716F445006C8EB98EA995'
    Assert-FileHash `
        'src/trip_decider/recovery.py' `
        'C0E098DD4AB997727A0EFBCCC9C396AC480DEEB3477DBF4CDCB5E31A34E0D8BA'
    Assert-FileHash `
        'src/trip_decider/evidence_runtime.py' `
        '626D052F068537D050D350E8404948286670405D0B75C2E793CAA71656C89C04'
    Assert-FileHash `
        'src/trip_decider/schema_validation.py' `
        '2061084E8AC27DF4C08F63DC264A2612685980D966AA5291A46660BE3F1CC017'

    $schemaHashes = [ordered]@{
        'schemas/candidates.schema.json' = '3E29144E1CEE4B300724D1E3DD63EB77DAE1F564135D6AB1B7C9B60F84B0CAB2'
        'schemas/common.schema.json' = 'A9134A705C67CF955228A28844AA2C5C42812AA2E0167E1256DB72F0ACAC36D7'
        'schemas/constraint-parse.schema.json' = '0D41493B52B6178AEE8DE44B2F3607B193B62C263AD79DEF380B638B22B400A4'
        'schemas/constraints.schema.json' = '25069E0DEFBDC03FEA7E92E83EE10F952A31A2B18BDC3678D17786C537EE4473'
        'schemas/evidence.schema.json' = '54904C8553BA5223BFB16A2253F1FDBD1FA18CFB77BDB7E5A616C41F24782F8B'
        'schemas/fixture-case.schema.json' = '630E57E7F27A660F388407A8FF1B81D851B8B3A047E5B98DCB70E1920177E45A'
        'schemas/plan.schema.json' = '81EEB5899C33F19DC6FA059C7D447D747E72E355F3084D925FD9410272389BD3'
        'schemas/plan-diff.schema.json' = '37B94FE5E03A73B046D7E6D79BEABF31C4105E50CD54DE520CA6C293AB3E8B43'
        'schemas/previous-plan.schema.json' = '59692D17EB79C7EA2D4A2E2866898DD97A0E49B97834EC8AFC5EAB46A80BEDAC'
        'schemas/request.schema.json' = 'BC7F46E9A85CE9697F9BA01FF1506A5B56C161F2F6B5140D91FCF0B100762914'
        'schemas/violations.schema.json' = 'C117415030993C24649B17837EC2A35C69A2F1CEC7D923742ABD383BA85B394F'
    }
    foreach ($entry in $schemaHashes.GetEnumerator()) {
        Assert-FileHash $entry.Key $entry.Value
    }
    $schemaCount = @(
        Get-ChildItem `
            -LiteralPath (Join-Path $repoRoot 'schemas') `
            -Filter '*.schema.json'
    ).Count
    Assert-True ($schemaCount -eq 11) 'Schema count changed'
}

function Assert-ScopeAndCommits {
    $allowedPaths = @(
        'plans/work-unit-4-coarse-planner.md',
        'src/trip_decider/coarse_planner.py',
        'tests/test_wu4_coarse_planner.py',
        'scripts/verify_wu4_coarse_planner.ps1',
        'docs/reviews/work-unit-4-coarse-planner-review.md'
    )
    $pathSet = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($path in @(git diff --name-only "$startHead..HEAD")) {
        if (-not [string]::IsNullOrWhiteSpace($path)) {
            [void]$pathSet.Add($path.Replace('\', '/'))
        }
    }
    foreach ($line in @(git status --short -uall)) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        $path = $line.Substring(3).Replace('\', '/')
        Assert-True (-not $path.Contains(' -> ')) 'Renamed path is outside scope'
        [void]$pathSet.Add($path)
    }
    foreach ($path in $pathSet) {
        Assert-True `
            ($allowedPaths -contains $path) `
            "Path outside WU4-CP whitelist: $path"
    }
    foreach ($required in $allowedPaths[0..3]) {
        Assert-True `
            ($pathSet.Contains($required)) `
            "Required WU4-CP path missing: $required"
    }

    $expectedMessages = @(
        'docs: record WU4 coarse planner plan',
        'chore: add coarse planner interface',
        'test: add failing coarse planner cases',
        'feat: implement conditional coarse planner',
        'chore: add coarse planner verification entry',
        'docs: prepare WU4 coarse planner review'
    )
    $actualMessages = @(
        git log --reverse --format=%s "$startHead..HEAD"
    )
    Assert-True `
        ($actualMessages.Count -ge 4 -and $actualMessages.Count -le 6) `
        'WU4-CP commit count is outside the approved execution stages'
    for ($index = 0; $index -lt $actualMessages.Count; $index++) {
        Assert-True `
            ($actualMessages[$index] -ceq $expectedMessages[$index]) `
            "WU4-CP commit mismatch at index $index"
    }
}

function Assert-R10Scans {
    $runtime = Join-Path $repoRoot 'src\trip_decider\coarse_planner.py'
    $runtimeText = [IO.File]::ReadAllText($runtime, [Text.Encoding]::UTF8)
    foreach ($pattern in @(
        '\binfer_[A-Za-z0-9_]*\b',
        '\bguess_[A-Za-z0-9_]*\b',
        'silent_fallback',
        'default_when_missing',
        'urllib',
        'http\.client',
        '\brequests\b',
        '\bsocket\b',
        'nominatim',
        'overpass',
        'osrm',
        '高德|百度|腾讯|Google',
        '婺源|江岭|李坑|篁岭|庆源'
    )) {
        Assert-True `
            (-not [regex]::IsMatch($runtimeText, $pattern, 'IgnoreCase')) `
            "Forbidden runtime pattern found: $pattern"
    }
    Assert-True `
        (-not $runtimeText.Contains('NotImplementedError')) `
        'Reachable NotImplementedError remains in runtime'
    Assert-True `
        ($runtimeText.Contains('"network_attempts": 0')) `
        'Runtime does not freeze zero network attempts'
    Assert-True `
        ($runtimeText.Contains('"llm_calls": 0')) `
        'Runtime does not freeze zero LLM calls'

    $changedFiles = @(
        git diff --name-only "$startHead..HEAD"
    )
    $scanPaths = @()
    foreach ($relative in $changedFiles) {
        $path = Join-Path $repoRoot $relative
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $scanPaths += $path
        }
    }
    foreach ($path in $scanPaths) {
        $text = [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8)
        foreach ($pattern in @(
            '(?i)(api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*["''][^"'']+',
            'sk-[A-Za-z0-9]{16,}',
            'AKIA[0-9A-Z]{16}'
        )) {
            Assert-True `
                (-not [regex]::IsMatch($text, $pattern)) `
                "Potential secret found in $path"
        }
    }
}

function Invoke-TargetedTests {
    $result = Invoke-CapturedProcess `
        -FilePath $pythonExe `
        -Arguments @(
            '-m',
            'unittest',
            'tests.test_wu4_coarse_planner',
            '-v'
        ) `
        -Label 'WU4-CP targeted tests'
    Assert-True ($result.ExitCode -eq 0) "Targeted tests exited $($result.ExitCode)"
    Assert-True `
        ($result.Combined -match 'Ran 6 tests') `
        'Targeted test count is not 6'
    Assert-True `
        ($result.Combined -match '(?m)^OK\s*$') `
        'Targeted tests did not report OK'
}

function Invoke-FullRegression {
    $arguments = @(
        '-m',
        'unittest',
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
        'tests.test_wu4_coarse_planner'
    )
    $result = Invoke-CapturedProcess `
        -FilePath $pythonExe `
        -Arguments $arguments `
        -Label 'WU4-CP complete offline suite'
    Assert-True ($result.ExitCode -eq 0) "Full regression exited $($result.ExitCode)"
    Assert-True `
        ($result.Combined -match 'Ran 204 tests') `
        'Full regression count is not 204'
    Assert-True `
        ($result.Combined -match '(?m)^OK\s*$') `
        'Full regression did not report OK'
}

function Invoke-IndependentMatrix {
    $code = @'
import json
import socket
import sys
import tempfile
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path.cwd() / "src"))

from tests.test_wu4_coarse_planner import (
    ANCHOR,
    HUANGLING_REFS,
    JIANGLING_REF,
    LIKENG_REF,
    _write_planning_root,
)
from trip_decider.coarse_planner import run_coarse_planner
from trip_decider.evidence_runtime import run_evidence_runtime
from trip_decider.recovery import run_wu2_recovery

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

with tempfile.TemporaryDirectory(prefix="trip-decider-wu4-cp-matrix-") as temp:
    root = Path(temp)
    recovery_root = root / "recovery"
    evidence_root = root / "evidence"
    planning_root = root / "planning"
    output_root = root / "output"
    recovery = run_wu2_recovery(ANCHOR, recovery_root)
    assert recovery.problems == ()
    evidence = run_evidence_runtime(recovery_root, evidence_root)
    assert evidence.problems == ()
    _write_planning_root(planning_root, 2)
    with (
        patch.object(
            socket.socket,
            "connect",
            side_effect=AssertionError("network forbidden"),
        ) as socket_mock,
        patch.object(
            urllib.request,
            "urlopen",
            side_effect=AssertionError("network forbidden"),
        ) as urlopen_mock,
    ):
        result = run_coarse_planner(
            recovery_root,
            evidence_root,
            planning_root,
            output_root,
        )
    assert result.problems == ()
    assert result.value is not None
    assert socket_mock.call_count == 0
    assert urlopen_mock.call_count == 0
    assert sorted(path.name for path in output_root.iterdir()) == [
        "plan.json",
        "planning-gate.json",
        "run-summary.json",
        "violations.json",
    ]
    plan = load(output_root / "plan.json")
    gate = load(output_root / "planning-gate.json")
    summary = load(output_root / "run-summary.json")
    activities = [
        activity
        for day in plan["payload"]["days"]
        for activity in day["activities"]
    ]
    assert plan["payload"]["plan_status"] == "conditionally_feasible"
    assert [item["candidate_ref"] for item in activities] == [
        JIANGLING_REF,
        LIKENG_REF,
    ]
    assert all(
        item["timing_status"] == "day_assigned_unscheduled"
        and "start_at" not in item
        and "end_at" not in item
        for item in activities
    )
    assert all(day["legs"] == [] for day in plan["payload"]["days"])
    blocked = {item["seed"]: item for item in gate["blocked_seeds"]}
    assert blocked["篁岭"]["candidate_refs"] == list(HUANGLING_REFS)
    assert blocked["庆源"]["candidate_refs"] == []
    assert gate["generation_allowed_input"] is False
    assert gate["draft_created"] is True
    assert gate["publishable"] is False
    assert gate["planning_status"] == "conditionally_feasible"
    assert summary["network_attempts"] == 0
    assert summary["llm_calls"] == 0
    assert summary["scheduled_candidate_count"] == 2
    print(json.dumps({
        "blocked_seeds": len(gate["blocked_seeds"]),
        "draft_created": gate["draft_created"],
        "generation_allowed_input": gate["generation_allowed_input"],
        "llm_calls": summary["llm_calls"],
        "network_attempts": summary["network_attempts"],
        "outputs": len(list(output_root.iterdir())),
        "planning_status": gate["planning_status"],
        "publishable": gate["publishable"],
        "scheduled_candidates": summary["scheduled_candidate_count"],
    }, ensure_ascii=True, sort_keys=True))
'@
    $result = Invoke-TemporaryPython `
        -Code $code `
        -Label 'WU4-CP independent real-anchor matrix'
    Assert-True ($result.ExitCode -eq 0) 'Independent matrix failed'
    Assert-True `
        ($result.Stdout -match '"outputs": 4') `
        'Independent matrix did not report four outputs'
    Assert-True `
        ($result.Stdout -match '"scheduled_candidates": 2') `
        'Independent matrix did not report two scheduled candidates'
    Assert-True `
        ($result.Stdout -match '"network_attempts": 0') `
        'Independent matrix did not report zero network attempts'
    Assert-True `
        ($result.Stdout -match '"llm_calls": 0') `
        'Independent matrix did not report zero LLM calls'
}

function Assert-FixtureStatistics {
    $code = @'
import json
from pathlib import Path

roots = sorted(
    path
    for path in Path("fixtures").iterdir()
    if path.is_dir() and (path / "case.json").is_file()
)
documents = 0
dirty_cases = 0
for root in roots:
    case = json.loads((root / "case.json").read_text(encoding="utf-8"))
    documents += len(case["documents"])
    dirty_cases += len(case["dirty_cases"])
result = {
    "dirty_cases": dirty_cases,
    "documents": documents,
    "fixtures": len(roots),
    "schemas": len(list(Path("schemas").glob("*.schema.json"))),
}
assert result == {
    "dirty_cases": 7,
    "documents": 40,
    "fixtures": 7,
    "schemas": 11,
}
print(json.dumps(result, sort_keys=True))
'@
    $result = Invoke-TemporaryPython `
        -Code $code `
        -Label 'fixture and schema statistics'
    Assert-True ($result.ExitCode -eq 0) 'Fixture statistics failed'
}

$tempPattern = 'trip-decider-wu4-cp-*'
$beforeResidue = @(
    Get-ChildItem `
        -LiteralPath ([IO.Path]::GetTempPath()) `
        -Filter $tempPattern `
        -Force `
        -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty FullName
)

try {
    Push-Location $repoRoot
    Assert-True `
        ((git branch --show-current) -eq 'main') `
        'WU4-CP verification requires main'
    Assert-True `
        ((git rev-parse $startHead) -eq $startHead) `
        'WU4-CP start HEAD is missing'
    Assert-PythonEnvironment
    Assert-LockedEnvironment
    Assert-FrozenHashes
    Assert-ScopeAndCommits
    Assert-R10Scans

    $diffProblems = @(git diff --check "$startHead..HEAD")
    Assert-True `
        ($diffProblems.Count -eq 0) `
        'Tracked WU4-CP diff has whitespace errors'

    Invoke-TargetedTests
    Invoke-FullRegression
    Invoke-IndependentMatrix
    Assert-FixtureStatistics

    $afterResidue = @(
        Get-ChildItem `
            -LiteralPath ([IO.Path]::GetTempPath()) `
            -Filter $tempPattern `
            -Force `
            -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty FullName
    )
    $newResidue = @(
        $afterResidue |
        Where-Object { $beforeResidue -notcontains $_ }
    )
    Assert-True `
        ($newResidue.Count -eq 0) `
        'WU4-CP verification left temporary residue'

    [Console]::Out.WriteLine(
        'WU4-CP verification PASS: tests=204 schemas=11 ' +
        'fixtures=7 documents=40 dirty_cases=7 outputs=4 ' +
        'network_attempts=0 llm_calls=0 temporary_residue=0'
    )
} catch {
    [Console]::Error.WriteLine(
        "WU4-CP verification FAIL: $($_.Exception.Message)"
    )
    exit 1
} finally {
    Pop-Location
}

exit 0
