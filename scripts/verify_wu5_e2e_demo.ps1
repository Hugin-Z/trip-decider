[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
$startHead = 'e008d9e6fbdd81f7642f32bd0d6488a61bb6d539'
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
    $stdoutPath = Join-Path $tempRoot "trip-decider-wu5-$token.stdout"
    $stderrPath = Join-Path $tempRoot "trip-decider-wu5-$token.stderr"
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

function Invoke-TemporaryPython {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Code,

        [Parameter(Mandatory = $true)]
        [string]$Label,

        [string[]]$ScriptArguments = @()
    )

    $token = [Guid]::NewGuid().ToString('N')
    $scriptPath = Join-Path `
        ([IO.Path]::GetTempPath()) `
        "trip-decider-wu5-$token.py"
    $temporaryArtifacts.Add($scriptPath)
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    try {
        [IO.File]::WriteAllText($scriptPath, $Code, $utf8NoBom)
        $arguments = @($scriptPath) + $ScriptArguments
        return Invoke-CapturedProcess `
            -FilePath $pythonExe `
            -Arguments $arguments `
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
    $originCode = @'
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
        -Code $originCode `
        -Label 'project venv origin'
    Assert-True ($origin.ExitCode -eq 0) 'Project venv origin check failed'

    $pipCheck = Invoke-CapturedProcess `
        -FilePath $pythonExe `
        -Arguments @('-m', 'pip', 'check') `
        -Label 'pip check'
    Assert-True ($pipCheck.ExitCode -eq 0) 'pip check failed'
}

function Assert-FrozenInputs {
    $hashes = [ordered]@{
        'plans/work-unit-5-e2e-html-demo.md' = '653529395335CF422C1D02A206826DAFC32D10ECEE90A2125FFB37886D61AB54'
        'src/trip_decider/e2e_demo.py' = 'BA934DE551056533DBDBE59BC51B007DDA9272C4DF2A8FC300C31A6E8040C6C7'
        'tests/test_wu5_e2e_demo.py' = 'DCA808033245AE055AA46F6E10434F238ECFF3460735AE183EF8A97A21AD15B2'
        'src/trip_decider/recovery.py' = 'C0E098DD4AB997727A0EFBCCC9C396AC480DEEB3477DBF4CDCB5E31A34E0D8BA'
        'src/trip_decider/evidence_runtime.py' = '626D052F068537D050D350E8404948286670405D0B75C2E793CAA71656C89C04'
        'src/trip_decider/coarse_planner.py' = '8098F75190E279419D704E9135B896DE84D88691D4B2A942142671C870E25D8C'
        'tests/test_wu4_coarse_planner.py' = '1A9A090F32E9C785F36034A23B66D76F0173EDA95069882F514E3AFCE4C289E4'
        'PLAN.md' = '563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456'
        'pyproject.toml' = 'FD6622AA930E4BFA5986F26274EFA42B2512089050B716F445006C8EB98EA995'
        'requirements.lock' = 'BFE485EFB4105DC01C475D21EFB7858FD8468A69EBD0056363FBD9C84E6C6927'
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
    $remotes = @(& git -C $repoRoot remote)
    $stashes = @(& git -C $repoRoot stash list)
    Assert-True ($remotes.Count -eq 0) 'Git remotes are present'
    Assert-True ($stashes.Count -eq 0) 'Git stashes are present'

    $allowed = @(
        'plans/work-unit-5-e2e-html-demo.md',
        'src/trip_decider/e2e_demo.py',
        'tests/test_wu5_e2e_demo.py',
        'scripts/verify_wu5_e2e_demo.ps1',
        'docs/reviews/work-unit-5-e2e-html-demo-review.md'
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
        Assert-True ($allowed -contains $path) "Path outside WU5 scope: $path"
    }

    $expectedMessages = @(
        'docs: record WU5 end-to-end HTML demo plan',
        'chore: add end-to-end demo interface',
        'test: add failing end-to-end demo cases',
        'feat: implement end-to-end HTML demo',
        'chore: add end-to-end demo verification entry',
        'docs: prepare WU5 end-to-end HTML demo review'
    )
    $actualMessages = @(
        & git -C $repoRoot log --reverse --format='%s' "$startHead..HEAD"
    )
    Assert-True `
        ($actualMessages.Count -ge 4 -and $actualMessages.Count -le 6) `
        'WU5 commit count is outside the C3-C5 verification window'
    for ($index = 0; $index -lt $actualMessages.Count; $index++) {
        Assert-True `
            ($actualMessages[$index] -eq $expectedMessages[$index]) `
            "WU5 commit message mismatch at index $index"
    }

    $diffCheck = Invoke-CapturedProcess `
        -FilePath 'git' `
        -Arguments @('-C', $repoRoot, 'diff', '--check', "$startHead..HEAD") `
        -Label 'git diff check'
    Assert-True ($diffCheck.ExitCode -eq 0) 'git diff --check failed'
}

function Assert-R10Scans {
    $runtimePath = Join-Path $repoRoot 'src\trip_decider\e2e_demo.py'
    $runtime = [IO.File]::ReadAllText($runtimePath, [Text.Encoding]::UTF8)
    foreach ($pattern in @(
        'NotImplementedError',
        'silent_fallback',
        'infer_',
        'guess_',
        'urllib.request',
        'requests.',
        'httpx',
        'socket.',
        'openai',
        'anthropic',
        'langchain',
        '婺源',
        '江岭',
        '李坑',
        '篁岭',
        '庆源'
    )) {
        Assert-True `
            (-not $runtime.Contains($pattern)) `
            "R10/source scan matched: $pattern"
    }
    Assert-True `
        ($runtime.Contains('html.escape(value, quote=True)')) `
        'Renderer does not use the frozen escaping boundary'

    $scannedPaths = @(
        'plans/work-unit-5-e2e-html-demo.md',
        'src/trip_decider/e2e_demo.py',
        'tests/test_wu5_e2e_demo.py',
        'scripts/verify_wu5_e2e_demo.ps1'
    )
    $secretPattern = '(?i)(api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*["''][A-Za-z0-9_\-]{8,}'
    foreach ($relative in $scannedPaths) {
        $path = Join-Path $repoRoot ($relative.Replace('/', '\'))
        $content = [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8)
        Assert-True `
            (-not [Regex]::IsMatch($content, $secretPattern)) `
            "Secret pattern matched: $relative"
    }
}

function Invoke-Tests {
    $target = Invoke-CapturedProcess `
        -FilePath $pythonExe `
        -Arguments @(
            '-m',
            'unittest',
            'tests.test_wu5_e2e_demo',
            '-v'
        ) `
        -Label 'WU5 targeted tests'
    Assert-True ($target.ExitCode -eq 0) 'WU5 targeted tests failed'
    Assert-True `
        ($target.Combined -match 'Ran 6 tests') `
        'WU5 targeted test count is not 6'
    Assert-True `
        ($target.Combined -match '(?m)^OK\s*$') `
        'WU5 targeted tests did not report OK'

    $full = Invoke-CapturedProcess `
        -FilePath $pythonExe `
        -Arguments @(
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
            'tests.test_wu4_coarse_planner',
            'tests.test_wu5_e2e_demo'
        ) `
        -Label 'WU5 complete offline suite'
    Assert-True ($full.ExitCode -eq 0) 'Full regression failed'
    Assert-True `
        ($full.Combined -match 'Ran 210 tests') `
        'Full regression count is not 210'
    Assert-True `
        ($full.Combined -match '(?m)^OK\s*$') `
        'Full regression did not report OK'
}

function New-PlanningInput {
    param(
        [Parameter(Mandatory = $true)]
        [string]$OutputPath,

        [Parameter(Mandatory = $true)]
        [ValidateSet(1, 2)]
        [int]$DayCount
    )

    $code = @'
import sys
from pathlib import Path

repo = Path.cwd().resolve()
sys.path.insert(0, str(repo))
sys.path.insert(0, str(repo / "src"))

from tests.test_wu4_coarse_planner import _write_planning_root

output = Path(sys.argv[1])
day_count = int(sys.argv[2])
assert not output.exists()
_write_planning_root(output, day_count)
'@
    $result = Invoke-TemporaryPython `
        -Code $code `
        -Label "create explicit $DayCount-day planning input" `
        -ScriptArguments @($OutputPath, [string]$DayCount)
    Assert-True ($result.ExitCode -eq 0) 'Planning input preparation failed'
}

function Invoke-E2ECli {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PlanningInput,

        [Parameter(Mandatory = $true)]
        [string]$OutputRoot,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    $anchor = Join-Path $repoRoot 'fixtures\jiangxi_multi_identity_smoke'
    $previousPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = Join-Path $repoRoot 'src'
        return Invoke-CapturedProcess `
            -FilePath $pythonExe `
            -Arguments @(
                '-m',
                'trip_decider.e2e_demo',
                '--anchor-root',
                $anchor,
                '--planning-input-root',
                $PlanningInput,
                '--output-root',
                $OutputRoot
            ) `
            -Label $Label
    } finally {
        if ($null -eq $previousPythonPath) {
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        } else {
            $env:PYTHONPATH = $previousPythonPath
        }
    }
}

function Assert-CliAndOutputs {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RunRoot
    )

    $planningTwo = Join-Path $RunRoot 'planning-two'
    $planningOne = Join-Path $RunRoot 'planning-one'
    New-PlanningInput -OutputPath $planningTwo -DayCount 2
    New-PlanningInput -OutputPath $planningOne -DayCount 1

    $firstRoot = Join-Path $RunRoot 'output-first'
    $secondRoot = Join-Path $RunRoot 'output-second'
    $noPlanRoot = Join-Path $RunRoot 'output-no-plan'
    $first = Invoke-E2ECli `
        -PlanningInput $planningTwo `
        -OutputRoot $firstRoot `
        -Label 'WU5 CLI first clean root'
    $second = Invoke-E2ECli `
        -PlanningInput $planningTwo `
        -OutputRoot $secondRoot `
        -Label 'WU5 CLI second clean root'
    $noPlan = Invoke-E2ECli `
        -PlanningInput $planningOne `
        -OutputRoot $noPlanRoot `
        -Label 'WU5 CLI no-plan root'

    foreach ($result in @($first, $second)) {
        Assert-True ($result.ExitCode -eq 0) "$($result.Label) failed"
        Assert-True `
            ([string]::IsNullOrEmpty($result.Stderr)) `
            "$($result.Label) wrote stderr"
        Assert-True `
            ($result.Stdout.Trim() -eq (
                'status=conditionally_feasible scheduled=2 blocked=2 ' +
                'publishable=false report=report/index.html'
            )) `
            "$($result.Label) stdout mismatch"
    }
    Assert-True ($noPlan.ExitCode -eq 0) 'No-plan CLI failed'
    Assert-True `
        ([string]::IsNullOrEmpty($noPlan.Stderr)) `
        'No-plan CLI wrote stderr'
    Assert-True `
        ($noPlan.Stdout.Trim() -eq (
            'status=no_plan_found scheduled=0 blocked=2 ' +
            'publishable=false report=report/index.html'
        )) `
        'No-plan CLI stdout mismatch'

    $checker = @'
import hashlib
import json
import sys
from pathlib import Path

first = Path(sys.argv[1])
second = Path(sys.argv[2])
no_plan = Path(sys.argv[3])
repo = Path.cwd().resolve()

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

def files(root):
    return tuple(sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    ))

def bytes_by_path(root):
    return {
        name: root.joinpath(*name.split("/")).read_bytes()
        for name in files(root)
    }

def load(root, relative):
    return json.loads(
        root.joinpath(*relative.split("/")).read_text(encoding="utf-8")
    )

def sha(root, relative):
    return hashlib.sha256(
        root.joinpath(*relative.split("/")).read_bytes()
    ).hexdigest().upper()

assert files(first) == expected_files
assert files(second) == expected_files
assert files(no_plan) == expected_files
assert bytes_by_path(first) == bytes_by_path(second)

summary = load(first, "run-summary.json")
assert set(summary) == {
    "schema_version", "run_id", "completion_status", "input", "stages",
    "result", "report", "network_attempts", "llm_calls",
}
assert summary["schema_version"] == "wu5-e2e-demo-run/1.0"
assert summary["completion_status"] == "completed"
assert summary["result"] == {
    "planning_status": "conditionally_feasible",
    "draft_created": True,
    "publishable": False,
    "generation_allowed_input": False,
    "scheduled_count": 2,
    "blocked_count": 2,
}
assert summary["network_attempts"] == 0
assert summary["llm_calls"] == 0
assert "run_summary_sha256" not in summary
for stage in ("recovery", "evidence", "planning"):
    value = summary["stages"][stage]
    assert value["summary_path"] == f"{stage}/run-summary.json"
    assert value["summary_sha256"] == sha(first, value["summary_path"])
assert summary["report"] == {
    "path": "report/index.html",
    "sha256": sha(first, "report/index.html"),
}
planning_summary = load(first, "planning/run-summary.json")
assert summary["run_id"] == planning_summary["run_id"]

raw = first.joinpath("report", "index.html").read_bytes()
assert not raw.startswith(b"\xef\xbb\xbf")
text = raw.decode("utf-8", errors="strict")
assert "第1天：江岭" in text
assert "第2天：李坑" in text
assert text.count("具体时刻：尚未安排") == 2
assert "support_status: unknown" in text
assert "display_status: unknown" in text
assert "publishable: false" in text
assert "generation_allowed_input: false" in text
assert "<script" not in text.lower()
assert "<img" not in text.lower()
assert "http://" not in text.lower()
assert "https://" not in text.lower()
assert str(first) not in text

gate = load(first, "planning/planning-gate.json")
assert [item["seed"] for item in gate["blocked_seeds"]] == ["篁岭", "庆源"]
for candidate_ref in gate["blocked_seeds"][0]["candidate_refs"]:
    assert candidate_ref in text
assert gate["blocked_seeds"][1]["candidate_refs"] == []
assert "未创建占位地点" in text

plan = load(first, "planning/plan.json")
position = -1
for condition in plan["payload"]["conditions"]:
    next_position = text.index(condition["condition_id"])
    assert next_position > position
    assert condition["description"] in text
    position = next_position

no_plan_summary = load(no_plan, "run-summary.json")
assert no_plan_summary["result"]["planning_status"] == "no_plan_found"
assert no_plan_summary["result"]["publishable"] is False
no_plan_gate = load(no_plan, "planning/planning-gate.json")
no_plan_text = no_plan.joinpath("report", "index.html").read_text(
    encoding="utf-8"
)
assert "当前粗分配器未找到计划" in no_plan_text
assert no_plan_gate["no_plan_reason"] in no_plan_text
for candidate_ref in no_plan_gate["unscheduled_eligible_candidate_refs"]:
    assert candidate_ref in no_plan_text
assert "这不等于已证明不可行" in no_plan_text
assert "无法旅行" not in no_plan_text
assert 'id="itinerary"' not in no_plan_text
assert 'id="no-plan"' in no_plan_text

fixture_roots = []
documents = 0
dirty_cases = 0
for path in sorted((repo / "fixtures").iterdir()):
    case_path = path / "case.json"
    if not case_path.is_file():
        continue
    case = json.loads(case_path.read_text(encoding="utf-8"))
    fixture_roots.append(path)
    documents += len(case["documents"])
    dirty_cases += len(case["dirty_cases"])
assert (len(fixture_roots), documents, dirty_cases) == (7, 40, 7)

print(json.dumps({
    "dirty_cases": dirty_cases,
    "documents": documents,
    "files": len(expected_files),
    "fixtures": len(fixture_roots),
    "llm_calls": summary["llm_calls"],
    "network_attempts": summary["network_attempts"],
    "planning_status": summary["result"]["planning_status"],
}, sort_keys=True))
'@
    $checked = Invoke-TemporaryPython `
        -Code $checker `
        -Label 'independent CLI output matrix' `
        -ScriptArguments @($firstRoot, $secondRoot, $noPlanRoot)
    Assert-True ($checked.ExitCode -eq 0) 'CLI output matrix failed'

    $nonempty = Join-Path $RunRoot 'output-nonempty'
    [void][IO.Directory]::CreateDirectory($nonempty)
    $marker = Join-Path $nonempty 'marker.txt'
    [IO.File]::WriteAllText(
        $marker,
        'preserve',
        (New-Object System.Text.UTF8Encoding($false))
    )
    $rejected = Invoke-E2ECli `
        -PlanningInput $planningTwo `
        -OutputRoot $nonempty `
        -Label 'WU5 CLI nonempty output rejection'
    Assert-True ($rejected.ExitCode -eq 4) 'Nonempty output exit is not 4'
    Assert-True `
        ([string]::IsNullOrEmpty($rejected.Stdout)) `
        'Nonempty output failure wrote stdout'
    Assert-True `
        (-not [string]::IsNullOrWhiteSpace($rejected.Stderr)) `
        'Nonempty output failure did not write JSONL'
    Assert-True `
        ([IO.File]::ReadAllText($marker, [Text.Encoding]::UTF8) -eq 'preserve') `
        'Nonempty output was modified'
    $problem = ConvertFrom-Json -InputObject $rejected.Stderr.Trim()
    $problemFields = @(
        $problem.PSObject.Properties.Name | Sort-Object
    )
    $expectedProblemFields = @(
        'actual_type',
        'artifact_path',
        'error_code',
        'expected',
        'json_pointer',
        'message',
        'schema_rule'
    )
    Assert-True `
        (($problemFields -join '|') -eq ($expectedProblemFields -join '|')) `
        'Failure JSONL does not have seven fields'
    Assert-True `
        ($problem.error_code -eq 'E2E_OUTPUT_ROOT_INVALID') `
        'Nonempty output error code mismatch'
    Assert-True `
        (-not $rejected.Stderr.Contains($RunRoot)) `
        'Failure JSONL leaked an absolute path'

    return [PSCustomObject]@{
        FirstRoot = $firstRoot
        PlanningTwo = $planningTwo
    }
}

function Assert-LibraryBoundaries {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RunRoot,

        [Parameter(Mandatory = $true)]
        [string]$PlanningInput
    )

    $anchor = Join-Path $repoRoot 'fixtures\jiangxi_multi_identity_smoke'
    $successRoot = Join-Path $RunRoot 'library-output'
    $failedRoot = Join-Path $RunRoot 'library-failed-output'
    $code = @'
import json
import socket
import sys
import urllib.request
from pathlib import Path
from unittest.mock import patch

repo = Path.cwd().resolve()
sys.path.insert(0, str(repo))
sys.path.insert(0, str(repo / "src"))

import trip_decider.e2e_demo as module
from trip_decider.coarse_planner import run_coarse_planner as planner
from trip_decider.evidence_runtime import run_evidence_runtime as evidence
from trip_decider.recovery import run_wu2_recovery as recovery
from trip_decider.schema_validation import ValidationProblem, ValidationResult

anchor = Path(sys.argv[1])
planning = Path(sys.argv[2])
success_root = Path(sys.argv[3])
failed_root = Path(sys.argv[4])
trace = []

def recovery_once(*args, **kwargs):
    assert not Path(args[1]).exists()
    trace.append("recovery")
    return recovery(*args, **kwargs)

def evidence_once(*args, **kwargs):
    assert not Path(args[1]).exists()
    trace.append("evidence")
    return evidence(*args, **kwargs)

def planner_once(*args, **kwargs):
    assert not Path(args[3]).exists()
    trace.append("planning")
    return planner(*args, **kwargs)

real_render = module._render_html
real_install = module._install_directory

def render_once(*args, **kwargs):
    trace.append("render")
    return real_render(*args, **kwargs)

def install_once(*args, **kwargs):
    trace.append("install")
    return real_install(*args, **kwargs)

with (
    patch("trip_decider.e2e_demo.run_wu2_recovery", side_effect=recovery_once)
    as recovery_mock,
    patch(
        "trip_decider.e2e_demo.run_evidence_runtime",
        side_effect=evidence_once,
    ) as evidence_mock,
    patch(
        "trip_decider.e2e_demo.run_coarse_planner",
        side_effect=planner_once,
    ) as planner_mock,
    patch("trip_decider.e2e_demo._render_html", side_effect=render_once)
    as render_mock,
    patch(
        "trip_decider.e2e_demo._install_directory",
        side_effect=install_once,
    ) as install_mock,
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
    result = module.run_e2e_demo(anchor, planning, success_root)

assert not result.problems and result.value is not None
assert recovery_mock.call_count == 1
assert evidence_mock.call_count == 1
assert planner_mock.call_count == 1
assert render_mock.call_count == 1
assert install_mock.call_count == 1
assert trace == ["recovery", "evidence", "planning", "render", "install"]
assert socket_mock.call_count == 0
assert urlopen_mock.call_count == 0
assert result.value.network_attempts == 0
assert result.value.llm_calls == 0

documents = module._load_stage_documents(success_root)
candidate = documents["recovery/candidates.json"]["payload"]["candidates"][4]
original_label = candidate["label"]
candidate["label"] = "<script data-x='1'>&"
escaped = module._render_html(documents).decode("utf-8")
assert "<script data-x='1'>" not in escaped
assert "&lt;script data-x=&#x27;1&#x27;&gt;&amp;" in escaped
candidate["label"] = original_label

forced = ValidationProblem(
    error_code="EVIDENCE_RUNTIME_INPUT_INVALID",
    artifact_path="input/forced",
    json_pointer="/forced",
    schema_rule="injected",
    expected="accepted evidence input",
    actual_type="injected",
    message="Evidence Runtime input is invalid.",
)
with (
    patch("trip_decider.e2e_demo.run_wu2_recovery", wraps=recovery)
    as recovery_mock,
    patch(
        "trip_decider.e2e_demo.run_evidence_runtime",
        return_value=ValidationResult(None, (forced,)),
    ) as evidence_mock,
    patch("trip_decider.e2e_demo.run_coarse_planner", wraps=planner)
    as planner_mock,
    patch("trip_decider.e2e_demo._render_html", wraps=real_render)
    as render_mock,
):
    failed = module.run_e2e_demo(anchor, planning, failed_root)
assert failed.value is None
assert failed.problems == (forced,)
assert recovery_mock.call_count == 1
assert evidence_mock.call_count == 1
assert planner_mock.call_count == 0
assert render_mock.call_count == 0
assert not failed_root.exists()
assert not any(
    item.name.startswith(f".{failed_root.name}.")
    and item.name.endswith(".staging")
    for item in failed_root.parent.iterdir()
)

print(json.dumps({
    "install_calls": install_mock.call_count,
    "llm_calls": result.value.llm_calls,
    "network_attempts": result.value.network_attempts,
    "stage_calls": [1, 1, 1],
    "temporary_residue": 0,
}, sort_keys=True))
'@
    $checked = Invoke-TemporaryPython `
        -Code $code `
        -Label 'independent library boundary matrix' `
        -ScriptArguments @(
            $anchor,
            $PlanningInput,
            $successRoot,
            $failedRoot
        )
    Assert-True ($checked.ExitCode -eq 0) 'Library boundary matrix failed'
}

function Assert-NoResidue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RunRoot
    )

    $staging = @(
        Get-ChildItem -LiteralPath $RunRoot -Recurse -Force -Directory |
            Where-Object { $_.Name.EndsWith('.staging') }
    )
    Assert-True ($staging.Count -eq 0) 'WU5 staging residue is present'
    foreach ($path in $temporaryArtifacts) {
        Assert-True `
            (-not (Test-Path -LiteralPath $path)) `
            "Temporary verifier artifact remains: $path"
    }
}

