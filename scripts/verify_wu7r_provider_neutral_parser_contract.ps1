[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
$startHead = '5754c1b7117f4dd1604a7529df61ffc5ad2d595c'
$runToken = [Guid]::NewGuid().ToString('N')
$temporaryArtifacts = New-Object 'System.Collections.Generic.List[string]'

$planHash = 'CAF2674C0C0065432291DA6DCAF07A55FE1500ECCEDF10836F93038FB0709D2D'
$runtimeHash = '8FCAD57A8A7EF2F4B7924DE3A4DAE83808C680929B6BD3872144D7372B8B8EF9'
$testHash = '5448FBA20F1F571CD2CF744F1B8F723252061A12C1B0DD9DAE068A954769180F'
$wu7bHash = 'FBB2FA0AE8C59BE44EB8AAF6FE627301D2FAB481137E4DEE022F686449D7006B'
$wu7TestHash = '443905617A067838C9BED34B63308F8F23403A373425E4FE53BEA523840A0962'
$wu7ReviewHash = '42E9902CD8FC8EF6901E990CC9FF7D88002C1358B9DEBC05CD62C89B3148A50E'

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
    $stdoutPath = Join-Path $tempRoot "trip-decider-wu7r-$token.stdout"
    $stderrPath = Join-Path $tempRoot "trip-decider-wu7r-$token.stderr"
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
    ) "trip-decider-wu7r-$runToken-$([Guid]::NewGuid().ToString('N')).py"
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

