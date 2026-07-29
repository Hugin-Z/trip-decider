[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
$powerShellExe = Join-Path $PSHOME 'powershell.exe'
$startHead = '91ee1a0c7c29a9ac03a270d35ad5ea983ea86ce7'
$runToken = [Guid]::NewGuid().ToString('N')
$runRoot = Join-Path (
    [IO.Path]::GetTempPath()
) "trip-decider-wu6-$runToken-run"
$temporaryArtifacts = New-Object 'System.Collections.Generic.List[string]'

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
    $stdoutPath = Join-Path $tempRoot "trip-decider-wu6-$token.stdout"
    $stderrPath = Join-Path $tempRoot "trip-decider-wu6-$token.stderr"
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
    ) "trip-decider-wu6-$runToken-$([Guid]::NewGuid().ToString('N')).py"
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

function Invoke-TemporaryPowerShell {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Code,

        [Parameter(Mandatory = $true)]
        [string]$Label,

        [string[]]$ScriptArguments = @()
    )

    $scriptPath = Join-Path (
        [IO.Path]::GetTempPath()
    ) "trip-decider-wu6-$runToken-$([Guid]::NewGuid().ToString('N')).ps1"
    $temporaryArtifacts.Add($scriptPath)
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    try {
        [IO.File]::WriteAllText($scriptPath, $Code, $utf8NoBom)
        return Invoke-CapturedProcess `
            -FilePath $powerShellExe `
            -Arguments (
                @(
                    '-NoProfile',
                    '-ExecutionPolicy',
                    'Bypass',
                    '-File',
                    $scriptPath
                ) + $ScriptArguments
            ) `
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
executable = Path(sys.executable).resolve()
prefix = Path(sys.prefix).resolve()
site_paths = tuple(Path(value).resolve() for value in site.getsitepackages())
assert executable == (venv / "Scripts" / "python.exe").resolve()
assert prefix == venv
assert site_paths
assert all(venv == path or venv in path.parents for path in site_paths)

def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()

raw_lock = (repo / "requirements.lock").read_bytes()
assert not raw_lock.startswith(b"\xef\xbb\xbf")
expected = {}
for line in raw_lock.decode("utf-8", errors="strict").splitlines():
    assert line and line.count("==") == 1
    name, version = line.split("==", 1)
    key = normalized(name)
    assert key not in expected
    expected[key] = version

actual = {}
locations = {}
for distribution in importlib.metadata.distributions():
    name = distribution.metadata["Name"]
    if not name:
        continue
    key = normalized(name)
    if key in {"pip", "setuptools"}:
        continue
    assert key not in actual
    actual[key] = distribution.version
    locations[key] = Path(distribution.locate_file("")).resolve()
assert actual == expected
assert all(venv == path or venv in path.parents for path in locations.values())
print(json.dumps({
    "executable_in_project_venv": True,
    "lock_packages": len(expected),
    "prefix_in_project_venv": True,
    "site_packages_in_project_venv": True,
}, sort_keys=True))
'@
    $origin = Invoke-TemporaryPython `
        -Code $code `
        -Label 'WU6 venv and exact lock'
    Assert-True ($origin.ExitCode -eq 0) 'Venv or exact lock check failed'

    $pipCheck = Invoke-CapturedProcess `
        -FilePath $pythonExe `
        -Arguments @('-m', 'pip', 'check') `
        -Label 'WU6 pip check'
    Assert-True ($pipCheck.ExitCode -eq 0) 'pip check failed'
}