$runRoot = Join-Path `
    ([IO.Path]::GetTempPath()) `
    ("trip-decider-wu5-verify-" + [Guid]::NewGuid().ToString('N'))
$runRootRemoved = $false
try {
    [void][IO.Directory]::CreateDirectory($runRoot)
    Assert-Environment
    Assert-FrozenInputs
    Assert-ScopeAndHistory
    Assert-R10Scans
    Invoke-Tests
    $cli = Assert-CliAndOutputs -RunRoot $runRoot
    Assert-LibraryBoundaries `
        -RunRoot $runRoot `
        -PlanningInput $cli.PlanningTwo
    Assert-NoResidue -RunRoot $runRoot
} finally {
    if (Test-Path -LiteralPath $runRoot) {
        Remove-Item -LiteralPath $runRoot -Recurse -Force
    }
    $runRootRemoved = -not (Test-Path -LiteralPath $runRoot)
}

Assert-True $runRootRemoved 'Verifier system-temp root was not removed'
foreach ($path in $temporaryArtifacts) {
    Assert-True `
        (-not (Test-Path -LiteralPath $path)) `
        "Temporary verifier artifact remains after cleanup: $path"
}

[Console]::Out.WriteLine(
    'WU5-E2E verification PASS: tests=210 schemas=11 ' +
    'fixtures=7 documents=40 dirty_cases=7 output_files=13 ' +
    'network_attempts=0 llm_calls=0 temporary_residue=0'
)
