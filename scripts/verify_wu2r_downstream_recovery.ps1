[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$startHead = '276221d860950e6940d344fe2889312104da4290'
$approvedPlanHash = '1D671D9C1777755305526A05F82CEBB4279D4B9FA743762A0769C825E4770F8D'
$recoveryHash = '870FB097B4E9059D7D5DCCAD41A4522B31AB79ACBA7DC961BAD40970E8DB6511'
$testHash = '1CEAD6C418A19789C0AEABDE2E5CBC461D436D074256A73948B89580D0815E09'
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
$oldPythonPath = $env:PYTHONPATH
$oldVerifyRoot = $env:TRIP_DECIDER_DOR_VERIFY_ROOT

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
    $stdoutPath = Join-Path $tempRoot "trip-decider-dor-verify-$token.stdout"
    $stderrPath = Join-Path $tempRoot "trip-decider-dor-verify-$token.stderr"
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
        'plans/work-unit-2r-downstream-offline-recovery.md',
        'src/trip_decider/recovery.py',
        'tests/test_wu2r_downstream_recovery.py',
        'scripts/verify_wu2r_downstream_recovery.ps1',
        'docs/reviews/work-unit-2r-downstream-offline-recovery-review.md'
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
            "Path outside WU2R-DOR whitelist: $path"
    }
    foreach ($required in $allowedPaths[0..3]) {
        Assert-True `
            ($pathSet.Contains($required)) `
            "Required WU2R-DOR path missing: $required"
    }

    $expectedMessages = @(
        'docs: record downstream offline recovery plan',
        'test: add failing downstream recovery cases',
        'feat: implement downstream offline recovery',
        'chore: add downstream recovery verification entry',
        'docs: prepare downstream offline recovery review'
    )
    $messages = @(git log --reverse --format='%s' "$startHead..HEAD")
    Assert-True `
        ($messages.Count -ge 3 -and $messages.Count -le 5) `
        'WU2R-DOR commit count is outside the approved sequence'
    for ($index = 0; $index -lt $messages.Count; $index += 1) {
        Assert-True `
            ($messages[$index] -eq $expectedMessages[$index]) `
            "WU2R-DOR commit mismatch at index $index"
    }
    if ($messages.Count -eq 5) {
        Assert-True `
            ($pathSet.Contains($allowedPaths[4])) `
            'Final Review path is missing'
    }
}