function Get-Sha256 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RelativePath
    )
    return (
        Get-FileHash `
            -LiteralPath (Join-Path $repoRoot $RelativePath) `
            -Algorithm SHA256
    ).Hash
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
        -Label 'WU7R project venv and exact lock'
    Assert-True ($result.ExitCode -eq 0) 'Venv or lock validation failed'
    $pipCheck = Invoke-CapturedProcess `
        -FilePath $pythonExe `
        -Arguments @('-m', 'pip', 'check') `
        -Label 'WU7R pip check'
    Assert-True ($pipCheck.ExitCode -eq 0) 'pip check failed'
}

function Assert-PlanHash {
    Assert-True `
        ((Get-Sha256 'plans\work-unit-7r-provider-neutral-parser-contract.md') -eq $planHash) `
        'Approved WU7R Plan hash changed'
}

function Assert-ScopeAndHistory {
    Assert-True `
        ((& git -C $repoRoot branch --show-current).Trim() -eq 'main') `
        'Branch is not main'
    Assert-True (@(& git -C $repoRoot remote).Count -eq 0) 'Git remotes exist'
    Assert-True (@(& git -C $repoRoot stash list).Count -eq 0) 'Git stashes exist'

    $wu7bPath = 'plans/work-unit-7b-amap-ephemeral-live.md'
    Assert-True `
        ((Get-Sha256 $wu7bPath) -eq $wu7bHash) `
        'WU7B Plan hash changed'
    $trackedWu7b = @(& git -C $repoRoot ls-files -- $wu7bPath)
    Assert-True ($trackedWu7b.Count -eq 0) 'WU7B Plan became tracked'

    $allowed = @(
        'plans/work-unit-7r-provider-neutral-parser-contract.md',
        'src/trip_decider/live_place_resolution.py',
        'tests/test_wu7r_provider_neutral_parser_contract.py',
        'scripts/verify_wu7r_provider_neutral_parser_contract.ps1',
        'docs/reviews/work-unit-7r-provider-neutral-parser-contract-review.md'
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
            $normalized = $path.Replace('\', '/')
            if ($normalized -ne $wu7bPath) {
                [void]$observed.Add($normalized)
            }
        }
    }
    foreach ($path in $observed) {
        Assert-True ($allowed -contains $path) "Path outside WU7R scope: $path"
    }
    Assert-True `
        ($observed.Count -ge 4 -and $observed.Count -le 5) `
        'WU7R path count is outside the C4-C5 window'

    $expectedMessages = @(
        'docs: record WU7R provider-neutral parser plan',
        'chore: add provider-neutral parser contract interface',
        'test: add failing provider-neutral parser cases',
        'test: correct UTF-8 synthetic compatibility baseline',
        'refactor: implement provider-neutral parser contract',
        'chore: add provider-neutral parser verification',
        'docs: prepare WU7R provider-neutral parser review'
    )
    $actualMessages = @(
        & git -C $repoRoot log --reverse --format='%s' "$startHead..HEAD"
    )
    Assert-True `
        ($actualMessages.Count -ge 5 -and $actualMessages.Count -le 7) `
        'WU7R commit count is outside the C3-C5 window'
    for ($index = 0; $index -lt $actualMessages.Count; $index++) {
        Assert-True `
            ($actualMessages[$index] -eq $expectedMessages[$index]) `
            "WU7R commit message mismatch at index $index"
    }
    if ($actualMessages.Count -eq 7) {
        Assert-True ($observed.Count -eq 5) 'Final WU7R scope is not five paths'
    }

    $diffCheck = Invoke-CapturedProcess `
        -FilePath 'git' `
        -Arguments @('-C', $repoRoot, 'diff', '--check', "$startHead..HEAD") `
        -Label 'WU7R committed diff check'
    Assert-True ($diffCheck.ExitCode -eq 0) 'Committed diff check failed'
    $workCheck = Invoke-CapturedProcess `
        -FilePath 'git' `
        -Arguments @('-C', $repoRoot, 'diff', '--check') `
        -Label 'WU7R working diff check'
    Assert-True ($workCheck.ExitCode -eq 0) 'Working diff check failed'
}

function Assert-ProtectedHashes {
    Assert-True `
        ((Get-Sha256 'src\trip_decider\live_place_resolution.py') -eq $runtimeHash) `
        'WU7R runtime hash changed after C3'
    Assert-True `
        ((Get-Sha256 'tests\test_wu7r_provider_neutral_parser_contract.py') -eq $testHash) `
        'WU7R test hash changed after C2.1'
    Assert-True `
        ((Get-Sha256 'tests\test_wu7_live_place_resolution.py') -eq $wu7TestHash) `
        'Protected WU7 test hash changed'
    Assert-True `
        ((Get-Sha256 'docs\reviews\work-unit-7-live-place-resolution-review.md') -eq $wu7ReviewHash) `
        'Protected WU7 Review hash changed'

    $schemaHashes = @{
        'candidates.schema.json' = '3E29144E1CEE4B300724D1E3DD63EB77DAE1F564135D6AB1B7C9B60F84B0CAB2'
        'common.schema.json' = 'A9134A705C67CF955228A28844AA2C5C42812AA2E0167E1256DB72F0ACAC36D7'
        'constraint-parse.schema.json' = '0D41493B52B6178AEE8DE44B2F3607B193B62C263AD79DEF380B638B22B400A4'
        'constraints.schema.json' = '25069E0DEFBDC03FEA7E92E83EE10F952A31A2B18BDC3678D17786C537EE4473'
        'evidence.schema.json' = '54904C8553BA5223BFB16A2253F1FDBD1FA18CFB77BDB7E5A616C41F24782F8B'
        'fixture-case.schema.json' = '630E57E7F27A660F388407A8FF1B81D851B8B3A047E5B98DCB70E1920177E45A'
        'plan.schema.json' = '81EEB5899C33F19DC6FA059C7D447D747E72E355F3084D925FD9410272389BD3'
        'plan-diff.schema.json' = '37B94FE5E03A73B046D7E6D79BEABF31C4105E50CD54DE520CA6C293AB3E8B43'
        'previous-plan.schema.json' = '59692D17EB79C7EA2D4A2E2866898DD97A0E49B97834EC8AFC5EAB46A80BEDAC'
        'request.schema.json' = 'BC7F46E9A85CE9697F9BA01FF1506A5B56C161F2F6B5140D91FCF0B100762914'
        'violations.schema.json' = 'C117415030993C24649B17837EC2A35C69A2F1CEC7D923742ABD383BA85B394F'
    }
    $schemaFiles = @(
        Get-ChildItem `
            -LiteralPath (Join-Path $repoRoot 'schemas') `
            -File `
            -Filter '*.schema.json'
    )
    Assert-True ($schemaFiles.Count -eq 11) 'Schema count changed'
    foreach ($name in $schemaHashes.Keys) {
        Assert-True `
            ((Get-Sha256 (Join-Path 'schemas' $name)) -eq $schemaHashes[$name]) `
            "Protected Schema hash changed: $name"
    }
}

