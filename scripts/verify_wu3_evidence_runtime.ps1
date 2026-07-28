[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$startHead = 'a1a79665d7eaba1cd3f1224b88c8c316e4d86051'
$approvedPlanHash = 'D27D083ADED805A0E0E11528918E4557A769C73B78C60C63DA54C62BF97BBC19'
$runtimeHash = '626D052F068537D050D350E8404948286670405D0B75C2E793CAA71656C89C04'
$testHash = '4C7F3FF666FB92A9242064D81FEA33B4404EAE9099593832FFE798703F962747'
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
$oldPythonPath = $env:PYTHONPATH
$oldVerifyRoot = $env:TRIP_DECIDER_WU3_VERIFY_ROOT

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
    $stdoutPath = Join-Path $tempRoot "trip-decider-wu3-verify-$token.stdout"
    $stderrPath = Join-Path $tempRoot "trip-decider-wu3-verify-$token.stderr"
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

function Assert-ScopeAndCommits {
    $allowedPaths = @(
        'plans/work-unit-3-evidence-runtime.md',
        'src/trip_decider/evidence_runtime.py',
        'tests/test_wu3_evidence_runtime.py',
        'scripts/verify_wu3_evidence_runtime.ps1',
        'docs/reviews/work-unit-3-evidence-runtime-review.md'
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
            "Path outside WU3-ER whitelist: $path"
    }
    foreach ($required in $allowedPaths[0..3]) {
        Assert-True `
            ($pathSet.Contains($required)) `
            "Required WU3-ER path missing: $required"
    }

    $expectedMessages = @(
        'docs: record WU3 evidence runtime plan',
        'chore: add Evidence Runtime interface',
        'test: add failing Evidence Runtime cases',
        'feat: implement candidate Evidence Runtime',
        'chore: add Evidence Runtime verification entry',
        'docs: prepare WU3 evidence runtime review'
    )
    $messages = @(git log --reverse --format='%s' "$startHead..HEAD")
    Assert-True `
        ($messages.Count -ge 4 -and $messages.Count -le 6) `
        'WU3-ER commit count is outside the approved sequence'
    for ($index = 0; $index -lt $messages.Count; $index += 1) {
        Assert-True `
            ($messages[$index] -eq $expectedMessages[$index]) `
            "WU3-ER commit mismatch at index $index"
    }
    if ($messages.Count -eq 6) {
        Assert-True `
            ($pathSet.Contains($allowedPaths[4])) `
            'Final WU3-ER Review path is missing'
    }
}

function Assert-FrozenInputs {
    $hashes = @{
        'plans/work-unit-3-evidence-runtime.md' = $approvedPlanHash
        'src/trip_decider/evidence_runtime.py' = $runtimeHash
        'tests/test_wu3_evidence_runtime.py' = $testHash
        'PLAN.md' = '563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456'
        'requirements.lock' = 'BFE485EFB4105DC01C475D21EFB7858FD8468A69EBD0056363FBD9C84E6C6927'
        'pyproject.toml' = 'FD6622AA930E4BFA5986F26274EFA42B2512089050B716F445006C8EB98EA995'
        'src/trip_decider/recovery.py' = 'C0E098DD4AB997727A0EFBCCC9C396AC480DEEB3477DBF4CDCB5E31A34E0D8BA'
        'src/trip_decider/resume_acquisition.py' = '86229BA52695D3B4725DFDB54D709C8D79580DD35B8FCEE010D3AD59B7D0A6AE'
        'src/trip_decider/acquisition_evidence.py' = 'BF7F25FC4A41C8085431450501B86866A7757B125A208363AA5113AD5F82FEDB'
        'src/trip_decider/adapters/open_data_poi.py' = 'F39EBF86B682EDECF182F6148178AEBA434A287B34A270FE84D3FAEE8F80944B'
        'src/trip_decider/schema_validation.py' = '2061084E8AC27DF4C08F63DC264A2612685980D966AA5291A46660BE3F1CC017'
        'src/trip_decider/fixture_validation.py' = '6C720C5F4D72356F2909854E6C1B605B891BC40787A4D87739CCA69C2590EBBF'
        'fixtures/jiangxi_multi_identity_smoke/case.json' = '6052797C4FE43B0E1BE216187EAD6AC10FB1617F07CD7784CF81F8403843F3C8'
        'fixtures/jiangxi_multi_identity_smoke/replay.json' = '5D8086E128FE1B33FD0314151C49256A459DB401233B1C548843791AFAC1919A'
        'fixtures/jiangxi_multi_identity_smoke/osm-pois.json' = '41520443BB370919F184CF46441DB897A809EB1B86119B7CF2B6007F20A5B382'
        'schemas/candidates.schema.json' = '3E29144E1CEE4B300724D1E3DD63EB77DAE1F564135D6AB1B7C9B60F84B0CAB2'
        'schemas/common.schema.json' = '83FE17127A545D168A16F58911564E53D2E17AFF826B6D34437D873ECF8E75BE'
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
}

function Assert-Scans {
    $runtimePath = Join-Path $repoRoot 'src\trip_decider\evidence_runtime.py'
    $changedFiles = @(
        git diff --name-only "$startHead..HEAD" |
        ForEach-Object { Join-Path $repoRoot ($_.Replace('/', '\')) } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
    )
    foreach ($line in @(git status --short -uall)) {
        if (-not [string]::IsNullOrWhiteSpace($line)) {
            $path = Join-Path $repoRoot ($line.Substring(3).Replace('/', '\'))
            if (Test-Path -LiteralPath $path -PathType Leaf) {
                $changedFiles += $path
            }
        }
    }
    $changedFiles = @($changedFiles | Sort-Object -Unique)

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

    Assert-True `
        (-not (Select-String -Path $runtimePath -Pattern 'NotImplementedError' -Quiet)) `
        'Evidence Runtime retains NotImplementedError'
    $fakeSourcePattern = 'api_response|webpage|direct_observation'
    Assert-True `
        (-not (Select-String -Path $runtimePath -Pattern $fakeSourcePattern -Quiet)) `
        'Evidence Runtime constructs a forbidden source kind'
    $transportPattern = (
        'requ' + 'ests\.|urllib\.request|http\.' + 'client|' +
        'socket\.|Invoke-' + 'WebRequest|Invoke-' + 'RestMethod'
    )
    Assert-True `
        (-not (Select-String -Path $runtimePath -Pattern $transportPattern -Quiet)) `
        'Network transport implementation found in Evidence Runtime'
}

function Invoke-UnittestGate {
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
        'tests.test_wu3_evidence_runtime'
    )
    $result = Invoke-CapturedProcess `
        -FilePath $pythonExe `
        -Arguments $arguments `
        -Label 'WU3-ER complete offline suite'
    Assert-True ($result.ExitCode -eq 0) "Unittest gate exited $($result.ExitCode)"
    Assert-True `
        ($result.Combined -match 'Ran\s+192\s+tests?') `
        'Unittest gate did not report exactly 192 tests'
    Assert-True `
        ($result.Combined -match '(?m)^OK\s*$') `
        'Unittest gate did not report OK'
}

function Invoke-RuntimeGate {
    $token = [Guid]::NewGuid().ToString('N')
    $tempScript = Join-Path `
        ([IO.Path]::GetTempPath()) `
        "trip-decider-wu3-verify-$token.py"
    $pythonCode = @'
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from unittest.mock import patch

root = Path(os.environ["TRIP_DECIDER_WU3_VERIFY_ROOT"])
venv = (root / ".venv").resolve()
executable = Path(sys.executable).resolve()
prefix = Path(sys.prefix).resolve()
if executable != (venv / "Scripts" / "python.exe").resolve():
    raise RuntimeError("interpreter is outside project venv")
if prefix != venv:
    raise RuntimeError("sys.prefix is outside project venv")
site_paths = [
    Path(item).resolve()
    for item in sys.path
    if "site-packages" in item.lower()
]
if not site_paths or any(venv not in item.parents for item in site_paths):
    raise RuntimeError("site-packages is outside project venv")

from trip_decider.evidence_runtime import run_evidence_runtime
from trip_decider.fixture_validation import validate_fixture_directory
from trip_decider.recovery import run_wu2_recovery
from trip_decider.schema_validation import validate_schema_registry

schema_paths = tuple(sorted((root / "schemas").glob("*.schema.json")))
if len(schema_paths) != 11:
    raise RuntimeError("schema count changed")
registry = validate_schema_registry(schema_paths)
if registry.problems or registry.value is None:
    raise RuntimeError("schema registry failed")
fixtures = validate_fixture_directory(root / "fixtures", registry.value)
if fixtures.problems or fixtures.value is None:
    raise RuntimeError("fixture validation failed")
counts = (
    fixtures.value.fixture_count,
    fixtures.value.document_count,
    fixtures.value.dirty_case_count,
)
if counts != (7, 40, 7):
    raise RuntimeError("fixture surface changed")

anchor = root / "fixtures" / "jiangxi_multi_identity_smoke"
with tempfile.TemporaryDirectory() as temp:
    temp_root = Path(temp)
    recovery_root = temp_root / "recovery"
    recovery = run_wu2_recovery(anchor, recovery_root)
    if recovery.problems or recovery.value is None:
        raise RuntimeError("offline recovery failed")
    with (
        patch("urllib.request.urlopen") as urlopen_mock,
        patch("http.client.HTTPConnection.request") as http_mock,
        patch("socket.socket.connect") as socket_mock,
    ):
        first = run_evidence_runtime(recovery_root, temp_root / "first")
        second = run_evidence_runtime(recovery_root, temp_root / "second")
    attempts = (
        urlopen_mock.call_count
        + http_mock.call_count
        + socket_mock.call_count
    )
    if attempts != 0:
        raise RuntimeError("network was attempted")
    if first.problems or first.value is None:
        raise RuntimeError("first Evidence Runtime failed")
    if second.problems or second.value is None:
        raise RuntimeError("second Evidence Runtime failed")
    filenames = ("evidence.json", "evidence-gate.json", "run-summary.json")
    if [
        (temp_root / "first" / name).read_bytes() for name in filenames
    ] != [
        (temp_root / "second" / name).read_bytes() for name in filenames
    ]:
        raise RuntimeError("runtime output is not deterministic")

    evidence = json.loads(
        (temp_root / "first" / "evidence.json").read_text(encoding="utf-8")
    )
    gate = json.loads(
        (temp_root / "first" / "evidence-gate.json").read_text(
            encoding="utf-8"
        )
    )
    summary = json.loads(
        (temp_root / "first" / "run-summary.json").read_text(encoding="utf-8")
    )
    facts = evidence["payload"]["facts"]
    if len(facts) != 28:
        raise RuntimeError("fact count changed")
    for fact in facts:
        if (
            fact["support_status"] != "unknown"
            or fact["derivation"] != "rule_derived"
            or fact["freshness"]["status"] != "unknown"
            or fact["sources"] != []
            or fact["display_status"] != "unknown"
            or fact["conflict_source_refs"] != []
            or fact["derivation_detail"]["input_fact_ids"] != []
        ):
            raise RuntimeError("fact support ceiling changed")
    identity_counts = Counter(
        item["identity_status"] for item in gate["seed_results"]
    )
    generation_counts = Counter(
        item["generation_status"] for item in gate["seed_results"]
    )
    if identity_counts != Counter(
        {"matched": 2, "ambiguous": 1, "unmatched": 1}
    ):
        raise RuntimeError("identity accounting changed")
    if generation_counts != Counter(
        {
            "ELIGIBLE": 2,
            "BLOCKED_IDENTITY_AMBIGUOUS": 1,
            "BLOCKED_IDENTITY_UNMATCHED": 1,
        }
    ):
        raise RuntimeError("evidence gate changed")
    if gate["generation_allowed"] is not False:
        raise RuntimeError("anchor generation gate must remain false")
    if (
        summary["candidate_count"] != 7
        or summary["complete_candidate_count"] != 7
        or summary["incomplete_candidate_count"] != 0
        or summary["eligible_seed_count"] != 2
        or summary["blocked_seed_count"] != 2
        or summary["network_attempts"] != 0
        or summary["completion_status"] != "completed"
    ):
        raise RuntimeError("runtime summary changed")

print(json.dumps({
    "candidate_count": 7,
    "dirty_cases": counts[2],
    "documents": counts[1],
    "evidence_facts": 28,
    "fixtures": counts[0],
    "generation_allowed": False,
    "network_attempts": 0,
    "outputs": 3,
    "schemas": len(schema_paths),
}, sort_keys=True))
'@
    $encoding = New-Object Text.UTF8Encoding($false)
    try {
        [IO.File]::WriteAllText($tempScript, $pythonCode, $encoding)
        $result = Invoke-CapturedProcess `
            -FilePath $pythonExe `
            -Arguments @($tempScript) `
            -Label 'WU3-ER runtime verification'
        Assert-True ($result.ExitCode -eq 0) 'Runtime verification failed'
        Assert-True `
            ($result.Stdout -match '"generation_allowed": false') `
            'Runtime verification did not report blocked global gate'
    } finally {
        if (Test-Path -LiteralPath $tempScript) {
            Remove-Item -LiteralPath $tempScript -Force
        }
    }
}

try {
    Set-Location $repoRoot
    Assert-True `
        ((git rev-parse --is-inside-work-tree) -eq 'true') `
        'Not inside project Git worktree'
    Assert-True ((git branch --show-current) -eq 'main') 'Branch is not main'
    git merge-base --is-ancestor $startHead HEAD
    Assert-True ($LASTEXITCODE -eq 0) 'Approved start HEAD is not an ancestor'
    Assert-True ((git remote | Measure-Object).Count -eq 0) 'Remote was added'
    Assert-True ((git stash list | Measure-Object).Count -eq 0) 'Stash remains'

    Assert-True `
        (Test-Path -LiteralPath $pythonExe -PathType Leaf) `
        'Project .venv Python is missing'
    Assert-True `
        ((Resolve-Path -LiteralPath $pythonExe).Path -eq
            [IO.Path]::GetFullPath(
                (Join-Path $repoRoot '.venv\Scripts\python.exe')
            )) `
        'Python does not resolve to project .venv'

    $env:PYTHONPATH = Join-Path $repoRoot 'src'
    $env:TRIP_DECIDER_WU3_VERIFY_ROOT = $repoRoot

    Assert-ScopeAndCommits
    Assert-FrozenInputs
    Assert-LockedEnvironment
    Assert-Scans
    Invoke-RuntimeGate
    Invoke-UnittestGate

    $residue = @(
        Get-ChildItem `
            -LiteralPath ([IO.Path]::GetTempPath()) `
            -Filter 'trip-decider-wu3-verify-*' `
            -Force `
            -ErrorAction SilentlyContinue
    )
    Assert-True ($residue.Count -eq 0) 'WU3 verification residue remains'

    Write-Output (
        'WU3-ER verification PASS: tests=192 schemas=11 ' +
        'fixtures=7 documents=40 dirty_cases=7 evidence_facts=28 ' +
        'outputs=3 generation_allowed=false network_attempts=0 ' +
        'temporary_residue=0'
    )
    exit 0
} catch {
    [Console]::Error.WriteLine("WU3-ER verification FAIL: $($_.Exception.Message)")
    exit 1
} finally {
    $env:PYTHONPATH = $oldPythonPath
    $env:TRIP_DECIDER_WU3_VERIFY_ROOT = $oldVerifyRoot
}