function Assert-FrozenInputs {
    $hashes = [ordered]@{
        'plans/work-unit-6-portfolio-packaging.md' = '415AA4B45A22D2C7F2947D1C3BD56A4E1FA2174D011B4093B71DBD669E8DFA24'
        'README.md' = '88BCAD43CAB71E3531AB3B45A3F73E6B874869F3B521131687D0ABB007F9ED14'
        'scripts/run_wuyuan_demo.ps1' = 'A8C40539F639E0E0118DFE39C6C86C7D9B32A7A272A680CDFE4D54F21C6EE14C'
        'examples/wuyuan-two-day/request.yaml' = 'EE1E8BAEF43868757FE8A7B4BB4A3C0148C4FB81241C2D91DF23E26A6D4F23F1'
        'examples/wuyuan-two-day/constraint-parse.json' = 'DF5B1D9809E628CD1B1B8F7D3056D11E03691EB654C89420549DDB57E0F69898'
        'examples/wuyuan-two-day/constraints.yaml' = '769BFC565DBBD0BDA555AA0F91DCD97A272F34CF696B71321DA868B688C51EC2'
        'PLAN.md' = '563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456'
        'pyproject.toml' = 'FD6622AA930E4BFA5986F26274EFA42B2512089050B716F445006C8EB98EA995'
        'requirements.lock' = 'BFE485EFB4105DC01C475D21EFB7858FD8468A69EBD0056363FBD9C84E6C6927'
        'src/trip_decider/e2e_demo.py' = 'BA934DE551056533DBDBE59BC51B007DDA9272C4DF2A8FC300C31A6E8040C6C7'
        'src/trip_decider/recovery.py' = 'C0E098DD4AB997727A0EFBCCC9C396AC480DEEB3477DBF4CDCB5E31A34E0D8BA'
        'src/trip_decider/evidence_runtime.py' = '626D052F068537D050D350E8404948286670405D0B75C2E793CAA71656C89C04'
        'src/trip_decider/coarse_planner.py' = '8098F75190E279419D704E9135B896DE84D88691D4B2A942142671C870E25D8C'
        'tests/test_wu4_coarse_planner.py' = '1A9A090F32E9C785F36034A23B66D76F0173EDA95069882F514E3AFCE4C289E4'
        'tests/test_wu5_e2e_demo.py' = 'DCA808033245AE055AA46F6E10434F238ECFF3460735AE183EF8A97A21AD15B2'
        'fixtures/jiangxi_multi_identity_smoke/case.json' = '6052797C4FE43B0E1BE216187EAD6AC10FB1617F07CD7784CF81F8403843F3C8'
        'fixtures/jiangxi_multi_identity_smoke/osm-pois.json' = '41520443BB370919F184CF46441DB897A809EB1B86119B7CF2B6007F20A5B382'
        'fixtures/jiangxi_multi_identity_smoke/README.md' = '49049A94B0DF039C430506BBA9827B599F417CF3A97AEB069D3099AEE9F59223'
        'fixtures/jiangxi_multi_identity_smoke/replay.json' = '5D8086E128FE1B33FD0314151C49256A459DB401233B1C548843791AFAC1919A'
    }
    foreach ($entry in $hashes.GetEnumerator()) {
        Assert-FileHash -RelativePath $entry.Key -Expected $entry.Value
    }

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
    Assert-True ($schemaHashes.Count -eq 11) 'Schema hash map is not 11'
    foreach ($entry in $schemaHashes.GetEnumerator()) {
        Assert-FileHash -RelativePath $entry.Key -Expected $entry.Value
    }
    $actualSchemas = @(
        Get-ChildItem `
            -LiteralPath (Join-Path $repoRoot 'schemas') `
            -Filter '*.schema.json' `
            -File
    )
    Assert-True ($actualSchemas.Count -eq 11) 'Schema file count is not 11'
}

function Assert-ScopeAndHistory {
    $branch = (& git -C $repoRoot branch --show-current).Trim()
    Assert-True ($branch -eq 'main') 'Branch is not main'
    Assert-True (@(& git -C $repoRoot remote).Count -eq 0) 'Git remotes exist'
    Assert-True (@(& git -C $repoRoot stash list).Count -eq 0) 'Git stashes exist'

    $allowed = @(
        'plans/work-unit-6-portfolio-packaging.md',
        'README.md',
        'examples/wuyuan-two-day/request.yaml',
        'examples/wuyuan-two-day/constraint-parse.json',
        'examples/wuyuan-two-day/constraints.yaml',
        'scripts/run_wuyuan_demo.ps1',
        'scripts/verify_wu6_portfolio_packaging.ps1',
        'docs/reviews/work-unit-6-portfolio-packaging-review.md'
    )
    $preReview = @($allowed | Where-Object {
        $_ -ne 'docs/reviews/work-unit-6-portfolio-packaging-review.md'
    })
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
        Assert-True ($allowed -contains $path) "Path outside WU6 scope: $path"
    }
    foreach ($path in $preReview) {
        Assert-True ($observed.Contains($path)) "Missing WU6 package path: $path"
    }
    Assert-True `
        ($observed.Count -eq 7 -or $observed.Count -eq 8) `
        'WU6 path count is not in the C3-C4 verification window'

    $expectedMessages = @(
        'docs: record WU6 portfolio packaging plan',
        'feat: add reproducible Wuyuan demo package',
        'docs: add portfolio README',
        'chore: add portfolio packaging verification',
        'docs: prepare WU6 portfolio packaging review'
    )
    $actualMessages = @(
        & git -C $repoRoot log --reverse --format='%s' "$startHead..HEAD"
    )
    Assert-True `
        ($actualMessages.Count -ge 3 -and $actualMessages.Count -le 5) `
        'WU6 commit count is outside the C3-C4 verification window'
    for ($index = 0; $index -lt $actualMessages.Count; $index++) {
        Assert-True `
            ($actualMessages[$index] -eq $expectedMessages[$index]) `
            "WU6 commit message mismatch at index $index"
    }
    if ($actualMessages.Count -eq 5) {
        Assert-True ($observed.Count -eq 8) 'Final WU6 scope is not eight paths'
    }

    $committedCheck = Invoke-CapturedProcess `
        -FilePath 'git' `
        -Arguments @('-C', $repoRoot, 'diff', '--check', "$startHead..HEAD") `
        -Label 'WU6 committed diff check'
    Assert-True ($committedCheck.ExitCode -eq 0) 'Committed diff check failed'
    $workingCheck = Invoke-CapturedProcess `
        -FilePath 'git' `
        -Arguments @('-C', $repoRoot, 'diff', '--check') `
        -Label 'WU6 working diff check'
    Assert-True ($workingCheck.ExitCode -eq 0) 'Working diff check failed'
}

function Assert-ReadmeAndPackageText {
    $code = @'
import re
import sys
from pathlib import Path

repo = Path(sys.argv[1]).resolve()
readme_path = repo / "README.md"
raw = readme_path.read_bytes()
assert not raw.startswith(b"\xef\xbb\xbf")
text = raw.decode("utf-8", errors="strict")
assert not re.search(r"(?i)(?:[a-z]:[\\/]|file://)", text)
assert "http://" not in text and "https://" not in text
assert "Hugin" not in text and "Codex" not in text
required = (
    "# trip-decider",
    "Day 1",
    "Day 2",
    "\u6c5f\u5cad",
    "\u674e\u5751",
    "identity ambiguous",
    "unmatched",
    "publishable=false",
    "Python `>=3.11,<3.12`",
    "requirements.lock",
    "$demoRoot = Join-Path $env:TEMP 'trip-decider-wuyuan-demo'",
    "Remove-Item -LiteralPath $demoRoot -Recurse -Force",
    "-File .\\scripts\\run_wuyuan_demo.ps1",
    "-OpenReport",
    "tests\uff1a210",
    "schemas\uff1a11",
    "7 / 40 / 7",
    "0 / 0",
    "no_plan_found != proven_infeasible",
    "\u4e0d\u662f\u6700\u4f73\u8def\u7ebf\u3001\u5b8c\u6574\u65c5\u6e38\u653b\u7565\u6216\u53ef\u76f4\u63a5\u53d1\u5e03\u7684\u884c\u7a0b",
    "\u4e0d\u58f0\u79f0\u652f\u6301\u4efb\u610f\u57ce\u5e02",
)
for token in required:
    assert token in text, repr(token)
for forbidden in (
    "\u667a\u80fd\u63a8\u8350\u6700\u4f73\u8def\u7ebf",
    "\u5df2\u652f\u6301\u4efb\u610f\u57ce\u5e02",
    "Evidence\u5df2\u6838\u5b9e",
):
    assert forbidden not in text
links = re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", text)
assert len(links) == 6
for link in links:
    assert not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", link)
    target = (repo / link).resolve()
    assert target == repo or repo in target.parents
    assert target.exists(), link
assert text.count("```mermaid") == 1

demo = (repo / "scripts" / "run_wuyuan_demo.ps1").read_text(
    encoding="utf-8"
)
for token in (
    ".venv\\Scripts\\python.exe",
    "trip_decider.e2e_demo",
    "fixtures\\jiangxi_multi_identity_smoke",
    "examples\\wuyuan-two-day",
    "finally",
    "$env:PYTHONPATH = $previousPythonPath",
    "Remove-Item Env:PYTHONPATH",
):
    assert token in demo
for forbidden in (
    "Invoke-Expression",
    "powershell -Command",
    "python -c",
    "demo-output",
    "Remove-Item -LiteralPath $checkedOutputRoot",
):
    assert forbidden not in demo

secret = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret)"
    r"\s*[:=]\s*['\"][A-Za-z0-9_-]{8,}"
)
paths = (
    "README.md",
    "plans/work-unit-6-portfolio-packaging.md",
    "examples/wuyuan-two-day/request.yaml",
    "examples/wuyuan-two-day/constraint-parse.json",
    "examples/wuyuan-two-day/constraints.yaml",
    "scripts/run_wuyuan_demo.ps1",
)
for relative in paths:
    assert not secret.search((repo / relative).read_text(encoding="utf-8"))
