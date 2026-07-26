$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Wu1Root = Split-Path -Parent $PSScriptRoot
$Wu1Python = Join-Path $Wu1Root '.venv\Scripts\python.exe'
$Wu1Source = Join-Path $Wu1Root 'src'

if (-not (Test-Path -LiteralPath $Wu1Python -PathType Leaf)) {
    Write-Error 'WU1 verification requires the project .venv Python interpreter.'
    exit 5
}

Push-Location $Wu1Root
try {
    $env:PYTHONPATH = $Wu1Source

    & $Wu1Python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    $Wu1FixtureCheck = @'
import json
import sys
from pathlib import Path

from trip_decider.fixture_validation import (
    validate_fixture_directory,
    validate_fixture_manifest,
)
from trip_decider.schema_validation import validate_schema_registry

root = Path.cwd()
schema_paths = tuple(sorted((root / "schemas").glob("*.schema.json")))
registry_result = validate_schema_registry(schema_paths)
if registry_result.value is None or registry_result.problems:
    print(json.dumps(
        {"status": "FAIL", "stage": "schema_registry", "problems": [
            {
                "error_code": item.error_code,
                "artifact_path": item.artifact_path,
                "json_pointer": item.json_pointer,
                "schema_rule": item.schema_rule,
            }
            for item in registry_result.problems
        ]},
        ensure_ascii=False,
        sort_keys=True,
    ))
    raise SystemExit(5)

registry = registry_result.value
fixture_root = root / "fixtures"
case_paths = tuple(sorted(fixture_root.glob("fixture_*/case.json")))
if len(case_paths) != 6:
    print(json.dumps(
        {
            "status": "FAIL",
            "stage": "fixture_discovery",
            "expected_fixture_count": 6,
            "actual_fixture_count": len(case_paths),
        },
        sort_keys=True,
    ))
    raise SystemExit(3)

for case_path in case_paths:
    raw = case_path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw:
        print(json.dumps(
            {
                "status": "FAIL",
                "stage": "case_encoding",
                "case_path": case_path.as_posix(),
            },
            sort_keys=True,
        ))
        raise SystemExit(4)
    manifest = json.loads(raw.decode("utf-8"))
    result = validate_fixture_manifest(manifest, registry)
    if result.value is None or result.problems:
        print(json.dumps(
            {
                "status": "FAIL",
                "stage": "fixture_manifest",
                "case_path": case_path.as_posix(),
                "problems": [
                    {
                        "error_code": item.error_code,
                        "artifact_path": item.artifact_path,
                        "json_pointer": item.json_pointer,
                        "schema_rule": item.schema_rule,
                    }
                    for item in result.problems
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        ))
        raise SystemExit(3)
    print(json.dumps(
        {
            "status": "PASS",
            "case_id": result.value.case_id,
            "bundle_closure": manifest["bundle_closure"],
            "root_artifact_id": result.value.root_artifact_id,
            "documents": result.value.document_count,
            "dirty_cases": result.value.dirty_case_count,
        },
        ensure_ascii=False,
        sort_keys=True,
    ))

summary = validate_fixture_directory(fixture_root, registry)
if summary.value is None or summary.problems:
    print(json.dumps(
        {"status": "FAIL", "stage": "fixture_directory", "problems": [
            {
                "error_code": item.error_code,
                "artifact_path": item.artifact_path,
                "json_pointer": item.json_pointer,
                "schema_rule": item.schema_rule,
            }
            for item in summary.problems
        ]},
        ensure_ascii=False,
        sort_keys=True,
    ))
    raise SystemExit(3)
if summary.value.fixture_count != 6:
    raise SystemExit(3)
print(json.dumps(
    {
        "status": "PASS",
        "fixture_count": summary.value.fixture_count,
        "document_count": summary.value.document_count,
        "dirty_case_count": summary.value.dirty_case_count,
        "schema_count": len(schema_paths),
    },
    sort_keys=True,
))
'@

    $Wu1TempPythonPath = [System.IO.Path]::Combine(
        [System.IO.Path]::GetTempPath(),
        ("trip-decider-wu1-{0}.py" -f [Guid]::NewGuid().ToString("N"))
    )
    $Wu1RepoFullPath = [System.IO.Path]::GetFullPath((Get-Location).Path)
    $Wu1TempFullPath = [System.IO.Path]::GetFullPath($Wu1TempPythonPath)
    if ($Wu1TempFullPath.StartsWith(
        $Wu1RepoFullPath + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Temporary Python script resolved inside repository."
    }
    $Wu1Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    try {
        [System.IO.File]::WriteAllText(
            $Wu1TempPythonPath,
            $Wu1FixtureCheck,
            $Wu1Utf8NoBom
        )
        & $Wu1Python $Wu1TempPythonPath
        $Wu1PythonExitCode = $LASTEXITCODE
    }
    finally {
        if (Test-Path -LiteralPath $Wu1TempPythonPath) {
            Remove-Item -LiteralPath $Wu1TempPythonPath -Force
        }
    }
    if ($Wu1PythonExitCode -ne 0) {
        exit $Wu1PythonExitCode
    }
}
finally {
    Pop-Location
}
