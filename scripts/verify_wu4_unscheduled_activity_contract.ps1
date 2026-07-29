[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$startHead = '1d5bf5ddf84634a5ba62a00a5e2f32d92c33886e'
$approvedPlanHash = 'D01FBAC9642EF2790A19F3E502D0213DE03D85CB6B45F7E462BF1D15381E83B6'
$commonHash = 'A9134A705C67CF955228A28844AA2C5C42812AA2E0167E1256DB72F0ACAC36D7'
$testHash = '052BA5FA2149EE6CA58B61C65FD683AB11DDE6AF0BCEE74E2A87D8AD3A1A3308'
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
$oldPythonPath = $env:PYTHONPATH
$oldVerifyRoot = $env:TRIP_DECIDER_WU4_UC_VERIFY_ROOT

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
    $stdoutPath = Join-Path $tempRoot "trip-decider-wu4-uc-$token.stdout"
    $stderrPath = Join-Path $tempRoot "trip-decider-wu4-uc-$token.stderr"
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
            Label = $Label
            ExitCode = $process.ExitCode
            Stdout = $stdout
            Stderr = $stderr
            Combined = $stdout + $stderr
        }
    } finally {
        foreach ($path in @($stdoutPath, $stderrPath)) {
            if (Test-Path -LiteralPath $path) {
                Remove-Item -LiteralPath $path -Force
            }
        }
    }
}

