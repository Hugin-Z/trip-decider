[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$startHead = '49394356c9fd81f951d439336d6243dc7d9452e9'
$approvedPlanHash = '815D399A6F30D0993DAB699FF73F0BC0F8F0BF62F8E812EA0C4586133A2A258E'
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
$oldPythonPath = $env:PYTHONPATH
$oldVerifyRoot = $env:TRIP_DECIDER_VERIFY_ROOT

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

    $path = Join-Path $repoRoot $RelativePath
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
    $stdoutPath = Join-Path ([IO.Path]::GetTempPath()) "trip-decider-$token.stdout"
    $stderrPath = Join-Path ([IO.Path]::GetTempPath()) "trip-decider-$token.stderr"
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
        [string[]]$Arguments,

        [Parameter(Mandatory = $true)]
        [int]$ExpectedCount,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    $result = Invoke-CapturedProcess `
        -FilePath $pythonExe `
        -Arguments $Arguments `
        -Label $Label
    Assert-True ($result.ExitCode -eq 0) "$Label exited $($result.ExitCode)"
    Assert-True `
        ($result.Combined -match "Ran\s+$ExpectedCount\s+tests?") `
        "$Label did not report exactly $ExpectedCount tests"
    Assert-True `
        ($result.Combined -match '(?m)^OK\s*$') `
        "$Label did not report OK"
}

function Get-FixtureTreeHash {
    $fixtureRoot = Join-Path $repoRoot 'fixtures'
    $files = @(Get-ChildItem -LiteralPath $fixtureRoot -Recurse -File | Sort-Object FullName)
    $lines = @(
        foreach ($file in $files) {
            $relative = $file.FullName.Substring($repoRoot.Length + 1).Replace('\', '/')
            $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
            "$relative`t$hash"
        }
    )
    $text = ($lines -join "`n") + "`n"
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($text)
        $digest = $sha.ComputeHash($bytes)
    } finally {
        $sha.Dispose()
    }
    return (-join ($digest | ForEach-Object { $_.ToString('X2') }))
}