function Assert-Scans {
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

    $recoveryPath = Join-Path $repoRoot 'src\trip_decider\recovery.py'
    Assert-True `
        (-not (Select-String -Path $recoveryPath -Pattern 'NotImplementedError' -Quiet)) `
        'Recovery public implementation retains NotImplementedError'
    $transportPattern = (
        'requ' + 'ests\.|http\.' + 'client|Invoke-' + 'WebRequest|' +
        'Invoke-' + 'RestMethod|cu' + 'rl\.exe'
    )
    Assert-True `
        (-not (Select-String -Path $recoveryPath -Pattern $transportPattern -Quiet)) `
        'Network transport implementation found in Recovery'
    $providerPattern = (
        'nom' + 'inatim|os' + 'rm|restapi\.' + 'amap|' +
        'api\.map\.' + 'baidu|apis\.map\.' + 'qq|maps\.' + 'google'
    )
    Assert-True `
        (-not (Select-String -Path $recoveryPath -Pattern $providerPattern -Quiet)) `
        'Forbidden provider token found in Recovery'
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
        'tests.test_wu2r_downstream_recovery'
    )
    $result = Invoke-CapturedProcess `
        -FilePath $pythonExe `
        -Arguments $arguments `
        -Label 'WU2R-DOR complete offline suite'
    Assert-True ($result.ExitCode -eq 0) "Unittest gate exited $($result.ExitCode)"
    Assert-True `
        ($result.Combined -match 'Ran\s+186\s+tests?') `
        'Unittest gate did not report exactly 186 tests'
    Assert-True `
        ($result.Combined -match '(?m)^OK\s*$') `
        'Unittest gate did not report OK'
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
    $resolvedPython = (Resolve-Path -LiteralPath $pythonExe).Path
    $expectedPython = [IO.Path]::GetFullPath(
        (Join-Path $repoRoot '.venv\Scripts\python.exe')
    )
    Assert-True `
        ($resolvedPython -eq $expectedPython) `
        'Python does not resolve to project .venv'

    $env:PYTHONPATH = Join-Path $repoRoot 'src'
    $env:TRIP_DECIDER_DOR_VERIFY_ROOT = $repoRoot
    Assert-LockedEnvironment

    $frozenHashes = [ordered]@{
        'docs/reviews/work-unit-2r-resume-review.md' = 'BF4AEC6B68CF69EB9DA04E2119E0AD5F3880B610A41CC8418CFF8D64CDA6E365'
        'docs/wu2r-resume-acquisition-decision.md' = 'DFA53FF72699752DCEE18B1E5BB736479F1351B24E705A55A24C2A9FB13A6CE0'
        'docs/wu2-recovery-source-and-capture.md' = 'B34ED5EB0FA570A11E0B43E9F0A714C30F4A44FC53EE3D5D38302074B1DE9CA1'
        'src/trip_decider/resume_acquisition.py' = '86229BA52695D3B4725DFDB54D709C8D79580DD35B8FCEE010D3AD59B7D0A6AE'
        'src/trip_decider/acquisition_evidence.py' = 'BF7F25FC4A41C8085431450501B86866A7757B125A208363AA5113AD5F82FEDB'
        'src/trip_decider/adapters/open_data_poi.py' = 'F39EBF86B682EDECF182F6148178AEBA434A287B34A270FE84D3FAEE8F80944B'
        'tests/test_wu2_recovery.py' = '8D1341E4A57EA008152059A670CF4876EA48E8D118DF6E82EF15850549E4F43E'
        'tests/test_wu2r_resume.py' = '88F0CD41F69BCDB535798B8329AFD02297F305E7DE95FCE5F73F219941953B01'
        'fixtures/jiangxi_multi_identity_smoke/README.md' = '49049A94B0DF039C430506BBA9827B599F417CF3A97AEB069D3099AEE9F59223'
        'fixtures/jiangxi_multi_identity_smoke/case.json' = '6052797C4FE43B0E1BE216187EAD6AC10FB1617F07CD7784CF81F8403843F3C8'
        'fixtures/jiangxi_multi_identity_smoke/replay.json' = '5D8086E128FE1B33FD0314151C49256A459DB401233B1C548843791AFAC1919A'
        'fixtures/jiangxi_multi_identity_smoke/osm-pois.json' = '41520443BB370919F184CF46441DB897A809EB1B86119B7CF2B6007F20A5B382'
        'requirements.lock' = 'BFE485EFB4105DC01C475D21EFB7858FD8468A69EBD0056363FBD9C84E6C6927'
        'pyproject.toml' = 'FD6622AA930E4BFA5986F26274EFA42B2512089050B716F445006C8EB98EA995'
        '.gitignore' = 'A6F5AFD044D06F8E04D1CC9DDE26B25D186A0CE9046C0ED50F7ADF734E5FC2A7'
        'plans/work-unit-2r-downstream-offline-recovery.md' = $approvedPlanHash
        'src/trip_decider/recovery.py' = $recoveryHash
        'tests/test_wu2r_downstream_recovery.py' = $testHash
    }
    foreach ($item in $frozenHashes.GetEnumerator()) {
        Assert-FileHash -RelativePath $item.Key -Expected $item.Value
    }

    $schemaHashes = [ordered]@{
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
    foreach ($item in $schemaHashes.GetEnumerator()) {
        Assert-FileHash -RelativePath $item.Key -Expected $item.Value
    }

    $handbook = '<handbook>'
    Assert-True (Test-Path -LiteralPath $handbook -PathType Container) 'Handbook missing'
    $handbookHead = git -C $handbook rev-parse HEAD
    $handbookOrigin = git -C $handbook rev-parse origin/main
    Assert-True `
        ($handbookHead -eq '6502e423ad2a1ab30db7f805e8ebc8fb31fc500b') `
        'Handbook local HEAD changed'
    Assert-True ($handbookOrigin -eq $handbookHead) 'Handbook origin/main changed'
    Assert-True `
        ((git -C $handbook rev-list --left-right --count HEAD...origin/main) -eq "0`t0") `
        'Handbook ahead/behind changed'
    Assert-True `
        ((git -C $handbook status --short | Measure-Object).Count -eq 0) `
        'Handbook worktree changed'

    Assert-ScopeAndCommits
    Assert-Scans

    $helperPath = Join-Path `
        ([IO.Path]::GetTempPath()) `
        ("trip-decider-dor-verify-" + [Guid]::NewGuid().ToString('N') + '.py')
    $helperCode = @'
import hashlib
import inspect
import json
import os
import re
import site
import socket
import sys
import tempfile
import urllib.request
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from trip_decider.fixture_validation import validate_fixture_directory
from trip_decider.recovery import run_wu2_recovery
from trip_decider.schema_validation import validate_schema_registry

root = Path(os.environ["TRIP_DECIDER_DOR_VERIFY_ROOT"]).resolve()
venv = (root / ".venv").resolve()
executable = Path(sys.executable).resolve()
prefix = Path(sys.prefix).resolve()

def inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False

if not inside(executable, venv):
    raise RuntimeError("interpreter is outside project .venv")
if not inside(prefix, venv):
    raise RuntimeError("sys.prefix is outside project .venv")
for package_path in site.getsitepackages():
    if not inside(Path(package_path).resolve(), venv):
        raise RuntimeError("site-packages is outside project .venv")

schema_paths = tuple(sorted((root / "schemas").glob("*.schema.json")))
registry_result = validate_schema_registry(schema_paths)
if registry_result.problems or registry_result.value is None:
    raise RuntimeError("schema registry validation failed")
registry = registry_result.value
if len(schema_paths) != 11 or len(registry.artifact_schema_ids) != 9:
    raise RuntimeError("schema registry count changed")
if not registry.fixture_schema_id:
    raise RuntimeError("fixture schema registry entry is missing")

fixture_result = validate_fixture_directory(root / "fixtures", registry)
if fixture_result.problems or fixture_result.value is None:
    raise RuntimeError("fixture validation failed")
fixture_summary = fixture_result.value
fixture_counts = (
    fixture_summary.fixture_count,
    fixture_summary.document_count,
    fixture_summary.dirty_case_count,
)
if fixture_counts != (7, 40, 7):
    raise RuntimeError("fixture surface changed")

fixture = root / "fixtures" / "jiangxi_multi_identity_smoke"
case = json.loads((fixture / "case.json").read_text(encoding="utf-8"))
replay = json.loads((fixture / "replay.json").read_text(encoding="utf-8"))
raw = (fixture / "osm-pois.json").read_bytes()
source = (root / "docs" / "wu2-recovery-source-and-capture.md").read_text(
    encoding="utf-8"
)
query_matches = re.findall(
    r"Exact UTF-8 query:\n\n```text\n(.*?)```",
    source,
    flags=re.DOTALL,
)
if len(query_matches) != 1:
    raise RuntimeError("frozen query block is not unique")
query_bytes = query_matches[0].encode("utf-8")
request_bytes = urlencode(
    {"data": query_matches[0]},
    encoding="utf-8",
    errors="strict",
).encode("ascii")
if hashlib.sha256(query_bytes).hexdigest().upper() != replay["query_sha256"]:
    raise RuntimeError("query hash mismatch")
if hashlib.sha256(request_bytes).hexdigest().upper() != replay["request_sha256"]:
    raise RuntimeError("request hash mismatch")
if hashlib.sha256(raw).hexdigest().upper() != replay["response_sha256"]:
    raise RuntimeError("response hash mismatch")
if case["root_artifact_id"] != replay["expected"]["candidate_artifact_id"]:
    raise RuntimeError("anchor root identity mismatch")

function_source = inspect.getsource(run_wu2_recovery)
for forbidden in (
    "normalize_open_data_pois",
    "stable_identifier",
    "stable_artifact_id",
    "ingest_candidate_pool",
):
    if forbidden in function_source:
        raise RuntimeError("run_wu2_recovery duplicates an upstream responsibility")
if "replay_wu2r_resume_anchor" not in function_source:
    raise RuntimeError("run_wu2_recovery does not delegate Resume replay")

with tempfile.TemporaryDirectory(prefix="trip-decider-dor-verify-") as temp:
    output_root = Path(temp) / "output"
    with (
        patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("network forbidden"),
        ) as socket_network,
        patch.object(
            urllib.request,
            "urlopen",
            side_effect=AssertionError("network forbidden"),
        ) as url_network,
    ):
        result = run_wu2_recovery(fixture, output_root)
    if result.problems or result.value is None:
        raise RuntimeError("real offline Recovery replay failed")
    if socket_network.call_count + url_network.call_count != 0:
        raise RuntimeError("offline Recovery attempted network")
    filenames = sorted(path.name for path in output_root.iterdir())
    expected_filenames = sorted(
        (
            "candidates.json",
            "seed-accounting.json",
            "record-local-facts.json",
            "run-summary.json",
        )
    )
    if filenames != expected_filenames:
        raise RuntimeError("Recovery output set changed")
    summary_path = output_root / "run-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("completion_status") != "completed":
        raise RuntimeError("Recovery completion marker is missing")
    if summary.get("network_attempts") != 0:
        raise RuntimeError("Recovery summary network count changed")
    if summary.get("candidate_count") != 7:
        raise RuntimeError("Recovery candidate count changed")
    if summary.get("seed_status_counts") != {
        "matched": 2,
        "ambiguous": 1,
        "unmatched": 1,
    }:
        raise RuntimeError("Recovery seed counts changed")
    if summary.get("output_paths") != {
        "candidate_artifact_path": "candidates.json",
        "seed_accounting_path": "seed-accounting.json",
        "record_local_facts_path": "record-local-facts.json",
        "run_summary_path": "run-summary.json",
    }:
        raise RuntimeError("Recovery logical output paths changed")
    for filename, expected_hash in summary["output_sha256"].items():
        actual_hash = hashlib.sha256((output_root / filename).read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise RuntimeError("installed output hash mismatch")
    if dict(result.value.output_sha256) != summary["output_sha256"]:
        raise RuntimeError("returned output hashes differ from disk summary")
    if result.value.network_attempts != 0:
        raise RuntimeError("returned network count changed")

print(json.dumps({
    "candidate_count": 7,
    "dirty_cases": fixture_counts[2],
    "documents": fixture_counts[1],
    "fixtures": fixture_counts[0],
    "network_attempts": 0,
    "output_files": 4,
    "schemas": len(schema_paths),
}, sort_keys=True))
'@
    try {
        $utf8NoBom = New-Object Text.UTF8Encoding($false)
        [IO.File]::WriteAllText($helperPath, $helperCode, $utf8NoBom)
        $helperResult = Invoke-CapturedProcess `
            -FilePath $pythonExe `
            -Arguments @($helperPath) `
            -Label 'environment, schema, fixture, and Recovery gate'
        Assert-True `
            ($helperResult.ExitCode -eq 0) `
            'Environment/schema/fixture/Recovery gate failed'
    } finally {
        if (Test-Path -LiteralPath $helperPath) {
            Remove-Item -LiteralPath $helperPath -Force
        }
    }

    Invoke-UnittestGate

    Assert-True `
        (@(
            Get-ChildItem `
                -LiteralPath ([IO.Path]::GetTempPath()) `
                -Filter 'trip-decider-dor-verify-*' `
                -Force
        ).Count -eq 0) `
        'Unexpected WU2R-DOR system-temp residue'
    Assert-True `
        (@(
            Get-ChildItem -LiteralPath $repoRoot -Recurse -File -Force |
            Where-Object { $_.Name -match '^\..+\.[0-9a-f]{32}\.tmp$' }
        ).Count -eq 0) `
        'Unexpected repository atomic-temp residue'

    Write-Output (
        'WU2R-DOR verification PASS: tests=186 schemas=11 ' +
        'fixtures=7 documents=40 dirty_cases=7 outputs=4 ' +
        'network_attempts=0 temporary_residue=0'
    )
    exit 0
} catch {
    [Console]::Error.WriteLine(
        "WU2R-DOR verification FAIL: $($_.Exception.Message)"
    )
    exit 1
} finally {
    $env:PYTHONPATH = $oldPythonPath
    $env:TRIP_DECIDER_DOR_VERIFY_ROOT = $oldVerifyRoot
    Set-Location $repoRoot
}