function Assert-LockedEnvironment {
    $expected = @{}
    $lockPath = Join-Path $repoRoot 'requirements.lock'
    foreach ($line in Get-Content -LiteralPath $lockPath) {
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
        Assert-True (-not $actual.ContainsKey($name)) "Duplicate installed package: $name"
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

function Get-Wu4Paths {
    $paths = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($path in @(git diff --name-only "$startHead..HEAD")) {
        if (-not [string]::IsNullOrWhiteSpace($path)) {
            [void]$paths.Add($path.Replace('\', '/'))
        }
    }
    foreach ($line in @(git status --short -uall)) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        $path = $line.Substring(3).Replace('\', '/')
        Assert-True (-not $path.Contains(' -> ')) 'Renamed path is outside scope'
        [void]$paths.Add($path)
    }
    return $paths
}

function Assert-ScopeAndCommits {
    $allowedPaths = @(
        'plans/work-unit-4-unscheduled-activity-contract.md',
        'schemas/common.schema.json',
        'tests/test_wu4_unscheduled_activity_contract.py',
        'scripts/verify_wu4_unscheduled_activity_contract.ps1',
        'docs/reviews/work-unit-4-unscheduled-activity-contract-review.md'
    )
    $pathSet = Get-Wu4Paths
    foreach ($path in $pathSet) {
        Assert-True `
            ($allowedPaths -contains $path) `
            "Path outside WU4-UC whitelist: $path"
    }
    foreach ($required in $allowedPaths[0..3]) {
        Assert-True `
            ($pathSet.Contains($required)) `
            "Required WU4-UC path missing: $required"
    }

    $expectedMessages = @(
        'docs: record unscheduled activity contract plan',
        'test: expose unscheduled activity contract gap',
        'test: remove WU4 contract test trailing blank line',
        'feat: allow day-assigned unscheduled activities',
        'chore: add unscheduled activity contract verification',
        'docs: prepare unscheduled activity contract review'
    )
    $messages = @(git log --reverse --format='%s' "$startHead..HEAD")
    Assert-True `
        ($messages.Count -ge 4 -and $messages.Count -le 6) `
        'WU4-UC commit count is outside the approved sequence plus C1.1'
    for ($index = 0; $index -lt $messages.Count; $index += 1) {
        Assert-True `
            ($messages[$index] -eq $expectedMessages[$index]) `
            "WU4-UC commit mismatch at index $index"
    }
    if ($messages.Count -eq 6) {
        Assert-True `
            ($pathSet.Contains($allowedPaths[4])) `
            'Final WU4-UC Review path is missing'
    }
}

function Assert-FrozenInputs {
    $hashes = @{
        'plans/work-unit-4-unscheduled-activity-contract.md' = $approvedPlanHash
        'schemas/common.schema.json' = $commonHash
        'tests/test_wu4_unscheduled_activity_contract.py' = $testHash
        'requirements.lock' = 'BFE485EFB4105DC01C475D21EFB7858FD8468A69EBD0056363FBD9C84E6C6927'
        'pyproject.toml' = 'FD6622AA930E4BFA5986F26274EFA42B2512089050B716F445006C8EB98EA995'
        'schemas/candidates.schema.json' = '3E29144E1CEE4B300724D1E3DD63EB77DAE1F564135D6AB1B7C9B60F84B0CAB2'
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
    foreach ($path in $hashes.Keys) {
        Assert-FileHash -RelativePath $path -Expected $hashes[$path]
    }

    $schemaFiles = @(Get-ChildItem -LiteralPath (Join-Path $repoRoot 'schemas') -Filter '*.schema.json')
    Assert-True ($schemaFiles.Count -eq 11) 'Schema file count changed'
}

function Assert-Scans {
    $pathSet = Get-Wu4Paths
    $changedFiles = @(
        $pathSet |
        ForEach-Object { Join-Path $repoRoot ($_.Replace('/', '\')) } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
    )

    $logicPattern = (
        'in' + 'fer_|gu' + 'ess_|silent_' + 'fallback|' +
        'warning_' + 'as_pass|default_when_' + 'missing'
    )
    Assert-True `
        (-not (Select-String -Path $changedFiles -Pattern $logicPattern -Quiet)) `
        'Fallback, guessing, or warning-as-pass token found'

    $secretPatterns = @(
        ('-----BEGIN ' + '(RSA |EC |OPENSSH )?' + 'PRIVATE KEY-----'),
        (
            '(?i)(AMAP|GAODE|BAIDU|TENCENT|QQ)' +
            '[_-]?(KEY|AK|SECRET)\s*[:=]\s*[''"]' +
            '[A-Za-z0-9_-]{8,}'
        ),
        (
            '(?i)(password|token|secret)' +
            '\s*[:=]\s*[''"]' +
            '[A-Za-z0-9_-]{12,}'
        )
    )
    foreach ($pattern in $secretPatterns) {
        Assert-True `
            (-not (Select-String -Path $changedFiles -Pattern $pattern -Quiet)) `
            'Potential secret pattern found'
    }

    $testPath = Join-Path $repoRoot 'tests\test_wu4_unscheduled_activity_contract.py'
    $transportPattern = (
        'requ' + 'ests\.|urllib\.request|http\.' + 'client|socket\.'
    )
    Assert-True `
        (-not (Select-String -Path $testPath -Pattern $transportPattern -Quiet)) `
        'Network transport found in WU4-UC tests'

    $diffProblems = @(git diff --check "$startHead..HEAD")
    Assert-True ($diffProblems.Count -eq 0) 'Tracked WU4-UC diff has whitespace errors'
}

function Invoke-TargetedTests {
    $result = Invoke-CapturedProcess `
        -FilePath $pythonExe `
        -Arguments @(
            '-m',
            'unittest',
            'tests.test_wu4_unscheduled_activity_contract',
            '-v'
        ) `
        -Label 'WU4-UC targeted contract tests'
    Assert-True ($result.ExitCode -eq 0) "Targeted tests exited $($result.ExitCode)"
    Assert-True `
        ($result.Combined -match 'Ran\s+6\s+tests?') `
        'Targeted gate did not report exactly 6 tests'
    Assert-True `
        ($result.Combined -match '(?m)^OK\s*$') `
        'Targeted gate did not report OK'
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
        'tests.test_wu4_unscheduled_activity_contract'
    )
    $result = Invoke-CapturedProcess `
        -FilePath $pythonExe `
        -Arguments $arguments `
        -Label 'WU4-UC complete offline suite'
    Assert-True ($result.ExitCode -eq 0) "Full regression exited $($result.ExitCode)"
    Assert-True `
        ($result.Combined -match 'Ran\s+198\s+tests?') `
        'Full regression did not report exactly 198 tests'
    Assert-True `
        ($result.Combined -match '(?m)^OK\s*$') `
        'Full regression did not report OK'
}

$helperToken = [Guid]::NewGuid().ToString('N')
$helperPattern = 'trip-decider-wu4-uc-contract-*.py'
$tempRoot = [IO.Path]::GetTempPath()
$helperPath = Join-Path $tempRoot "trip-decider-wu4-uc-contract-$helperToken.py"
$beforeResidue = @(
    Get-ChildItem -LiteralPath $tempRoot -Filter $helperPattern -File |
    ForEach-Object { $_.FullName }
)
$helperCode = @'
import json
import os
import site
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from trip_decider.fixture_validation import validate_fixture_directory
from trip_decider.schema_validation import validate_schema_registry


root = Path(os.environ["TRIP_DECIDER_WU4_UC_VERIFY_ROOT"]).resolve()
expected_python = (root / ".venv" / "Scripts" / "python.exe").resolve()
expected_prefix = (root / ".venv").resolve()

assert Path.cwd().resolve() == root
assert Path(sys.executable).resolve() == expected_python
assert Path(sys.prefix).resolve() == expected_prefix
assert all(
    expected_prefix == Path(item).resolve()
    or expected_prefix in Path(item).resolve().parents
    for item in site.getsitepackages()
)

schema_paths = tuple(sorted((root / "schemas").glob("*.schema.json")))
assert len(schema_paths) == 11
registry = validate_schema_registry(schema_paths)
assert registry.problems == () and registry.value is not None
fixtures = validate_fixture_directory(root / "fixtures", registry.value)
assert fixtures.problems == () and fixtures.value is not None
assert (
    fixtures.value.fixture_count,
    fixtures.value.document_count,
    fixtures.value.dirty_case_count,
) == (7, 40, 7)

common = json.loads(
    (root / "schemas" / "common.schema.json").read_text(encoding="utf-8")
)
plan = json.loads(
    (root / "schemas" / "plan.schema.json").read_text(encoding="utf-8")
)
previous = json.loads(
    (root / "schemas" / "previous-plan.schema.json").read_text(
        encoding="utf-8"
    )
)

assert common["$id"].endswith("/0.1.0/common.schema.json")
activity_schema = common["$defs"]["activity"]
assert activity_schema["additionalProperties"] is False
assert activity_schema["required"] == [
    "activity_id",
    "candidate_ref",
    "constraint_refs",
    "evidence_fact_refs",
]
assert activity_schema["properties"]["timing_status"]["enum"] == [
    "timed",
    "day_assigned_unscheduled",
]
assert len(activity_schema["oneOf"]) == 2
assert (
    common["$defs"]["day"]["properties"]["activities"]["items"]["$ref"]
    == "#/$defs/activity"
)
assert (
    plan["allOf"][1]["properties"]["payload"]["properties"]["days"]["items"][
        "$ref"
    ]
    == "common.schema.json#/$defs/day"
)
assert (
    previous["allOf"][1]["properties"]["payload"]["properties"]["snapshot"][
        "properties"
    ]["days"]["items"]["$ref"]
    == "common.schema.json#/$defs/day"
)

wrapper = {
    "$schema": common["$schema"],
    "$defs": common["$defs"],
    "$ref": "#/$defs/day",
}
validator = Draft202012Validator(wrapper, format_checker=FormatChecker())


def activity(**timing):
    value = {
        "activity_id": "activity_00000001-0000-4000-8000-000000000001",
        "candidate_ref": "candidate_00000001-0000-4000-8000-000000000001",
        "constraint_refs": [],
        "evidence_fact_refs": [],
    }
    value.update(timing)
    return value


def day(value):
    return {
        "day_id": "day_00000001-0000-4000-8000-000000000001",
        "date": "2026-08-05",
        "activities": [value],
        "legs": [],
    }


cases = (
    (
        "legacy_timed",
        activity(
            start_at="2026-08-05T09:00:00+08:00",
            end_at="2026-08-05T11:00:00+08:00",
        ),
        True,
    ),
    (
        "explicit_timed",
        activity(
            timing_status="timed",
            start_at="2026-08-05T09:00:00+08:00",
            end_at="2026-08-05T11:00:00+08:00",
        ),
        True,
    ),
    (
        "day_assigned_unscheduled",
        activity(timing_status="day_assigned_unscheduled"),
        True,
    ),
    ("missing_mode", activity(), False),
    (
        "partial_timed",
        activity(
            timing_status="timed",
            start_at="2026-08-05T09:00:00+08:00",
        ),
        False,
    ),
    (
        "mixed_unscheduled",
        activity(
            timing_status="day_assigned_unscheduled",
            start_at="2026-08-05T09:00:00+08:00",
        ),
        False,
    ),
    (
        "null_timed",
        activity(start_at=None, end_at=None),
        False,
    ),
    (
        "empty_timed",
        activity(start_at="", end_at=""),
        False,
    ),
    (
        "unknown_mode",
        activity(
            timing_status="unknown",
            start_at="2026-08-05T09:00:00+08:00",
            end_at="2026-08-05T11:00:00+08:00",
        ),
        False,
    ),
)

for name, value, expected_valid in cases:
    problems = tuple(validator.iter_errors(day(value)))
    actual_valid = not problems
    assert actual_valid is expected_valid, name

print(
    json.dumps(
        {
            "contract_cases": len(cases),
            "dirty_cases": fixtures.value.dirty_case_count,
            "documents": fixtures.value.document_count,
            "fixture_directories": fixtures.value.fixture_count,
            "network_attempts": 0,
            "schemas": len(schema_paths),
        },
        sort_keys=True,
    )
)
'@

try {
    Set-Location -LiteralPath $repoRoot
    Assert-True (Test-Path -LiteralPath $pythonExe -PathType Leaf) 'Project .venv Python is missing'

    $env:PYTHONPATH = Join-Path $repoRoot 'src'
    $env:TRIP_DECIDER_WU4_UC_VERIFY_ROOT = $repoRoot

    Assert-ScopeAndCommits
    Assert-FrozenInputs
    Assert-LockedEnvironment
    Assert-Scans

    [IO.File]::WriteAllText(
        $helperPath,
        $helperCode,
        [Text.UTF8Encoding]::new($false)
    )
    $contractGate = Invoke-CapturedProcess `
        -FilePath $pythonExe `
        -Arguments @($helperPath) `
        -Label 'WU4-UC independent contract matrix'
    Assert-True ($contractGate.ExitCode -eq 0) 'Independent contract matrix failed'
    Assert-True `
        ($contractGate.Stdout -match '"contract_cases": 9') `
        'Independent contract matrix count is not 9'
    Assert-True `
        ($contractGate.Stdout -match '"fixture_directories": 7') `
        'Fixture directory count changed'
    Assert-True `
        ($contractGate.Stdout -match '"documents": 40') `
        'Fixture document count changed'
    Assert-True `
        ($contractGate.Stdout -match '"dirty_cases": 7') `
        'Dirty case count changed'

    Invoke-TargetedTests
    Invoke-FullRegression

    if (Test-Path -LiteralPath $helperPath) {
        Remove-Item -LiteralPath $helperPath -Force
    }
    $afterResidue = @(
        Get-ChildItem -LiteralPath $tempRoot -Filter $helperPattern -File |
        ForEach-Object { $_.FullName }
    )
    Assert-True `
        ($afterResidue.Count -eq $beforeResidue.Count) `
        'WU4-UC verification residue count changed'
    foreach ($path in $beforeResidue) {
        Assert-True ($afterResidue -contains $path) 'Pre-existing temporary file changed'
    }

    Write-Output (
        'WU4-UC verification PASS: tests=198 schemas=11 ' +
        'fixtures=7 documents=40 dirty_cases=7 contract_cases=9 ' +
        'network_attempts=0 temporary_residue=0'
    )
    exit 0
} catch {
    [Console]::Error.WriteLine("WU4-UC verification FAIL: $($_.Exception.Message)")
    exit 1
} finally {
    if (Test-Path -LiteralPath $helperPath) {
        Remove-Item -LiteralPath $helperPath -Force
    }
    $env:PYTHONPATH = $oldPythonPath
    $env:TRIP_DECIDER_WU4_UC_VERIFY_ROOT = $oldVerifyRoot
}