try {
    Set-Location $repoRoot

    Assert-True ((git rev-parse --is-inside-work-tree) -eq 'true') 'Not inside the project Git worktree'
    Assert-True ((git branch --show-current) -eq 'main') 'WU1C must run on main'
    git merge-base --is-ancestor $startHead HEAD
    Assert-True ($LASTEXITCODE -eq 0) 'WU1C start HEAD is not an ancestor of HEAD'
    Assert-True ((git remote | Measure-Object).Count -eq 0) 'WU1C must not add a remote'
    Assert-True ((git stash list | Measure-Object).Count -eq 0) 'WU1C must not create a stash'

    Assert-True (Test-Path -LiteralPath $pythonExe -PathType Leaf) 'Project .venv Python is missing'
    $resolvedPython = (Resolve-Path -LiteralPath $pythonExe).Path
    $expectedPython = [IO.Path]::GetFullPath((Join-Path $repoRoot '.venv\Scripts\python.exe'))
    Assert-True ($resolvedPython -eq $expectedPython) 'Python does not resolve to project .venv'

    $env:PYTHONPATH = (Join-Path $repoRoot 'src')
    $env:TRIP_DECIDER_VERIFY_ROOT = $repoRoot

    $helperPath = Join-Path `
        ([IO.Path]::GetTempPath()) `
        ("trip-decider-wu1c-" + [Guid]::NewGuid().ToString('N') + '.py')
    $helperCode = @'
import json
import os
import site
import sys
from pathlib import Path

from trip_decider.fixture_validation import validate_fixture_directory
from trip_decider.schema_validation import validate_schema_registry

root = Path(os.environ["TRIP_DECIDER_VERIFY_ROOT"]).resolve()
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
if (
    summary.fixture_count != 6
    or summary.document_count != 38
    or summary.dirty_case_count != 6
):
    raise RuntimeError("fixture surface changed")

print(
    json.dumps(
        {
            "python": str(executable),
            "prefix": str(prefix),
            "schemas": len(schema_paths),
            "artifact_schemas": len(registry.artifact_schema_ids),
            "fixtures": summary.fixture_count,
            "documents": summary.document_count,
            "dirty_cases": summary.dirty_case_count,
        },
        sort_keys=True,
    )
)
'@

    try {
        $utf8NoBom = New-Object Text.UTF8Encoding($false)
        [IO.File]::WriteAllText($helperPath, $helperCode, $utf8NoBom)
        $helperResult = Invoke-CapturedProcess `
            -FilePath $pythonExe `
            -Arguments @($helperPath) `
            -Label 'registry and fixture gate'
        Assert-True ($helperResult.ExitCode -eq 0) 'Registry and fixture gate failed'
        $summaryLine = @(
            $helperResult.Stdout -split "`r?`n" |
            Where-Object { $_.Trim().StartsWith('{') }
        ) | Select-Object -Last 1
        Assert-True (-not [string]::IsNullOrWhiteSpace($summaryLine)) 'Registry summary JSON is missing'
        $summary = $summaryLine | ConvertFrom-Json
        Assert-True ($summary.schemas -eq 11) 'Registry summary schema count changed'
        Assert-True ($summary.fixtures -eq 6) 'Registry summary fixture count changed'
        Assert-True ($summary.documents -eq 38) 'Registry summary document count changed'
        Assert-True ($summary.dirty_cases -eq 6) 'Registry summary dirty-case count changed'
    } finally {
        Remove-Item -LiteralPath $helperPath -Force -ErrorAction SilentlyContinue
    }

    Invoke-UnittestGate `
        -Arguments @(
            '-m',
            'unittest',
            'tests.test_schema_validation',
            'tests.test_fixture_validation',
            'tests.wu1c_contract_compatibility_cases',
            '-v'
        ) `
        -ExpectedCount 115 `
        -Label 'WU1C explicit suite'

    Invoke-UnittestGate `
        -Arguments @(
            '-m',
            'unittest',
            'discover',
            '-s',
            'tests',
            '-p',
            'test*.py',
            '-v'
        ) `
        -ExpectedCount 82 `
        -Label 'WU1 default discovery'

    $frozenHashes = [ordered]@{
        'PLAN.md' = '563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456'
        'docs/architecture.md' = 'CA5B6F7D345E11623C94C13CDD73C0E774282AFD88F9E2E036035ED2396BB6F4'
        'docs/artifact-contracts.md' = '695C0AC6738B71852DC60ADAFD2A98B974C5EC65BB744D19B0E22EC3550497BF'
        'docs/reviews/work-unit-1-review.md' = 'C3E7CCF3D0F1A0181AD36E0435FCC481E56E3B3DAF42A921DB4E2E7EC72A659E'
        'docs/reviews/work-unit-1-remediation-review.md' = 'C7769D8DFEF0AE636D992475E40DB6C7E4498AB084B32B571D10BE8574256FF0'
        'plans/work-unit-1-contract-remediation.md' = $approvedPlanHash
        'src/trip_decider/schema_validation.py' = '2061084E8AC27DF4C08F63DC264A2612685980D966AA5291A46660BE3F1CC017'
        'src/trip_decider/fixture_validation.py' = '6C720C5F4D72356F2909854E6C1B605B891BC40787A4D87739CCA69C2590EBBF'
        'src/trip_decider/verification_entry.py' = 'E5698D276AC23B9A12DA8CB7943750AC5F45CC8C248B582A67A0DC18CE8F6D0E'
        'scripts/verify_wu1.ps1' = 'E20DE35F7597070C7554702421241ADD7809B4CDC3DC2034DC072274C243656B'
        'tests/test_schema_validation.py' = 'A4075DC19E2D923E25862D589DA4DA83AEE39B2D2355BF9B553683C7E24C0DAA'
        'tests/test_fixture_validation.py' = 'E748784A658FFD098A97269F7C3864A9CFB6612839207640A0CA0B900908BC7B'
        'tests/wu1r_verify_entry_cases.py' = '2F4213F7789C18C15E0FDAA0D4012834D4325E97DA9221C4E64F9D571F5D1900'
        'pyproject.toml' = 'FD6622AA930E4BFA5986F26274EFA42B2512089050B716F445006C8EB98EA995'
        'requirements.lock' = 'BFE485EFB4105DC01C475D21EFB7858FD8468A69EBD0056363FBD9C84E6C6927'
    }
    foreach ($item in $frozenHashes.GetEnumerator()) {
        Assert-FileHash -RelativePath $item.Key -Expected $item.Value
    }

    $fixtureTreeHash = Get-FixtureTreeHash
    Assert-True `
        ($fixtureTreeHash -eq '4860AD9409671EDFA8FAF5E51AF781E33762691F0CE09D0A4FF96738A252FB86') `
        'Frozen fixture tree hash changed'

    $allowedPaths = @(
        'plans/work-unit-1-contract-remediation.md',
        'docs/real-world-source-policy.md',
        'docs/real-world-contract-extension.md',
        'schemas/common.schema.json',
        'schemas/candidates.schema.json',
        'schemas/fixture-case.schema.json',
        'tests/wu1c_contract_compatibility_cases.py',
        'scripts/verify_wu1c.ps1',
        'docs/reviews/work-unit-1-contract-remediation-review.md'
    )
    $requiredPaths = $allowedPaths[0..7]
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
        Assert-True (-not $path.Contains(' -> ')) 'Renamed paths are outside WU1C scope'
        [void]$pathSet.Add($path)
    }
    foreach ($path in $pathSet) {
        Assert-True ($allowedPaths -contains $path) "Path outside WU1C whitelist: $path"
    }
    foreach ($path in $requiredPaths) {
        Assert-True ($pathSet.Contains($path)) "Required WU1C path is missing: $path"
    }

    $expectedMessages = @(
        'docs: record approved WU1 contract remediation plan',
        'docs: define real-world source and replay policy',
        'docs: define candidate and location compatibility extension',
        'test: add failing real-world contract compatibility cases',
        'feat: extend candidate location and fixture source contracts',
        'chore: add WU1C verification entry',
        'docs: prepare WU1 contract remediation review'
    )
    $actualMessages = @(git log --reverse --format='%s' "$startHead..HEAD")
    Assert-True `
        ($actualMessages.Count -ge 5 -and $actualMessages.Count -le 7) `
        'WU1C commit count is outside the C0-C6 prefix'
    for ($index = 0; $index -lt $actualMessages.Count; $index += 1) {
        Assert-True `
            ($actualMessages[$index] -eq $expectedMessages[$index]) `
            "WU1C commit message mismatch at index $index"
    }

    $scanTargets = @(
        (Join-Path $repoRoot 'schemas\common.schema.json'),
        (Join-Path $repoRoot 'schemas\candidates.schema.json'),
        (Join-Path $repoRoot 'schemas\fixture-case.schema.json'),
        (Join-Path $repoRoot 'tests\wu1c_contract_compatibility_cases.py')
    )
    $forbiddenLogic = 'infer_|guess_|default_when_missing|silent_fallback|warning_as_pass'
    $commercialEndpoints = 'lbs\.amap\.com|restapi\.amap\.com|lbsyun\.baidu\.com|api\.map\.baidu\.com|lbs\.qq\.com|apis\.map\.qq\.com'
    $realAnchorNames = '婺源|上饶|三清山|江西'
    Assert-True `
        (-not (Select-String -Path $scanTargets -Pattern $forbiddenLogic -Quiet)) `
        'Fallback or guessing token found in executable WU1C contract surface'
    Assert-True `
        (-not (Select-String -Path $scanTargets -Pattern $commercialEndpoints -Quiet)) `
        'Commercial map endpoint found in executable WU1C contract surface'
    Assert-True `
        (-not (Select-String -Path $scanTargets -Pattern $realAnchorNames -Quiet)) `
        'Real Jiangxi anchor name found in WU1C structural surface'

    $secretTargets = @(
        foreach ($path in $pathSet) {
            $fullPath = Join-Path $repoRoot $path
            if (Test-Path -LiteralPath $fullPath -PathType Leaf) {
                $fullPath
            }
        }
    )
    $secretPatterns = @(
        '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----',
        '(?i)(AMAP|GAODE|BAIDU|TENCENT|QQ)[_-]?(KEY|AK|SECRET)\s*[:=]\s*[''"][A-Za-z0-9_-]{8,}',
        '(?i)(password|token|secret)\s*[:=]\s*[''"][A-Za-z0-9_-]{12,}'
    )
    foreach ($pattern in $secretPatterns) {
        Assert-True `
            (-not (Select-String -Path $secretTargets -Pattern $pattern -Quiet)) `
            'Potential secret pattern found in WU1C path'
    }

    $schemaCount = @(Get-ChildItem -LiteralPath (Join-Path $repoRoot 'schemas') -Filter '*.schema.json' -File).Count
    Assert-True ($schemaCount -eq 11) 'Schema file count changed'
    Assert-True `
        ((Select-String -Path (Join-Path $repoRoot 'tests\wu1c_contract_compatibility_cases.py') -Pattern '^    def test_' | Measure-Object).Count -eq 33) `
        'WU1C test method count changed'

    Write-Output 'WU1C verification PASS: schemas=11 explicit_tests=115 default_tests=82 fixtures=6 documents=38 dirty_cases=6 criteria=18'
    exit 0
} catch {
    [Console]::Error.WriteLine("WU1C verification FAIL: $($_.Exception.Message)")
    exit 1
} finally {
    $env:PYTHONPATH = $oldPythonPath
    $env:TRIP_DECIDER_VERIFY_ROOT = $oldVerifyRoot
    Set-Location $repoRoot
}