function Invoke-UnitTestGate {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Modules,

        [Parameter(Mandatory = $true)]
        [int]$ExpectedCount,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )
    $result = Invoke-ProjectPython `
        -Arguments (@('-m', 'unittest') + $Modules + @('-v')) `
        -Label $Label
    Assert-True ($result.ExitCode -eq 0) "$Label failed"
    Assert-True `
        ($result.Combined -match "Ran $ExpectedCount tests?") `
        "$Label test count changed"
}

function Assert-NewContractTests {
    Invoke-UnitTestGate `
        -Modules @('tests.test_wu7r_provider_neutral_parser_contract') `
        -ExpectedCount 4 `
        -Label 'WU7R provider-neutral contract cases'
}

function Assert-Wu7CompatibilityTests {
    Invoke-UnitTestGate `
        -Modules @('tests.test_wu7_live_place_resolution') `
        -ExpectedCount 6 `
        -Label 'WU7 protected compatibility cases'
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
        'tests.test_wu5_e2e_demo',
        'tests.test_wu7_live_place_resolution',
        'tests.test_wu7r_provider_neutral_parser_contract'
    )
    Invoke-UnitTestGate `
        -Modules $modules `
        -ExpectedCount 220 `
        -Label 'WU7R full regression'
}

function Assert-SyntheticCompatibility {
    $code = @'
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]).resolve()))

from tests.test_wu7r_provider_neutral_parser_contract import (
    PRE_REFACTOR_CANDIDATE_SHA256,
    PRE_REFACTOR_TREE_SHA256,
    _SyntheticTransport,
    _poi,
    _structured_input,
    _tree_sha256,
)
from trip_decider.live_place_resolution import run_synthetic_live_place_resolution

seeds = ("\u666f\u70b9\u7532", "\u672a\u5339\u914d")
poi = _poi(
    "SYNTH-AMAP-POI-0001",
    " " + seeds[0] + " ",
    location="120.100000,30.100000",
    typecode="110000",
)
transport = _SyntheticTransport({seeds[0]: (poi,), seeds[1]: ()})
with tempfile.TemporaryDirectory(prefix="trip-decider-wu7r-compat-") as temp:
    output_root = Path(temp) / "output"
    result = run_synthetic_live_place_resolution(
        _structured_input(must_visit=seeds),
        output_root,
        transport,
    )
    assert not result.problems
    files, tree_hash = _tree_sha256(output_root)
    candidate_path = output_root / "resolution" / "candidates.json"
    candidate_bytes = candidate_path.read_bytes()
    candidate_hash = hashlib.sha256(candidate_bytes).hexdigest().upper()
    candidate_count = len(json.loads(candidate_bytes)["payload"]["candidates"])
    assert files == 12
    assert tree_hash == PRE_REFACTOR_TREE_SHA256
    assert candidate_hash == PRE_REFACTOR_CANDIDATE_SHA256
    assert candidate_count == 1
    assert transport.network_attempts == 0
    print("FILES=12")
    print("TREE_SHA256=" + tree_hash)
    print("CANDIDATES_SHA256=" + candidate_hash)
    print("CANDIDATES=1")
    print("NETWORK_CALLS=0")
'@
    $result = Invoke-TemporaryPython `
        -Code $code `
        -Label 'WU7R synthetic compatibility' `
        -ScriptArguments @($repoRoot)
    Assert-True ($result.ExitCode -eq 0) 'Synthetic compatibility changed'
}

