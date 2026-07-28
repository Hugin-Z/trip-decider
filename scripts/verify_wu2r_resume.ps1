[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('PreAcquisition', 'Failure', 'Success')]
    [string]$Mode
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$startHead = 'e93f606d193161bfb1bd245a1e9b5e27282bd9a7'
$approvedPlanHash = 'AAE5DA96F11C367E450522CBAFDD1A7648AD527B42FBFC642C0FCDF355699674'
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
$runtimeRelative = 'runtime/wu2r-failure-evidence/run_wu2r_resume_001/failure-evidence.json'
$runtimePath = Join-Path $repoRoot ($runtimeRelative.Replace('/', '\'))
$fixtureRelative = 'fixtures/jiangxi_multi_identity_smoke'
$fixturePath = Join-Path $repoRoot ($fixtureRelative.Replace('/', '\'))
$decisionPath = Join-Path $repoRoot 'docs\wu2r-resume-acquisition-decision.md'
$oldPythonPath = $env:PYTHONPATH
$oldVerifyRoot = $env:TRIP_DECIDER_VERIFY_ROOT
$oldVerifyMode = $env:TRIP_DECIDER_RESUME_VERIFY_MODE

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
    Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Missing frozen file: $RelativePath"
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
    $stdoutPath = Join-Path ([IO.Path]::GetTempPath()) "trip-decider-resume-verify-$token.stdout"
    $stderrPath = Join-Path ([IO.Path]::GetTempPath()) "trip-decider-resume-verify-$token.stderr"
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
        Remove-Item -LiteralPath $stdoutPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $stderrPath -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-UnittestGate {
    param(
        [Parameter(Mandatory = $true)]
        [int]$ExpectedCount
    )

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
        'tests.test_wu2r_resume'
    )
    $result = Invoke-CapturedProcess `
        -FilePath $pythonExe `
        -Arguments $arguments `
        -Label 'WU2R Resume explicit offline suite'
    Assert-True ($result.ExitCode -eq 0) "WU2R Resume tests exited $($result.ExitCode)"
    Assert-True `
        ($result.Combined -match "Ran\s+$ExpectedCount\s+tests?") `
        "WU2R Resume tests did not report exactly $ExpectedCount tests"
    Assert-True `
        ($result.Combined -match '(?m)^OK\s*$') `
        'WU2R Resume tests did not report OK'
}

function Assert-LockedEnvironment {
    $lockPath = Join-Path $repoRoot 'requirements.lock'
    $expected = @{}
    foreach ($line in Get-Content -LiteralPath $lockPath) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        Assert-True ($line -match '^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)$') "Invalid lock line: $line"
        $name = $matches[1].ToLowerInvariant().Replace('_', '-')
        Assert-True (-not $expected.ContainsKey($name)) "Duplicate locked package: $name"
        $expected[$name] = $matches[2]
    }

    $pipList = Invoke-CapturedProcess `
        -FilePath $pythonExe `
        -Arguments @('-m', 'pip', 'list', '--format=json') `
        -Label 'locked package inventory'
    Assert-True ($pipList.ExitCode -eq 0) 'pip list failed'
    $actual = @{}
    $pipItems = ConvertFrom-Json -InputObject $pipList.Stdout
    foreach ($item in $pipItems) {
        $name = ([string]$item.name).ToLowerInvariant().Replace('_', '-')
        if ($name -in @('pip', 'setuptools')) {
            continue
        }
        Assert-True (-not $actual.ContainsKey($name)) "Duplicate installed package: $name"
        $actual[$name] = [string]$item.version
    }

    Assert-True ($expected.Count -eq $actual.Count) 'Locked and installed package counts differ'
    foreach ($name in $expected.Keys) {
        Assert-True ($actual.ContainsKey($name)) "Locked package is not installed: $name"
        Assert-True ($actual[$name] -eq $expected[$name]) "Locked package version mismatch: $name"
    }

    $pipCheck = Invoke-CapturedProcess `
        -FilePath $pythonExe `
        -Arguments @('-m', 'pip', 'check') `
        -Label 'pip check'
    Assert-True ($pipCheck.ExitCode -eq 0) 'pip check failed'
    Assert-True ($pipCheck.Combined -match 'No broken requirements found') 'pip check did not report a clean environment'
}

function Assert-Scope {
    $allowedPaths = @(
        'plans/work-unit-2r-resume.md',
        'docs/wu2r-resume-acquisition-decision.md',
        'src/trip_decider/resume_acquisition.py',
        'tests/test_wu2r_resume.py',
        'scripts/verify_wu2r_resume.ps1',
        'fixtures/jiangxi_multi_identity_smoke/README.md',
        'fixtures/jiangxi_multi_identity_smoke/case.json',
        'fixtures/jiangxi_multi_identity_smoke/replay.json',
        'fixtures/jiangxi_multi_identity_smoke/osm-pois.json',
        'docs/reviews/work-unit-2r-resume-review.md'
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
        Assert-True (-not $path.Contains(' -> ')) 'Renamed paths are outside WU2R Resume scope'
        [void]$pathSet.Add($path)
    }
    foreach ($path in $pathSet) {
        Assert-True ($allowedPaths -contains $path) "Path outside WU2R Resume whitelist: $path"
    }
    foreach ($required in $allowedPaths[0..4]) {
        Assert-True ($pathSet.Contains($required)) "Required WU2R Resume path is missing: $required"
    }
    if ($Mode -eq 'Success') {
        foreach ($required in $allowedPaths[5..8]) {
            Assert-True ($pathSet.Contains($required)) "Success fixture path is missing: $required"
        }
    } else {
        foreach ($forbidden in $allowedPaths[5..8]) {
            Assert-True (-not $pathSet.Contains($forbidden)) "Non-success mode contains fixture path: $forbidden"
        }
    }
}

function Assert-CommitPrefix {
    $messages = @(git log --reverse --format='%s' "$startHead..HEAD")
    $fixed = @(
        'docs: record approved WU2R resume plan',
        'docs: record WU2R resume acquisition gate',
        'chore: add WU2R resume integration interfaces',
        'test: add failing WU2R resume integration cases',
        'test: correct RI03 candidate order expectation',
        'feat: implement WU2R resume integration',
        'chore: add WU2R resume verification entry'
    )
    Assert-True ($messages.Count -ge 6 -and $messages.Count -le 9) 'WU2R Resume commit count is outside the allowed prefix'
    $fixedCount = [Math]::Min($messages.Count, $fixed.Count)
    for ($index = 0; $index -lt $fixedCount; $index += 1) {
        Assert-True ($messages[$index] -eq $fixed[$index]) "WU2R Resume commit mismatch at index $index"
    }
    if ($messages.Count -ge 8) {
        $expectedOutcome = if ($Mode -eq 'Success') {
            'test: add completed WU2R resume acquisition anchor'
        } elseif ($Mode -eq 'Failure') {
            'docs: record blocked WU2R resume acquisition'
        } else {
            throw 'PreAcquisition mode cannot contain a C6 outcome commit'
        }
        Assert-True ($messages[7] -eq $expectedOutcome) 'WU2R Resume C6 message does not match mode'
    }
    if ($messages.Count -eq 9) {
        Assert-True ($messages[8] -eq 'docs: prepare WU2R resume review') 'WU2R Resume C7 message mismatch'
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
            $candidate = Join-Path $repoRoot ($line.Substring(3).Replace('/', '\'))
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                $changedFiles += $candidate
            }
        }
    }
    $changedFiles = @($changedFiles | Sort-Object -Unique)

    $logicPattern = ('in' + 'fer_|gu' + 'ess_|silent_' + 'fallback|warning_' + 'as_pass|default_when_' + 'missing')
    Assert-True `
        (-not (Select-String -Path $changedFiles -Pattern $logicPattern -Quiet)) `
        'Fallback, guessing, or warning-as-pass token found'

    $secretPatterns = @(
        ('-----BEGIN ' + '(RSA |EC |OPENSSH )?' + 'PRIVATE KEY-----'),
        ('(?i)(AMAP|GAODE|BAIDU|TENCENT|QQ)' + '[_-]?(KEY|AK|SECRET)\s*[:=]\s*[''"]' + '[A-Za-z0-9_-]{8,}'),
        ('(?i)(password|token|secret)' + '\s*[:=]\s*[''"]' + '[A-Za-z0-9_-]{12,}')
    )
    foreach ($pattern in $secretPatterns) {
        Assert-True `
            (-not (Select-String -Path $changedFiles -Pattern $pattern -Quiet)) `
            'Potential secret pattern found in WU2R Resume path'
    }

    $executableTargets = @(
        (Join-Path $repoRoot 'src\trip_decider\resume_acquisition.py'),
        (Join-Path $repoRoot 'tests\test_wu2r_resume.py'),
        (Join-Path $repoRoot 'scripts\verify_wu2r_resume.ps1')
    )
    $transportPattern = ('url' + 'lib\.request|requ' + 'ests\.|Invoke-' + 'WebRequest|Invoke-' + 'RestMethod|cu' + 'rl\.exe|http\.' + 'client')
    Assert-True `
        (-not (Select-String -Path $executableTargets -Pattern $transportPattern -Quiet)) `
        'Network transport implementation found in offline Resume surface'
    $providerPattern = ('nom' + 'inatim|os' + 'rm|restapi\.' + 'amap|api\.map\.' + 'baidu|apis\.map\.' + 'qq|maps\.' + 'google')
    Assert-True `
        (-not (Select-String -Path $executableTargets -Pattern $providerPattern -Quiet)) `
        'Forbidden provider token found in executable Resume surface'
    $rawPattern = ('response_' + 'body|raw_' + 'body|trace' + 'back|exception_' + 'text')
    Assert-True `
        (-not (Select-String -Path $changedFiles -Pattern $rawPattern -Quiet)) `
        'Raw body or exception serialization token found'
}

function Assert-DecisionAndRuntime {
    Assert-True (Test-Path -LiteralPath $decisionPath -PathType Leaf) 'Resume decision is missing'
    $decision = Get-Content -LiteralPath $decisionPath -Raw
    foreach ($token in @(
        'WU2R-resume-001',
        'run_wu2r_resume_001',
        'runtime/wu2r-failure-evidence/run_wu2r_resume_001/failure-evidence.json',
        '5A51E39FFD53FCD1B204AEBD6652CC7267853BD236B4FBA5D807941CFF62993F',
        '6765ABDAA3BBBB4A70F1E28EA7B4A339F81ED7A2F9CCC8B9A4CE8BA1DE275045',
        'UNRECONCILABLE_FROM_DELETED_LEDGER'
    )) {
        Assert-True ($decision.Contains($token)) "Resume decision link is missing: $token"
    }

    $lastLine = @(
        $decision -split "`r?`n" |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    ) | Select-Object -Last 1
    if ($Mode -eq 'PreAcquisition') {
        Assert-True ($lastLine -eq 'READY_TO_ATTEMPT') 'PreAcquisition decision token changed'
        Assert-True (-not (Test-Path -LiteralPath $runtimePath)) 'PreAcquisition must not have a FER ledger'
        Assert-True (-not (Test-Path -LiteralPath $fixturePath)) 'PreAcquisition must not have an anchor fixture'
        return
    }

    $expectedToken = if ($Mode -eq 'Failure') {
        'WU2R_ACQUISITION_BLOCKED_WITH_COMPLETE_EVIDENCE'
    } else {
        'WU2R_ACQUISITION_COMPLETED'
    }
    Assert-True ($lastLine -eq $expectedToken) 'Decision terminal token does not match mode'
    Assert-True (Test-Path -LiteralPath $runtimePath -PathType Leaf) 'Authoritative FER ledger is missing'
    $ledgerRaw = [IO.File]::ReadAllText($runtimePath, [Text.Encoding]::UTF8)
    $ledger = $ledgerRaw | ConvertFrom-Json
    Assert-True ($ledger.run_id -eq 'run_wu2r_resume_001') 'FER run ID mismatch'
    Assert-True ($ledger.request_sha256 -eq '6765abdaa3bbbb4a70f1e28ea7b4a339f81ed7a2f9ccc8b9a4ce8ba1de275045') 'FER request hash mismatch'
    Assert-True (@($ledger.attempts).Count -ge 1) 'FER ledger has no attempt'
    Assert-True ($null -ne $ledger.cleanup.status) 'FER cleanup status is missing'
    Assert-True ($null -ne $ledger.persistence.primary_status) 'FER persistence status is missing'
    Assert-True ($ledgerRaw -notmatch ('response_' + 'body|raw_' + 'body|trace' + 'back|exception_' + 'text|secret')) 'FER ledger contains forbidden content'

    $ledgerHash = (Get-FileHash -LiteralPath $runtimePath -Algorithm SHA256).Hash
    Assert-True ($decision.Contains($ledgerHash)) 'Decision does not contain exact FER ledger hash'
    if ($Mode -eq 'Failure') {
        $codes = @(
            'ACQUISITION_TRANSPORT_FAILURE',
            'ACQUISITION_HTTP_FAILURE',
            'ACQUISITION_RESPONSE_FAILURE',
            'ACQUISITION_LEDGER_FAILURE',
            'ACQUISITION_CLEANUP_FAILURE',
            'ACQUISITION_INTERNAL_FAILURE'
        )
        Assert-True ($ledger.status -eq 'failed') 'Failure ledger status is not failed'
        Assert-True ($codes -contains $ledger.terminal_failure_code) 'Failure ledger terminal code is invalid'
        Assert-True ($decision.Contains([string]$ledger.terminal_failure_code)) 'Decision terminal failure code mismatch'
        Assert-True (-not (Test-Path -LiteralPath $fixturePath)) 'Failure mode must not create an anchor fixture'
    } else {
        Assert-True ($ledger.status -eq 'succeeded') 'Success ledger status is not succeeded'
        Assert-True ($null -eq $ledger.terminal_failure_code) 'Success ledger has a terminal failure'
        Assert-True (Test-Path -LiteralPath $fixturePath -PathType Container) 'Success fixture directory is missing'
    }
}

try {
    Set-Location $repoRoot
    Assert-True ((git rev-parse --is-inside-work-tree) -eq 'true') 'Not inside the project Git worktree'
    Assert-True ((git branch --show-current) -eq 'main') 'WU2R Resume must run on main'
    git merge-base --is-ancestor $startHead HEAD
    Assert-True ($LASTEXITCODE -eq 0) 'WU2R Resume start HEAD is not an ancestor of HEAD'
    Assert-True ((git remote | Measure-Object).Count -eq 0) 'WU2R Resume must not add a remote'
    Assert-True ((git stash list | Measure-Object).Count -eq 0) 'WU2R Resume must not retain a stash'

    Assert-True (Test-Path -LiteralPath $pythonExe -PathType Leaf) 'Project .venv Python is missing'
    $resolvedPython = (Resolve-Path -LiteralPath $pythonExe).Path
    $expectedPython = [IO.Path]::GetFullPath((Join-Path $repoRoot '.venv\Scripts\python.exe'))
    Assert-True ($resolvedPython -eq $expectedPython) 'Python does not resolve to project .venv'

    $env:PYTHONPATH = Join-Path $repoRoot 'src'
    $env:TRIP_DECIDER_VERIFY_ROOT = $repoRoot
    $env:TRIP_DECIDER_RESUME_VERIFY_MODE = $Mode

    Assert-LockedEnvironment

    $helperPath = Join-Path `
        ([IO.Path]::GetTempPath()) `
        ("trip-decider-resume-verify-" + [Guid]::NewGuid().ToString('N') + '.py')
    $helperCode = @'
import json
import os
import site
import sys
from pathlib import Path

from trip_decider.fixture_validation import validate_fixture_directory
from trip_decider.schema_validation import validate_schema_registry

root = Path(os.environ["TRIP_DECIDER_VERIFY_ROOT"]).resolve()
mode = os.environ["TRIP_DECIDER_RESUME_VERIFY_MODE"]
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
if len(schema_paths) != 11:
    raise RuntimeError("schema count changed")
if len(registry.artifact_schema_ids) != 9:
    raise RuntimeError("artifact schema registry count changed")
if not registry.fixture_schema_id:
    raise RuntimeError("fixture schema registry entry is missing")

fixture_result = validate_fixture_directory(root / "fixtures", registry)
if fixture_result.problems or fixture_result.value is None:
    raise RuntimeError("fixture validation failed")
summary = fixture_result.value
expected = (7, 40, 7) if mode == "Success" else (6, 38, 6)
actual = (summary.fixture_count, summary.document_count, summary.dirty_case_count)
if actual != expected:
    raise RuntimeError("fixture surface changed")

for case_path in sorted((root / "fixtures").glob("*/case.json")):
    case = json.loads(case_path.read_text(encoding="utf-8"))
    if case.get("bundle_closure") != "closed":
        raise RuntimeError("fixture closure is not closed")

if mode == "Success":
    fixture = root / "fixtures" / "jiangxi_multi_identity_smoke"
    replay = json.loads((fixture / "replay.json").read_text(encoding="utf-8"))
    raw = (fixture / "osm-pois.json").read_bytes()
    import hashlib
    if replay.get("schema_version") != "wu2r-resume-replay/1.0":
        raise RuntimeError("replay version mismatch")
    if replay.get("network_required") is not False:
        raise RuntimeError("replay is not offline")
    raw_control = replay.get("raw_response")
    if not isinstance(raw_control, dict):
        raise RuntimeError("raw response control is missing")
    if raw_control.get("relative_path") != "osm-pois.json":
        raise RuntimeError("raw response path mismatch")
    if raw_control.get("bytes") != len(raw):
        raise RuntimeError("raw response byte count mismatch")
    if raw_control.get("sha256", "").lower() != hashlib.sha256(raw).hexdigest():
        raise RuntimeError("raw response hash mismatch")
    if replay.get("run_id") != "run_wu2r_resume_001":
        raise RuntimeError("replay run ID mismatch")
    if replay.get("attempt_group_id") != "WU2R-resume-001":
        raise RuntimeError("replay attempt group mismatch")
    if replay.get("query_sha256", "").upper() != "5A51E39FFD53FCD1B204AEBD6652CC7267853BD236B4FBA5D807941CFF62993F":
        raise RuntimeError("replay query hash mismatch")
    if replay.get("request_sha256", "").upper() != "6765ABDAA3BBBB4A70F1E28EA7B4A339F81ED7A2F9CCC8B9A4CE8BA1DE275045":
        raise RuntimeError("replay request hash mismatch")

print(json.dumps({
    "python": str(executable),
    "prefix": str(prefix),
    "schemas": len(schema_paths),
    "artifact_schemas": len(registry.artifact_schema_ids),
    "fixtures": summary.fixture_count,
    "documents": summary.document_count,
    "dirty_cases": summary.dirty_case_count,
}, sort_keys=True))
'@

    try {
        $utf8NoBom = New-Object Text.UTF8Encoding($false)
        [IO.File]::WriteAllText($helperPath, $helperCode, $utf8NoBom)
        $helperResult = Invoke-CapturedProcess `
            -FilePath $pythonExe `
            -Arguments @($helperPath) `
            -Label 'environment, schema, fixture, and replay gate'
        Assert-True ($helperResult.ExitCode -eq 0) 'Environment/schema/fixture gate failed'
    } finally {
        Remove-Item -LiteralPath $helperPath -Force -ErrorAction SilentlyContinue
    }

    $frozenHashes = [ordered]@{
        'docs/reviews/work-unit-2r-failure-evidence-review.md' = '2F6D893C57C70D5B74F432E96CCB72AFCC65F23BA0903BDF6CCDC6DC5D9E0B85'
        'docs/wu2-recovery-source-and-capture.md' = 'B34ED5EB0FA570A11E0B43E9F0A714C30F4A44FC53EE3D5D38302074B1DE9CA1'
        'docs/wu2a-resume-decision.md' = '417F4E89A059CA99A5E96E960B839FA0297935F2438D76B100E7F8F30313B40A'
        'docs/wu2-identity-boundary-decision.md' = '44C1105298AE55FD9B0508B078D4D39124455242F927DAFAAF8E7E2605A77B57'
        'src/trip_decider/recovery.py' = '8105424CAEBD020BDAFBA4048477BF92846AE2B27090CB3EFAFC7C40B6183614'
        'src/trip_decider/acquisition_evidence.py' = 'BF7F25FC4A41C8085431450501B86866A7757B125A208363AA5113AD5F82FEDB'
        'plans/work-unit-2-recovery.md' = 'D6F6C0A662969D5AE810291CE746F4530594DC9C2A0E018C5FC41122AE606AF8'
        'plans/work-unit-2r-failure-evidence-remediation.md' = 'B457E6ECDF2CF6BEAB057BD35D761071AD6100D4926652736E3336726E3C3F95'
        'scripts/acquisition_harness.py' = 'AE6487D7F35E6A1CE351C07FD83DA219214705F1D3AC00611F5D7B9EF49559F9'
        'src/trip_decider/adapters/open_data_poi.py' = 'F39EBF86B682EDECF182F6148178AEBA434A287B34A270FE84D3FAEE8F80944B'
        'tests/test_wu2_recovery.py' = '8D1341E4A57EA008152059A670CF4876EA48E8D118DF6E82EF15850549E4F43E'
        'tests/test_wu2r_failure_evidence.py' = '09894721531AA422B2C87B03B3F4D3104E47A680FA459E16A4AE11A9E4AD684D'
        '.gitignore' = 'A6F5AFD044D06F8E04D1CC9DDE26B25D186A0CE9046C0ED50F7ADF734E5FC2A7'
        'requirements.lock' = 'BFE485EFB4105DC01C475D21EFB7858FD8468A69EBD0056363FBD9C84E6C6927'
        'pyproject.toml' = 'FD6622AA930E4BFA5986F26274EFA42B2512089050B716F445006C8EB98EA995'
        'plans/work-unit-2r-resume.md' = $approvedPlanHash
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

    Assert-Scope
    Assert-CommitPrefix
    Assert-Scans
    Assert-DecisionAndRuntime

    $expectedTests = if ($Mode -eq 'Success') { 180 } else { 175 }
    Invoke-UnittestGate -ExpectedCount $expectedTests

    $runtimeRoot = Join-Path $repoRoot 'runtime'
    if ($Mode -eq 'PreAcquisition') {
        if (Test-Path -LiteralPath $runtimeRoot) {
            Assert-True (@(Get-ChildItem -LiteralPath $runtimeRoot -Recurse -Force).Count -eq 0) 'Unexpected PreAcquisition runtime residue'
        }
    } else {
        $runtimeFiles = @(
            Get-ChildItem -LiteralPath $runtimeRoot -Recurse -File -Force |
            ForEach-Object { $_.FullName.Substring($repoRoot.Length + 1).Replace('\', '/') }
        )
        Assert-True ($runtimeFiles.Count -eq 1) 'Unexpected runtime file count'
        Assert-True ($runtimeFiles[0] -eq $runtimeRelative) 'Unexpected runtime file'
    }
    Assert-True `
        (@(Get-ChildItem -LiteralPath ([IO.Path]::GetTempPath()) -Filter 'trip-decider-wu2r-resume-*' -Force).Count -eq 0) `
        'Unexpected WU2R Resume system-temp residue'
    Assert-True `
        (@(
            Get-ChildItem -LiteralPath $repoRoot -Recurse -File -Force |
            Where-Object { $_.Extension -eq '.tmp' }
        ).Count -eq 0) `
        'Unexpected repository atomic-temp residue'

    $fixtureSummary = if ($Mode -eq 'Success') { 'fixtures=7 documents=40 dirty_cases=7' } else { 'fixtures=6 documents=38 dirty_cases=6' }
    Write-Output "WU2R Resume verification PASS: mode=$Mode tests=$expectedTests schemas=11 $fixtureSummary network_attempts=0"
    exit 0
} catch {
    [Console]::Error.WriteLine("WU2R Resume verification FAIL: $($_.Exception.Message)")
    exit 1
} finally {
    $env:PYTHONPATH = $oldPythonPath
    $env:TRIP_DECIDER_VERIFY_ROOT = $oldVerifyRoot
    $env:TRIP_DECIDER_RESUME_VERIFY_MODE = $oldVerifyMode
    Set-Location $repoRoot
}