print("README_LINKS=6")
print("README_AND_PACKAGE_TEXT=PASS")
'@
    $result = Invoke-TemporaryPython `
        -Code $code `
        -Label 'WU6 README and package text audit' `
        -ScriptArguments @($repoRoot)
    Assert-True ($result.ExitCode -eq 0) 'README or package text audit failed'
}

function Invoke-DemoAndAssertions {
    Assert-True (-not (Test-Path -LiteralPath $runRoot)) 'WU6 run root exists'
    [void][IO.Directory]::CreateDirectory($runRoot)
    $demoScript = Join-Path $repoRoot 'scripts\run_wuyuan_demo.ps1'
    $successRoot = Join-Path $runRoot 'success-output'

    $successWrapper = @'
param(
    [Parameter(Mandatory = $true)]
    [string]$DemoScript,
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot
)
$ErrorActionPreference = "Stop"
$sentinel = "wu6-success-pythonpath-sentinel"
$env:PYTHONPATH = $sentinel
& $DemoScript -OutputRoot $OutputRoot
$code = $LASTEXITCODE
if ($code -ne 0) {
    exit $code
}
if (-not (Test-Path Env:PYTHONPATH)) {
    throw "PYTHONPATH presence was not restored after success."
}
if ($env:PYTHONPATH -cne $sentinel) {
    throw "PYTHONPATH value was not restored after success."
}
Write-Output "WU6_PYTHONPATH_SUCCESS_RESTORED=true"
'@
    $success = Invoke-TemporaryPowerShell `
        -Code $successWrapper `
        -Label 'WU6 real demo and success environment restoration' `
        -ScriptArguments @($demoScript, $successRoot)
    Assert-True ($success.ExitCode -eq 0) 'Real demo script failed'
    Assert-True `
        ([string]::IsNullOrEmpty($success.Stderr)) `
        'Real demo wrote stderr'
    $successLines = @(
        $success.Stdout -split "\r?\n" |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    Assert-True ($successLines.Count -eq 2) 'Real demo stdout line count mismatch'
    Assert-True `
        ($successLines[0] -eq (
            'status=conditionally_feasible scheduled=2 blocked=2 ' +
            'publishable=false report=report/index.html'
        )) `
        'Real demo safe status line mismatch'
    Assert-True `
        ($successLines[1] -eq 'WU6_PYTHONPATH_SUCCESS_RESTORED=true') `
        'Success environment restoration marker mismatch'

    $failureRoot = Join-Path $runRoot 'existing-output'
    [void][IO.Directory]::CreateDirectory($failureRoot)
    $markerPath = Join-Path $failureRoot 'marker.txt'
    [IO.File]::WriteAllText(
        $markerPath,
        'preserve',
        (New-Object System.Text.UTF8Encoding($false))
    )
    $failureWrapper = @'
param(
    [Parameter(Mandatory = $true)]
    [string]$DemoScript,
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot
)
$ErrorActionPreference = "Stop"
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
$caught = $false
try {
    & $DemoScript -OutputRoot $OutputRoot
} catch {
    $caught = $true
}
if (-not $caught) {
    throw "Injected existing-root failure did not fail."
}
if (Test-Path Env:PYTHONPATH) {
    throw "Absent PYTHONPATH was not restored after injected failure."
}
Write-Output "WU6_PYTHONPATH_FAILURE_RESTORED=true"
'@
    $failure = Invoke-TemporaryPowerShell `
        -Code $failureWrapper `
        -Label 'WU6 injected failure environment restoration' `
        -ScriptArguments @($demoScript, $failureRoot)
    Assert-True ($failure.ExitCode -eq 0) 'Injected failure wrapper failed'
    Assert-True `
        ($failure.Stdout.Trim() -eq 'WU6_PYTHONPATH_FAILURE_RESTORED=true') `
        'Failure environment restoration marker mismatch'
    Assert-True `
        ([string]::IsNullOrEmpty($failure.Stderr)) `
        'Injected failure wrapper wrote stderr'
    Assert-True `
        ([IO.File]::ReadAllText($markerPath, [Text.Encoding]::UTF8) -eq 'preserve') `
        'Existing output marker was modified'
    Assert-True `
        (@(Get-ChildItem -LiteralPath $failureRoot -Force).Count -eq 1) `
        'Existing output root gained partial files'

    $checker = @'
import hashlib
import json
import sys
from pathlib import Path

from trip_decider.schema_validation import (
    BundleClosure,
    load_document,
    validate_bundle,
    validate_schema_registry,
)

repo = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2]).resolve()
example = repo / "examples" / "wuyuan-two-day"
expected_hashes = {
    "request.yaml": "EE1E8BAEF43868757FE8A7B4BB4A3C0148C4FB81241C2D91DF23E26A6D4F23F1",
    "constraint-parse.json": "DF5B1D9809E628CD1B1B8F7D3056D11E03691EB654C89420549DDB57E0F69898",
    "constraints.yaml": "769BFC565DBBD0BDA555AA0F91DCD97A272F34CF696B71321DA868B688C51EC2",
}
registry_result = validate_schema_registry(
    tuple(sorted((repo / "schemas").glob("*.schema.json")))
)
assert not registry_result.problems and registry_result.value is not None
loaded = []
for name, artifact_type in (
    ("request.yaml", "request"),
    ("constraint-parse.json", "constraint-parse"),
    ("constraints.yaml", "constraints"),
):
    path = example / name
    first = path.read_bytes()
    second = path.read_bytes()
    assert first == second
    assert not first.startswith(b"\xef\xbb\xbf")
    assert str(repo).encode("utf-8") not in first
    assert hashlib.sha256(first).hexdigest().upper() == expected_hashes[name]
    result = load_document(path, expected_artifact_type=artifact_type)
    assert not result.problems and result.value is not None
    loaded.append(result.value)
root_id = "urn:uuid:93d97ccf-c2ce-4c63-9db5-2722024705a8"
bundle = validate_bundle(
    loaded,
    registry_result.value,
    closure=BundleClosure.CLOSED,
    root_artifact_id=root_id,
)
assert not bundle.problems and bundle.value is not None
assert bundle.value.root_artifact_id == root_id
assert len(bundle.value.validated_artifact_ids) == 3
assert len(bundle.value.resolved_artifact_ids) == 3

expected_files = (
    "evidence/evidence-gate.json",
    "evidence/evidence.json",
    "evidence/run-summary.json",
    "planning/plan.json",
    "planning/planning-gate.json",
    "planning/run-summary.json",
    "planning/violations.json",
    "recovery/candidates.json",
    "recovery/record-local-facts.json",
    "recovery/run-summary.json",
    "recovery/seed-accounting.json",
    "report/index.html",
    "run-summary.json",
)
files = tuple(sorted(
    path.relative_to(output).as_posix()
    for path in output.rglob("*")
    if path.is_file()
))
assert files == expected_files

request = loaded[0].data
expected_ref = {
    "artifact_id": request["artifact_id"],
    "artifact_type": request["artifact_type"],
    "payload_sha256": request["integrity"]["payload_sha256"],
    "schema_version": request["schema_version"],
}
candidates = json.loads(
    (output / "recovery" / "candidates.json").read_text(encoding="utf-8")
)
assert candidates["payload"]["request_ref"] == expected_ref
constraints = loaded[2].data
assert constraints["payload"]["user_edit_policy"] == {
    "constraints_are_solver_ssot": True,
    "request_auto_overwrite": False,
}

summary = json.loads((output / "run-summary.json").read_text(encoding="utf-8"))
assert summary["result"] == {
    "blocked_count": 2,
    "draft_created": True,
    "generation_allowed_input": False,
    "planning_status": "conditionally_feasible",
    "publishable": False,
    "scheduled_count": 2,
}
assert summary["network_attempts"] == 0
assert summary["llm_calls"] == 0

raw_html = (output / "report" / "index.html").read_bytes()
assert not raw_html.startswith(b"\xef\xbb\xbf")
html = raw_html.decode("utf-8", errors="strict")
for token in (
    "\u7b2c1\u5929\uff1a\u6c5f\u5cad",
    "\u7b2c2\u5929\uff1a\u674e\u5751",
    "\u7bc1\u5cad",
    "\u5e86\u6e90",
    "support_status: unknown",
    "display_status: unknown",
    "publishable: false",
    "generation_allowed_input: false",
):
    assert token in html
for forbidden in (
    "\u8fd9\u662f\u6700\u4f73\u8def\u7ebf",
    "\u8bc1\u636e\u5df2\u6838\u5b9e",
    "publishable: true",
    "generation_allowed_input: true",
    "<script",
    "<img",
    "http://",
    "https://",
):
    assert forbidden not in html.lower()

fixtures = 0
documents = 0
dirty_cases = 0
for directory in sorted((repo / "fixtures").iterdir()):
    case_path = directory / "case.json"
    if not case_path.is_file():
        continue
    case = json.loads(case_path.read_text(encoding="utf-8"))
    fixtures += 1
    documents += len(case["documents"])
    dirty_cases += len(case["dirty_cases"])
assert (fixtures, documents, dirty_cases) == (7, 40, 7)
assert len(tuple((repo / "schemas").glob("*.schema.json"))) == 11

print(json.dumps({
    "bundle_documents": 3,
    "candidate_request_ref": "exact",
    "dirty_cases": dirty_cases,
    "documents": documents,
    "fixtures": fixtures,
    "llm_calls": summary["llm_calls"],
    "network_attempts": summary["network_attempts"],
    "outputs": len(files),
    "schemas": 11,
}, sort_keys=True))
'@
    $checked = Invoke-TemporaryPython `
        -Code $checker `
        -Label 'WU6 independent package and output matrix' `
        -ScriptArguments @($repoRoot, $successRoot)
    Assert-True ($checked.ExitCode -eq 0) 'Package or output matrix failed'
}