function Assert-EphemeralBoundary {
    Invoke-UnitTestGate `
        -Modules @(
            'tests.test_wu7r_provider_neutral_parser_contract.' +
            'ProviderNeutralParserContractCase.' +
            'test_pn02_ephemeral_live_is_memory_only'
        ) `
        -ExpectedCount 1 `
        -Label 'WU7R ephemeral memory-only boundary'
}

function Assert-PolicyMismatchBoundary {
    Invoke-UnitTestGate `
        -Modules @(
            'tests.test_wu7r_provider_neutral_parser_contract.' +
            'ProviderNeutralParserContractCase.' +
            'test_pn03_policy_mismatch_never_infers_or_corrects'
        ) `
        -ExpectedCount 1 `
        -Label 'WU7R policy mismatch boundary'
}

function Assert-NoNetworkSource {
    $code = @'
import re
import sys
from pathlib import Path

runtime = Path(sys.argv[1]).read_text(encoding="utf-8")
network_import = re.compile(
    r"(?m)^\s*(?:from|import)\s+"
    r"(?:aiohttp|httpx|requests|socket|urllib|http\.client)\b"
)
assert not network_import.search(runtime)
assert "restapi.amap.com" not in runtime
assert not re.search(
    r"(?m)^\s*(?:from|import)\s+(?:openai|anthropic)\b",
    runtime,
)
assert not re.search(r"\b(?:chat\.completions|responses\.create)\b", runtime)
print("NETWORK_IMPORTS=0")
print("LLM_CALLS=0")
'@
    $result = Invoke-TemporaryPython `
        -Code $code `
        -Label 'WU7R network and LLM source boundary' `
        -ScriptArguments @(
            (Join-Path $repoRoot 'src\trip_decider\live_place_resolution.py')
        )
    Assert-True ($result.ExitCode -eq 0) 'Network or LLM source boundary failed'
}

function Assert-NoCredentialRead {
    $code = @'
import sys
from pathlib import Path

runtime = Path(sys.argv[1]).read_text(encoding="utf-8")
assert "AMAP_WEB_SERVICE_KEY" not in runtime
assert "os.environ" not in runtime
assert "getenv(" not in runtime
print("CREDENTIAL_READS=0")
'@
    $result = Invoke-TemporaryPython `
        -Code $code `
        -Label 'WU7R credential-read source boundary' `
        -ScriptArguments @(
            (Join-Path $repoRoot 'src\trip_decider\live_place_resolution.py')
        )
    Assert-True ($result.ExitCode -eq 0) 'Credential-read source boundary failed'
}