function Assert-FullRegression {
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
        'tests.test_wu5_e2e_demo'
    )
    $result = Invoke-ProjectPython `
        -Arguments (@('-m', 'unittest') + $modules + @('-v')) `
        -Label 'WU6 complete offline regression'
    Assert-True ($result.ExitCode -eq 0) 'Full regression failed'
    Assert-True `
        ($result.Combined -match 'Ran 210 tests') `
        'Full regression count is not 210'
    Assert-True `
        ($result.Combined -match '(?m)^OK\s*$') `
        'Full regression did not report OK'
}

$hadNoBytecode = Test-Path Env:PYTHONDONTWRITEBYTECODE
$previousNoBytecode = if ($hadNoBytecode) {
    (Get-Item Env:PYTHONDONTWRITEBYTECODE).Value
} else {
    $null
}
$completed = $false
try {
    $env:PYTHONDONTWRITEBYTECODE = '1'
    Assert-Environment
    Assert-FrozenInputs
    Assert-ScopeAndHistory
    Assert-ReadmeAndPackageText
    Invoke-DemoAndAssertions
    Assert-FullRegression
    $completed = $true
} finally {
    if (Test-Path -LiteralPath $runRoot) {
        Remove-Item -LiteralPath $runRoot -Recurse -Force
    }
    foreach ($path in $temporaryArtifacts) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force
        }
    }
    if ($hadNoBytecode) {
        $env:PYTHONDONTWRITEBYTECODE = $previousNoBytecode
    } else {
        Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue
    }
}

Assert-True $completed 'WU6 verification did not complete'
Assert-True (-not (Test-Path -LiteralPath $runRoot)) 'WU6 run root residue'
foreach ($path in $temporaryArtifacts) {
    Assert-True (-not (Test-Path -LiteralPath $path)) "Temp residue: $path"
}

Write-Output 'WU6_PORTFOLIO_PACKAGING_VERIFICATION=PASS'
Write-Output 'checks=20'
Write-Output 'tests=210'
Write-Output 'schemas=11'
Write-Output 'fixtures=7'
Write-Output 'documents=40'
Write-Output 'dirty_cases=7'
Write-Output 'outputs=13'
Write-Output 'network_attempts=0'
Write-Output 'llm_calls=0'
Write-Output 'temporary_residue=0'