function Assert-OneSharedCore {
    $code = @'
import inspect
import re
import sys
from pathlib import Path

from trip_decider import live_place_resolution as runtime_module
from trip_decider.live_place_resolution import (
    AmapObservationMode,
    bind_amap_observation_policy,
    run_synthetic_live_place_resolution,
)

runtime = Path(sys.argv[1]).read_text(encoding="utf-8")
assert runtime.count("def parse_amap_district_response") == 1
assert runtime.count("def parse_amap_poi_response") == 1
assert runtime.count("def project_amap_candidates") == 1
assert runtime.count("def _candidate_from_poi") == 1
wrapper_source = inspect.getsource(run_synthetic_live_place_resolution)
prepare_source = inspect.getsource(runtime_module._prepare_and_install)
binding_source = inspect.getsource(runtime_module._bound_provider_responses)
assert "_prepare_and_install" in wrapper_source
assert "parse_amap_district_response" in binding_source
assert "parse_amap_poi_response" in binding_source
assert "project_amap_candidates" in prepare_source
assert tuple(item.value for item in AmapObservationMode) == (
    "synthetic_test",
    "ephemeral_live",
)
mode = inspect.signature(bind_amap_observation_policy).parameters["mode"]
assert mode.kind is inspect.Parameter.KEYWORD_ONLY
assert mode.default is inspect.Parameter.empty
assert "silent_fallback" not in runtime
assert not re.search(r"\b(?:infer|guess)_", runtime)
print("DISTRICT_PARSERS=1")
print("POI_PARSERS=1")
print("CANDIDATE_PROJECTORS=1")
print("MODE_MEMBERS=2")
'@
    $result = Invoke-TemporaryPython `
        -Code $code `
        -Label 'WU7R shared parser and projector boundary' `
        -ScriptArguments @(
            (Join-Path $repoRoot 'src\trip_decider\live_place_resolution.py')
        )
    Assert-True ($result.ExitCode -eq 0) 'Shared parser/projector boundary failed'
}

function Assert-ArtifactCounts {
    $code = @'
import json
import sys
from pathlib import Path

repo = Path(sys.argv[1]).resolve()
schemas = tuple((repo / "schemas").glob("*.schema.json"))
fixture_dirs = sorted(
    path for path in (repo / "fixtures").iterdir()
    if path.is_dir() and (path / "case.json").is_file()
)
documents = 0
dirty_cases = 0
for fixture in fixture_dirs:
    case = json.loads((fixture / "case.json").read_text(encoding="utf-8"))
    documents += len(case["documents"])
    dirty_cases += len(case["dirty_cases"])
assert (len(schemas), len(fixture_dirs), documents, dirty_cases) == (
    11,
    7,
    40,
    7,
)
print("SCHEMAS=11")
print("FIXTURES=7")
print("DOCUMENTS=40")
print("DIRTY_CASES=7")
'@
    $result = Invoke-TemporaryPython `
        -Code $code `
        -Label 'WU7R schema and fixture counts' `
        -ScriptArguments @($repoRoot)
    Assert-True ($result.ExitCode -eq 0) 'Schema or fixture counts changed'
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
            -Filter 'trip-decider-wu7r-*' `
            -Force `
            -ErrorAction SilentlyContinue
    )
    Assert-True ($residue.Count -eq 0) 'WU7R temporary residue remains'
}

try {
    Write-Output 'GATE_01=project_venv_lock_pip'
    Assert-Environment
    Write-Output 'GATE_02=approved_plan_hash'
    Assert-PlanHash
    Write-Output 'GATE_03=scope_history_wu7b_exemption'
    Assert-ScopeAndHistory
    Write-Output 'GATE_04=protected_hashes'
    Assert-ProtectedHashes
    Write-Output 'GATE_05=provider_neutral_tests'
    Assert-NewContractTests
    Write-Output 'GATE_06=protected_wu7_tests'
    Assert-Wu7CompatibilityTests
    Write-Output 'GATE_07=full_regression'
    Assert-FullRegression
    Write-Output 'GATE_08=synthetic_byte_compatibility'
    Assert-SyntheticCompatibility
    Write-Output 'GATE_09=ephemeral_memory_only'
    Assert-EphemeralBoundary
    Write-Output 'GATE_10=policy_mismatch_hard_failure'
    Assert-PolicyMismatchBoundary
    Write-Output 'GATE_11=no_network_or_llm_source'
    Assert-NoNetworkSource
    Write-Output 'GATE_12=no_credential_read'
    Assert-NoCredentialRead
    Write-Output 'GATE_13=one_shared_parser_projector'
    Assert-OneSharedCore
    Write-Output 'GATE_14=schema_fixture_counts'
    Assert-ArtifactCounts
    Write-Output 'GATE_15=zero_residue'
    Assert-NoResidue

    Write-Output 'WU7R_VERIFICATION=PASS'
    Write-Output 'TESTS=220'
    Write-Output 'SCHEMAS=11'
    Write-Output 'FIXTURES_DOCUMENTS_DIRTY_CASES=7/40/7'
    Write-Output 'SYNTHETIC_FILES=12'
    Write-Output 'SYNTHETIC_CANDIDATES=1'
    Write-Output 'NETWORK_CALLS=0'
    Write-Output 'CREDENTIAL_READS=0'
    Write-Output 'LLM_CALLS=0'
    Write-Output 'TEMPORARY_RESIDUE=0'
} finally {
    foreach ($path in $temporaryArtifacts) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force
        }
    }
}
