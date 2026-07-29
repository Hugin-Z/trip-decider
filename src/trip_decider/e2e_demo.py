"""WU5 orchestration and a static, non-publishable HTML result page.

This module composes the approved Recovery, Evidence Runtime, and Coarse
Planner entrypoints.  It does not reproduce any of their domain decisions.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import IO, Mapping, Sequence
from urllib.parse import urlsplit

from trip_decider.coarse_planner import run_coarse_planner
from trip_decider.evidence_runtime import run_evidence_runtime
from trip_decider.recovery import run_wu2_recovery
from trip_decider.schema_validation import (
    ValidationProblem,
    ValidationResult,
)


_PROBLEM_MESSAGES = {
    "E2E_INPUT_INVALID": "End-to-end demo input is invalid.",
    "E2E_OUTPUT_ROOT_INVALID": "End-to-end output root is invalid.",
    "E2E_STAGE_OUTPUT_INVALID": "A stage output is invalid.",
    "E2E_RENDER_INVALID": "The static report input is invalid.",
    "E2E_TRANSACTION_FAILED": "The output transaction failed.",
    "E2E_OUTPUT_HASH_MISMATCH": "Installed output bytes do not match.",
    "E2E_INTERNAL_FAILURE": "The end-to-end demo failed internally.",
}

_EXPECTED_FILES = (
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

_AUDIT_LINKS = (
    ("Plan artifact", "../planning/plan.json"),
    ("Violations artifact", "../planning/violations.json"),
    ("Planning gate", "../planning/planning-gate.json"),
    ("Evidence artifact", "../evidence/evidence.json"),
    ("Candidate artifact", "../recovery/candidates.json"),
)


@dataclass(frozen=True)
class E2EDemoSummary:
    """Auditable control metadata for one complete offline demo run."""

    run_id: str
    run_summary_path: Path
    report_path: Path
    planning_status: str
    draft_created: bool
    publishable: bool
    generation_allowed_input: bool
    scheduled_count: int
    blocked_count: int
    network_attempts: int
    llm_calls: int
    output_sha256: Mapping[str, str]


class _E2EIssue(Exception):
    def __init__(
        self,
        code: str,
        pointer: str,
        rule: str,
        *,
        expected: str = "",
        actual_type: str = "",
        artifact_path: str = "",
    ) -> None:
        super().__init__(code)
        self.code = code
        self.pointer = pointer
        self.rule = rule
        self.expected = expected
        self.actual_type = actual_type
        self.artifact_path = artifact_path


class _StageRejected(Exception):
    def __init__(self, problems: tuple[ValidationProblem, ...]) -> None:
        super().__init__("stage rejected input")
        self.problems = problems


class _HTMLAuditParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.section_ids: list[str] = []
        self.links: list[str] = []
        self.forbidden_tag = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag in {"script", "img", "link", "iframe", "object", "embed"}:
            self.forbidden_tag = True
        values = dict(attrs)
        if tag == "section":
            section_id = values.get("id")
            if isinstance(section_id, str):
                self.section_ids.append(section_id)
        if tag == "a":
            href = values.get("href")
            if isinstance(href, str):
                self.links.append(href)


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _E2EIssue(
            "E2E_INPUT_INVALID",
            "/cli",
            "arguments",
            expected="three required path arguments",
            actual_type="command-line",
        )


def _problem(
    code: str,
    pointer: str,
    rule: str,
    *,
    expected: str = "",
    actual_type: str = "",
    artifact_path: str = "",
) -> ValidationProblem:
    if code not in _PROBLEM_MESSAGES:
        raise ValueError("unknown WU5 problem code")
    return ValidationProblem(
        error_code=code,
        artifact_path=artifact_path,
        json_pointer=pointer,
        schema_rule=rule,
        expected=expected,
        actual_type=actual_type,
        message=_PROBLEM_MESSAGES[code],
    )


def _failure(issue: _E2EIssue) -> ValidationResult[E2EDemoSummary]:
    return ValidationResult(
        None,
        (
            _problem(
                issue.code,
                issue.pointer,
                issue.rule,
                expected=issue.expected,
                actual_type=issue.actual_type,
                artifact_path=issue.artifact_path,
            ),
        ),
    )


def _type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return type(value).__name__


def _object(
    value: object,
    pointer: str,
    *,
    code: str = "E2E_STAGE_OUTPUT_INVALID",
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise _E2EIssue(
            code,
            pointer,
            "type",
            expected="object",
            actual_type=_type_name(value),
        )
    return value


def _array(
    value: object,
    pointer: str,
    *,
    code: str = "E2E_STAGE_OUTPUT_INVALID",
) -> list[object]:
    if not isinstance(value, list):
        raise _E2EIssue(
            code,
            pointer,
            "type",
            expected="array",
            actual_type=_type_name(value),
        )
    return value


def _string(
    value: object,
    pointer: str,
    *,
    code: str = "E2E_STAGE_OUTPUT_INVALID",
) -> str:
    if not isinstance(value, str) or not value:
        raise _E2EIssue(
            code,
            pointer,
            "nonemptyString",
            expected="non-empty string",
            actual_type=_type_name(value),
        )
    return value


def _boolean(
    value: object,
    pointer: str,
    *,
    code: str = "E2E_STAGE_OUTPUT_INVALID",
) -> bool:
    if not isinstance(value, bool):
        raise _E2EIssue(
            code,
            pointer,
            "type",
            expected="boolean",
            actual_type=_type_name(value),
        )
    return value


def _integer(
    value: object,
    pointer: str,
    *,
    code: str = "E2E_STAGE_OUTPUT_INVALID",
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _E2EIssue(
            code,
            pointer,
            "nonnegativeInteger",
            expected="non-negative integer",
            actual_type=_type_name(value),
        )
    return value


def _member(
    value: Mapping[str, object],
    key: str,
    pointer: str,
    *,
    code: str = "E2E_STAGE_OUTPUT_INVALID",
) -> object:
    if key not in value:
        raise _E2EIssue(
            code,
            f"{pointer}/{key}",
            "required",
            expected="required member",
            actual_type="missing",
        )
    return value[key]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def _json_clone(value: object) -> object:
    try:
        return json.loads(
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
            )
        )
    except (TypeError, ValueError) as error:
        raise _E2EIssue(
            "E2E_STAGE_OUTPUT_INVALID",
            "/summary",
            "jsonValue",
            expected="JSON-compatible stage summary value",
            actual_type=_type_name(value),
        ) from error


def _read_json(path: Path, logical_path: str) -> dict[str, object]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise _E2EIssue(
            "E2E_STAGE_OUTPUT_INVALID",
            f"/{logical_path}",
            "readableFile",
            expected="readable stage output",
            actual_type="unreadable",
            artifact_path=logical_path,
        ) from error
    if raw.startswith(b"\xef\xbb\xbf"):
        raise _E2EIssue(
            "E2E_STAGE_OUTPUT_INVALID",
            f"/{logical_path}",
            "utf8",
            expected="UTF-8 without BOM",
            actual_type="utf8-bom",
            artifact_path=logical_path,
        )
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise _E2EIssue(
            "E2E_STAGE_OUTPUT_INVALID",
            f"/{logical_path}",
            "json",
            expected="strict UTF-8 JSON object",
            actual_type="invalid-json",
            artifact_path=logical_path,
        ) from error
    return _object(value, f"/{logical_path}")


def _relative_files(root: Path) -> tuple[str, ...]:
    try:
        return tuple(
            sorted(
                path.relative_to(root).as_posix()
                for path in root.rglob("*")
                if path.is_file()
            )
        )
    except OSError as error:
        raise _E2EIssue(
            "E2E_TRANSACTION_FAILED",
            "/output",
            "fileInventory",
            expected="readable prepared output tree",
            actual_type="unreadable",
        ) from error


def _write_exclusive(path: Path, content: bytes) -> None:
    try:
        with path.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as error:
        raise _E2EIssue(
            "E2E_TRANSACTION_FAILED",
            "/output",
            "exclusiveWrite",
            expected="exclusive staging write",
            actual_type="write-failure",
        ) from error


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


def _candidate_labels(
    candidates: dict[str, object],
) -> dict[str, str]:
    payload = _object(
        _member(candidates, "payload", "/recovery/candidates"),
        "/recovery/candidates/payload",
    )
    items = _array(
        _member(payload, "candidates", "/recovery/candidates/payload"),
        "/recovery/candidates/payload/candidates",
    )
    labels: dict[str, str] = {}
    for index, raw_item in enumerate(items):
        pointer = f"/recovery/candidates/payload/candidates/{index}"
        item = _object(raw_item, pointer)
        candidate_id = _string(
            _member(item, "candidate_id", pointer),
            f"{pointer}/candidate_id",
        )
        label = _string(
            _member(item, "label", pointer),
            f"{pointer}/label",
        )
        if candidate_id in labels:
            raise _E2EIssue(
                "E2E_RENDER_INVALID",
                f"{pointer}/candidate_id",
                "uniqueCandidateId",
                expected="unique candidate ID",
                actual_type="duplicate",
            )
        labels[candidate_id] = label
    if not labels:
        raise _E2EIssue(
            "E2E_RENDER_INVALID",
            "/recovery/candidates/payload/candidates",
            "minItems",
            expected="at least one Candidate",
            actual_type="empty-array",
        )
    return labels


def _artifact_id(document: Mapping[str, object], pointer: str) -> str:
    return _string(
        _member(document, "artifact_id", pointer),
        f"{pointer}/artifact_id",
        code="E2E_RENDER_INVALID",
    )


def _render_html(documents: Mapping[str, dict[str, object]]) -> bytes:
    candidates = documents["recovery/candidates.json"]
    evidence = documents["evidence/evidence.json"]
    plan = documents["planning/plan.json"]
    gate = documents["planning/planning-gate.json"]
    planning_summary = documents["planning/run-summary.json"]

    labels = _candidate_labels(candidates)
    plan_payload = _object(
        _member(plan, "payload", "/planning/plan"),
        "/planning/plan/payload",
        code="E2E_RENDER_INVALID",
    )
    evidence_payload = _object(
        _member(evidence, "payload", "/evidence/evidence"),
        "/evidence/evidence/payload",
        code="E2E_RENDER_INVALID",
    )
    planning_status = _string(
        _member(plan_payload, "plan_status", "/planning/plan/payload"),
        "/planning/plan/payload/plan_status",
        code="E2E_RENDER_INVALID",
    )
    gate_status = _string(
        _member(gate, "planning_status", "/planning/planning-gate"),
        "/planning/planning-gate/planning_status",
        code="E2E_RENDER_INVALID",
    )
    publishable = _boolean(
        _member(gate, "publishable", "/planning/planning-gate"),
        "/planning/planning-gate/publishable",
        code="E2E_RENDER_INVALID",
    )
    generation_allowed = _boolean(
        _member(
            gate,
            "generation_allowed_input",
            "/planning/planning-gate",
        ),
        "/planning/planning-gate/generation_allowed_input",
        code="E2E_RENDER_INVALID",
    )
    if (
        planning_status not in {"conditionally_feasible", "no_plan_found"}
        or gate_status != planning_status
        or publishable
        or generation_allowed
    ):
        raise _E2EIssue(
            "E2E_RENDER_INVALID",
            "/planning/status",
            "nonPublishableCoarseResult",
            expected="matching conditional/no-plan status and false gates",
            actual_type="inconsistent-status",
        )

    raw_days = _array(
        _member(plan_payload, "days", "/planning/plan/payload"),
        "/planning/plan/payload/days",
        code="E2E_RENDER_INVALID",
    )
    raw_blockers = _array(
        _member(gate, "blocked_seeds", "/planning/planning-gate"),
        "/planning/planning-gate/blocked_seeds",
        code="E2E_RENDER_INVALID",
    )
    raw_facts = _array(
        _member(evidence_payload, "facts", "/evidence/evidence/payload"),
        "/evidence/evidence/payload/facts",
        code="E2E_RENDER_INVALID",
    )
    raw_conditions = _array(
        _member(plan_payload, "conditions", "/planning/plan/payload"),
        "/planning/plan/payload/conditions",
        code="E2E_RENDER_INVALID",
    )

    evidence_statuses: set[tuple[str, str]] = set()
    for index, raw_fact in enumerate(raw_facts):
        pointer = f"/evidence/evidence/payload/facts/{index}"
        fact = _object(raw_fact, pointer, code="E2E_RENDER_INVALID")
        evidence_statuses.add(
            (
                _string(
                    _member(fact, "support_status", pointer),
                    f"{pointer}/support_status",
                    code="E2E_RENDER_INVALID",
                ),
                _string(
                    _member(fact, "display_status", pointer),
                    f"{pointer}/display_status",
                    code="E2E_RENDER_INVALID",
                ),
            )
        )
    if not evidence_statuses:
        raise _E2EIssue(
            "E2E_RENDER_INVALID",
            "/evidence/evidence/payload/facts",
            "minItems",
            expected="at least one Evidence fact",
            actual_type="empty-array",
        )

    candidate_count = _integer(
        _member(
            documents["recovery/run-summary.json"],
            "candidate_count",
            "/recovery/run-summary",
        ),
        "/recovery/run-summary/candidate_count",
        code="E2E_RENDER_INVALID",
    )
    scheduled_count = _integer(
        _member(
            planning_summary,
            "scheduled_candidate_count",
            "/planning/run-summary",
        ),
        "/planning/run-summary/scheduled_candidate_count",
        code="E2E_RENDER_INVALID",
    )
    blocked_count = _integer(
        _member(
            planning_summary,
            "blocked_seed_count",
            "/planning/run-summary",
        ),
        "/planning/run-summary/blocked_seed_count",
        code="E2E_RENDER_INVALID",
    )
    run_id = _string(
        _member(planning_summary, "run_id", "/planning/run-summary"),
        "/planning/run-summary/run_id",
        code="E2E_RENDER_INVALID",
    )

    title = (
        "条件化粗计划"
        if planning_status == "conditionally_feasible"
        else "粗计划结果"
    )
    lines = [
        "<!doctype html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8">',
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        "<title>trip-decider 离线粗计划结果</title>",
        "<style>",
        ":root{color-scheme:light;font-family:system-ui,sans-serif;}",
        "body{max-width:920px;margin:0 auto;padding:32px 20px;color:#17202a;",
        "background:#f5f7f8;line-height:1.6;}",
        "section{background:#fff;border:1px solid #d8dee3;border-radius:12px;",
        "padding:20px;margin:16px 0;}",
        ".warning{font-weight:700;color:#8a3b12;}",
        ".card{border-left:4px solid #466b7a;padding:4px 16px;margin:16px 0;}",
        "code{overflow-wrap:anywhere;}",
        "a{color:#245f78;}",
        "</style>",
        "</head>",
        "<body>",
        '<section id="status">',
        f"<h1>{title}</h1>",
        '<p class="warning">不可直接发布</p>',
        "<p>未进行路线、营业时间或时长验证。</p>",
        "<ul>",
        f"<li>plan_status: {_escape(planning_status)}</li>",
        "<li>publishable: false</li>",
        "<li>generation_allowed_input: false</li>",
        "</ul>",
        "</section>",
    ]

    if planning_status == "conditionally_feasible":
        if not raw_days:
            raise _E2EIssue(
                "E2E_RENDER_INVALID",
                "/planning/plan/payload/days",
                "minItems",
                expected="at least one scheduled day",
                actual_type="empty-array",
            )
        lines.extend(
            [
                '<section id="itinerary">',
                "<h2>日程草案</h2>",
            ]
        )
        for day_index, raw_day in enumerate(raw_days):
            day_pointer = f"/planning/plan/payload/days/{day_index}"
            day = _object(
                raw_day,
                day_pointer,
                code="E2E_RENDER_INVALID",
            )
            date = _string(
                _member(day, "date", day_pointer),
                f"{day_pointer}/date",
                code="E2E_RENDER_INVALID",
            )
            activities = _array(
                _member(day, "activities", day_pointer),
                f"{day_pointer}/activities",
                code="E2E_RENDER_INVALID",
            )
            if len(activities) != 1:
                raise _E2EIssue(
                    "E2E_RENDER_INVALID",
                    f"{day_pointer}/activities",
                    "oneActivityPerDay",
                    expected="one coarse activity",
                    actual_type=f"array-count-{len(activities)}",
                )
            activity = _object(
                activities[0],
                f"{day_pointer}/activities/0",
                code="E2E_RENDER_INVALID",
            )
            candidate_ref = _string(
                _member(
                    activity,
                    "candidate_ref",
                    f"{day_pointer}/activities/0",
                ),
                f"{day_pointer}/activities/0/candidate_ref",
                code="E2E_RENDER_INVALID",
            )
            timing_status = _string(
                _member(
                    activity,
                    "timing_status",
                    f"{day_pointer}/activities/0",
                ),
                f"{day_pointer}/activities/0/timing_status",
                code="E2E_RENDER_INVALID",
            )
            if candidate_ref not in labels:
                raise _E2EIssue(
                    "E2E_RENDER_INVALID",
                    f"{day_pointer}/activities/0/candidate_ref",
                    "resolvedCandidate",
                    expected="existing Candidate reference",
                    actual_type="unresolved-reference",
                )
            if timing_status != "day_assigned_unscheduled":
                raise _E2EIssue(
                    "E2E_RENDER_INVALID",
                    f"{day_pointer}/activities/0/timing_status",
                    "const",
                    expected="day_assigned_unscheduled",
                    actual_type="unsupported-status",
                )
            lines.extend(
                [
                    '<article class="card">',
                    (
                        f"<h3>第{day_index + 1}天："
                        f"{_escape(labels[candidate_ref])}</h3>"
                    ),
                    f"<p>日期：{_escape(date)}</p>",
                    "<p>具体时刻：尚未安排</p>",
                    "</article>",
                ]
            )
        lines.extend(["</section>"])
    else:
        if raw_days:
            raise _E2EIssue(
                "E2E_RENDER_INVALID",
                "/planning/plan/payload/days",
                "noPlanDays",
                expected="empty days for no_plan_found",
                actual_type="nonempty-array",
            )
        reason = _string(
            _member(gate, "no_plan_reason", "/planning/planning-gate"),
            "/planning/planning-gate/no_plan_reason",
            code="E2E_RENDER_INVALID",
        )
        unscheduled = _array(
            _member(
                gate,
                "unscheduled_eligible_candidate_refs",
                "/planning/planning-gate",
            ),
            "/planning/planning-gate/unscheduled_eligible_candidate_refs",
            code="E2E_RENDER_INVALID",
        )
        if not unscheduled:
            raise _E2EIssue(
                "E2E_RENDER_INVALID",
                "/planning/planning-gate/"
                "unscheduled_eligible_candidate_refs",
                "minItems",
                expected="unscheduled required Candidate refs",
                actual_type="empty-array",
            )
        lines.extend(
            [
                '<section id="no-plan">',
                "<h2>当前粗分配器未找到计划</h2>",
                f"<p>原因：<code>{_escape(reason)}</code></p>",
                "<p>尚未排入的必需候选：</p>",
                "<ul>",
            ]
        )
        for index, raw_ref in enumerate(unscheduled):
            candidate_ref = _string(
                raw_ref,
                "/planning/planning-gate/"
                f"unscheduled_eligible_candidate_refs/{index}",
                code="E2E_RENDER_INVALID",
            )
            if candidate_ref not in labels:
                raise _E2EIssue(
                    "E2E_RENDER_INVALID",
                    "/planning/planning-gate/"
                    f"unscheduled_eligible_candidate_refs/{index}",
                    "resolvedCandidate",
                    expected="existing Candidate reference",
                    actual_type="unresolved-reference",
                )
            lines.append(
                "<li>"
                f"{_escape(labels[candidate_ref])} — "
                f"<code>{_escape(candidate_ref)}</code>"
                "</li>"
            )
        lines.extend(
            [
                "</ul>",
                "<p><strong>这不等于已证明不可行。</strong></p>",
                "</section>",
            ]
        )

    lines.extend(
        [
            '<section id="blockers">',
            "<h2>待确认和未匹配</h2>",
        ]
    )
    if not raw_blockers:
        lines.append("<p>当前 planning gate 未记录 identity blocker。</p>")
    for blocker_index, raw_blocker in enumerate(raw_blockers):
        pointer = (
            f"/planning/planning-gate/blocked_seeds/{blocker_index}"
        )
        blocker = _object(
            raw_blocker,
            pointer,
            code="E2E_RENDER_INVALID",
        )
        seed = _string(
            _member(blocker, "seed", pointer),
            f"{pointer}/seed",
            code="E2E_RENDER_INVALID",
        )
        generation_status = _string(
            _member(blocker, "generation_status", pointer),
            f"{pointer}/generation_status",
            code="E2E_RENDER_INVALID",
        )
        candidate_refs = _array(
            _member(blocker, "candidate_refs", pointer),
            f"{pointer}/candidate_refs",
            code="E2E_RENDER_INVALID",
        )
        lines.extend(
            [
                '<article class="card">',
                f"<h3>{_escape(seed)}</h3>",
                f"<p><code>{_escape(generation_status)}</code></p>",
            ]
        )
        if generation_status == "BLOCKED_IDENTITY_AMBIGUOUS":
            if not candidate_refs:
                raise _E2EIssue(
                    "E2E_RENDER_INVALID",
                    f"{pointer}/candidate_refs",
                    "minItems",
                    expected="all alternative Candidate refs",
                    actual_type="empty-array",
                )
            lines.extend(
                [
                    "<p>状态：存在多个候选，需要确认。</p>",
                    "<p>保留全部 alternative candidate refs；"
                    "未选择任何候选。</p>",
                    "<ul>",
                ]
            )
            for ref_index, raw_ref in enumerate(candidate_refs):
                candidate_ref = _string(
                    raw_ref,
                    f"{pointer}/candidate_refs/{ref_index}",
                    code="E2E_RENDER_INVALID",
                )
                if candidate_ref not in labels:
                    raise _E2EIssue(
                        "E2E_RENDER_INVALID",
                        f"{pointer}/candidate_refs/{ref_index}",
                        "resolvedCandidate",
                        expected="existing alternative Candidate",
                        actual_type="unresolved-reference",
                    )
                lines.append(
                    f"<li><code>{_escape(candidate_ref)}</code></li>"
                )
            lines.append("</ul>")
        elif generation_status == "BLOCKED_IDENTITY_UNMATCHED":
            if candidate_refs:
                raise _E2EIssue(
                    "E2E_RENDER_INVALID",
                    f"{pointer}/candidate_refs",
                    "maxItems",
                    expected="no placeholder Candidate refs",
                    actual_type="nonempty-array",
                )
            lines.extend(
                [
                    "<p>状态：当前候选池未匹配。</p>",
                    "<p>candidate refs：空。</p>",
                    "<p>未创建占位地点。</p>",
                ]
            )
        else:
            raise _E2EIssue(
                "E2E_RENDER_INVALID",
                f"{pointer}/generation_status",
                "supportedIdentityBlocker",
                expected=(
                    "BLOCKED_IDENTITY_AMBIGUOUS or "
                    "BLOCKED_IDENTITY_UNMATCHED"
                ),
                actual_type="unsupported-status",
            )
        lines.append("</article>")
    lines.append("</section>")

    lines.extend(
        [
            '<section id="evidence">',
            "<h2>证据状态</h2>",
            "<ul>",
        ]
    )
    for support_status, display_status in sorted(evidence_statuses):
        lines.extend(
            [
                "<li>",
                f"support_status: {_escape(support_status)}<br>",
                f"display_status: {_escape(display_status)}",
                "</li>",
            ]
        )
    lines.extend(
        [
            "</ul>",
            "<p>已从离线候选记录中提取，但尚未具备完整的结构化来源证明，"
            "不能视为已核实事实。</p>",
            "</section>",
            '<section id="conditions">',
            "<h2>尚未验证的条件</h2>",
        ]
    )
    for condition_index, raw_condition in enumerate(raw_conditions):
        pointer = (
            f"/planning/plan/payload/conditions/{condition_index}"
        )
        condition = _object(
            raw_condition,
            pointer,
            code="E2E_RENDER_INVALID",
        )
        condition_id = _string(
            _member(condition, "condition_id", pointer),
            f"{pointer}/condition_id",
            code="E2E_RENDER_INVALID",
        )
        description = _string(
            _member(condition, "description", pointer),
            f"{pointer}/description",
            code="E2E_RENDER_INVALID",
        )
        lines.extend(
            [
                '<article class="card">',
                f"<h3><code>{_escape(condition_id)}</code></h3>",
                f"<p>{_escape(description)}</p>",
                "</article>",
            ]
        )
    lines.extend(
        [
            "</section>",
            '<section id="audit">',
            "<h2>审计信息</h2>",
            "<dl>",
            "<dt>plan artifact ID</dt>",
            f"<dd><code>{_escape(_artifact_id(plan, '/planning/plan'))}</code></dd>",
            "<dt>evidence artifact ID</dt>",
            (
                "<dd><code>"
                f"{_escape(_artifact_id(evidence, '/evidence/evidence'))}"
                "</code></dd>"
            ),
            "<dt>candidate count</dt>",
            f"<dd>{candidate_count}</dd>",
            "<dt>evidence fact count</dt>",
            f"<dd>{len(raw_facts)}</dd>",
            "<dt>scheduled count</dt>",
            f"<dd>{scheduled_count}</dd>",
            "<dt>blocked count</dt>",
            f"<dd>{blocked_count}</dd>",
            "<dt>run ID</dt>",
            f"<dd><code>{_escape(run_id)}</code></dd>",
            "</dl>",
            "<ul>",
        ]
    )
    for label, href in _AUDIT_LINKS:
        lines.append(
            f'<li><a href="{_escape(href)}">{_escape(label)}</a></li>'
        )
    lines.extend(
        [
            "</ul>",
            "</section>",
            "</body>",
            "</html>",
        ]
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _load_stage_documents(
    staging_root: Path,
) -> dict[str, dict[str, object]]:
    names = (
        "recovery/candidates.json",
        "recovery/run-summary.json",
        "evidence/evidence.json",
        "evidence/evidence-gate.json",
        "evidence/run-summary.json",
        "planning/plan.json",
        "planning/violations.json",
        "planning/planning-gate.json",
        "planning/run-summary.json",
    )
    return {
        name: _read_json(
            staging_root.joinpath(*name.split("/")),
            name,
        )
        for name in names
    }


def _validate_stage_controls(
    documents: Mapping[str, dict[str, object]],
    *,
    recovery_run_id: str,
    evidence_run_id: str,
    planning_run_id: str,
) -> None:
    recovery_summary = documents["recovery/run-summary.json"]
    evidence_summary = documents["evidence/run-summary.json"]
    planning_summary = documents["planning/run-summary.json"]
    evidence_gate = documents["evidence/evidence-gate.json"]
    planning_gate = documents["planning/planning-gate.json"]
    checks = (
        (
            _member(recovery_summary, "run_id", "/recovery/run-summary"),
            recovery_run_id,
        ),
        (
            _member(evidence_summary, "run_id", "/evidence/run-summary"),
            evidence_run_id,
        ),
        (
            _member(planning_summary, "run_id", "/planning/run-summary"),
            planning_run_id,
        ),
    )
    for actual, expected in checks:
        if actual != expected:
            raise _E2EIssue(
                "E2E_STAGE_OUTPUT_INVALID",
                "/stages/run_id",
                "summaryValue",
                expected="stage result and summary run IDs match",
                actual_type="mismatch",
            )
    for pointer, summary in (
        ("/recovery/run-summary", recovery_summary),
        ("/evidence/run-summary", evidence_summary),
        ("/planning/run-summary", planning_summary),
    ):
        if (
            _member(summary, "completion_status", pointer) != "completed"
            or _member(summary, "network_attempts", pointer) != 0
        ):
            raise _E2EIssue(
                "E2E_STAGE_OUTPUT_INVALID",
                pointer,
                "completedOfflineStage",
                expected="completed stage with zero network attempts",
                actual_type="inconsistent-summary",
            )
    if _member(planning_summary, "llm_calls", "/planning/run-summary") != 0:
        raise _E2EIssue(
            "E2E_STAGE_OUTPUT_INVALID",
            "/planning/run-summary/llm_calls",
            "const",
            expected="0",
            actual_type="nonzero",
        )
    if (
        _member(evidence_summary, "generation_allowed", "/evidence/run-summary")
        is not False
        or _member(evidence_gate, "generation_allowed", "/evidence/evidence-gate")
        is not False
        or _member(planning_gate, "publishable", "/planning/planning-gate")
        is not False
        or _member(
            planning_gate,
            "generation_allowed_input",
            "/planning/planning-gate",
        )
        is not False
    ):
        raise _E2EIssue(
            "E2E_STAGE_OUTPUT_INVALID",
            "/stages/gates",
            "nonPublishableInput",
            expected="false evidence/generation/publishable gates",
            actual_type="elevated-gate",
        )


def _build_top_summary(
    documents: Mapping[str, dict[str, object]],
    report_bytes: bytes,
    staging_root: Path,
) -> dict[str, object]:
    recovery_summary = documents["recovery/run-summary.json"]
    evidence_summary = documents["evidence/run-summary.json"]
    planning_summary = documents["planning/run-summary.json"]
    planning_gate = documents["planning/planning-gate.json"]
    stages: dict[str, object] = {}
    for stage_name in ("recovery", "evidence", "planning"):
        relative = f"{stage_name}/run-summary.json"
        stage_summary = documents[relative]
        try:
            stage_bytes = staging_root.joinpath(
                *relative.split("/")
            ).read_bytes()
        except OSError as error:
            raise _E2EIssue(
                "E2E_STAGE_OUTPUT_INVALID",
                f"/{relative}",
                "readableFile",
                expected="readable stage summary bytes",
                actual_type="unreadable",
                artifact_path=relative,
            ) from error
        stages[stage_name] = {
            "run_id": _string(
                _member(stage_summary, "run_id", f"/{relative}"),
                f"/{relative}/run_id",
            ),
            "summary_path": relative,
            "summary_sha256": _sha256_bytes(stage_bytes),
        }
    return {
        "schema_version": "wu5-e2e-demo-run/1.0",
        "run_id": _string(
            _member(planning_summary, "run_id", "/planning/run-summary"),
            "/planning/run-summary/run_id",
        ),
        "completion_status": "completed",
        "input": {
            "anchor": _json_clone(
                _member(
                    recovery_summary,
                    "input_fixture_identity",
                    "/recovery/run-summary",
                )
            ),
            "planning": {
                "artifacts": _json_clone(
                    _member(
                        planning_summary,
                        "input_artifacts",
                        "/planning/run-summary",
                    )
                ),
                "file_sha256": _json_clone(
                    _member(
                        planning_summary,
                        "input_file_sha256",
                        "/planning/run-summary",
                    )
                ),
            },
        },
        "stages": stages,
        "result": {
            "planning_status": _string(
                _member(
                    planning_gate,
                    "planning_status",
                    "/planning/planning-gate",
                ),
                "/planning/planning-gate/planning_status",
            ),
            "draft_created": _boolean(
                _member(
                    planning_gate,
                    "draft_created",
                    "/planning/planning-gate",
                ),
                "/planning/planning-gate/draft_created",
            ),
            "publishable": _boolean(
                _member(
                    planning_gate,
                    "publishable",
                    "/planning/planning-gate",
                ),
                "/planning/planning-gate/publishable",
            ),
            "generation_allowed_input": _boolean(
                _member(
                    planning_gate,
                    "generation_allowed_input",
                    "/planning/planning-gate",
                ),
                "/planning/planning-gate/generation_allowed_input",
            ),
            "scheduled_count": _integer(
                _member(
                    planning_summary,
                    "scheduled_candidate_count",
                    "/planning/run-summary",
                ),
                "/planning/run-summary/scheduled_candidate_count",
            ),
            "blocked_count": _integer(
                _member(
                    planning_summary,
                    "blocked_seed_count",
                    "/planning/run-summary",
                ),
                "/planning/run-summary/blocked_seed_count",
            ),
        },
        "report": {
            "path": "report/index.html",
            "sha256": _sha256_bytes(report_bytes),
        },
        "network_attempts": 0,
        "llm_calls": 0,
    }


def _validate_html(report_bytes: bytes, *, no_plan: bool) -> None:
    if report_bytes.startswith(b"\xef\xbb\xbf"):
        raise _E2EIssue(
            "E2E_RENDER_INVALID",
            "/report/index.html",
            "utf8",
            expected="UTF-8 without BOM",
            actual_type="utf8-bom",
            artifact_path="report/index.html",
        )
    try:
        text = report_bytes.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise _E2EIssue(
            "E2E_RENDER_INVALID",
            "/report/index.html",
            "utf8",
            expected="strict UTF-8",
            actual_type="invalid-utf8",
            artifact_path="report/index.html",
        ) from error
    parser = _HTMLAuditParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception as error:
        raise _E2EIssue(
            "E2E_RENDER_INVALID",
            "/report/index.html",
            "htmlParse",
            expected="parseable static HTML",
            actual_type="invalid-html",
            artifact_path="report/index.html",
        ) from error
    expected_sections = [
        "status",
        "no-plan" if no_plan else "itinerary",
        "blockers",
        "evidence",
        "conditions",
        "audit",
    ]
    if (
        parser.forbidden_tag
        or parser.section_ids != expected_sections
        or tuple(parser.links) != tuple(item[1] for item in _AUDIT_LINKS)
    ):
        raise _E2EIssue(
            "E2E_RENDER_INVALID",
            "/report/index.html",
            "staticDocument",
            expected="fixed offline sections and relative audit links",
            actual_type="unexpected-html-structure",
            artifact_path="report/index.html",
        )
    for href in parser.links:
        parsed = urlsplit(href)
        if (
            parsed.scheme
            or parsed.netloc
            or href.startswith(("/", "\\"))
            or "\\" in href
        ):
            raise _E2EIssue(
                "E2E_RENDER_INVALID",
                "/report/index.html",
                "relativeLink",
                expected="fixed relative artifact link",
                actual_type="external-link",
                artifact_path="report/index.html",
            )


def _validate_prepared(
    staging_root: Path,
    report_bytes: bytes,
    summary_document: dict[str, object],
    summary_bytes: bytes,
) -> None:
    files = _relative_files(staging_root)
    if files != _EXPECTED_FILES:
        raise _E2EIssue(
            "E2E_TRANSACTION_FAILED",
            "/output/files",
            "exactFileSet",
            expected="13 approved output files",
            actual_type=f"file-count-{len(files)}",
        )
    try:
        installed_report = (
            staging_root / "report" / "index.html"
        ).read_bytes()
        installed_summary = (staging_root / "run-summary.json").read_bytes()
    except OSError as error:
        raise _E2EIssue(
            "E2E_TRANSACTION_FAILED",
            "/output",
            "readback",
            expected="readable prepared report and summary",
            actual_type="unreadable",
        ) from error
    if installed_report != report_bytes or installed_summary != summary_bytes:
        raise _E2EIssue(
            "E2E_OUTPUT_HASH_MISMATCH",
            "/output",
            "preparedBytes",
            expected="prepared bytes",
            actual_type="mismatch",
        )
    loaded_summary = _read_json(
        staging_root / "run-summary.json",
        "run-summary.json",
    )
    if loaded_summary != summary_document:
        raise _E2EIssue(
            "E2E_OUTPUT_HASH_MISMATCH",
            "/run-summary.json",
            "jsonReadback",
            expected="prepared top-level summary",
            actual_type="mismatch",
        )
    result = _object(
        _member(summary_document, "result", "/run-summary"),
        "/run-summary/result",
    )
    no_plan = (
        _member(result, "planning_status", "/run-summary/result")
        == "no_plan_found"
    )
    _validate_html(report_bytes, no_plan=no_plan)
    forbidden_path = str(staging_root)
    if (
        forbidden_path.encode("utf-8") in report_bytes
        or forbidden_path.encode("utf-8") in summary_bytes
    ):
        raise _E2EIssue(
            "E2E_RENDER_INVALID",
            "/output",
            "relativePathsOnly",
            expected="no staging absolute paths",
            actual_type="absolute-path",
        )


def _install_directory(staging_root: Path, output_root: Path) -> None:
    if output_root.exists() or output_root.is_symlink():
        raise _E2EIssue(
            "E2E_OUTPUT_ROOT_INVALID",
            "/output_root",
            "mustNotExist",
            expected="missing output root",
            actual_type="existing-path",
            artifact_path="output_root",
        )
    try:
        os.replace(staging_root, output_root)
    except OSError as error:
        raise _E2EIssue(
            "E2E_TRANSACTION_FAILED",
            "/output_root",
            "sameParentDirectoryInstall",
            expected="one same-parent directory installation",
            actual_type="install-failure",
            artifact_path="output_root",
        ) from error


def _validate_installed(
    output_root: Path,
    report_bytes: bytes,
    summary_bytes: bytes,
) -> None:
    try:
        installed_report = (
            output_root / "report" / "index.html"
        ).read_bytes()
        installed_summary = (output_root / "run-summary.json").read_bytes()
    except OSError as error:
        raise _E2EIssue(
            "E2E_OUTPUT_HASH_MISMATCH",
            "/output",
            "installedReadback",
            expected="readable installed report and summary",
            actual_type="unreadable",
        ) from error
    if (
        installed_report != report_bytes
        or installed_summary != summary_bytes
        or _relative_files(output_root) != _EXPECTED_FILES
    ):
        raise _E2EIssue(
            "E2E_OUTPUT_HASH_MISMATCH",
            "/output",
            "installedBytes",
            expected="prepared 13-file output",
            actual_type="mismatch",
        )


def _cleanup_tree(path: Path | None) -> bool:
    if path is None or not path.exists():
        return True
    if path.is_symlink() or not path.is_dir():
        return False
    try:
        shutil.rmtree(path)
    except OSError:
        return False
    return not path.exists()


def _safe_stage_problems(
    problems: tuple[ValidationProblem, ...],
    *,
    anchor_root: Path,
    planning_input_root: Path,
    staging_root: Path,
) -> tuple[ValidationProblem, ...]:
    roots = (
        (anchor_root, "input/anchor"),
        (planning_input_root, "input/planning"),
        (staging_root / "recovery", "recovery"),
        (staging_root / "evidence", "evidence"),
        (staging_root / "planning", "planning"),
    )
    normalized: list[ValidationProblem] = []
    for raw in problems:
        raw_path = raw.artifact_path
        if not raw_path:
            normalized.append(raw)
            continue
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            normalized.append(raw)
            continue
        safe_path = "external-input"
        try:
            resolved_candidate = candidate.resolve(strict=False)
            for root, prefix in roots:
                try:
                    relative = resolved_candidate.relative_to(
                        root.resolve(strict=False)
                    )
                except ValueError:
                    continue
                suffix = relative.as_posix()
                safe_path = prefix if suffix == "." else f"{prefix}/{suffix}"
                break
        except OSError:
            safe_path = "external-input"
        normalized.append(
            ValidationProblem(
                error_code=raw.error_code,
                artifact_path=safe_path,
                json_pointer=raw.json_pointer,
                schema_rule=raw.schema_rule,
                expected=raw.expected,
                actual_type=raw.actual_type,
                message=raw.message,
            )
        )
    return tuple(normalized)


def _check_paths(
    anchor_root: object,
    planning_input_root: object,
    output_root: object,
) -> tuple[Path, Path, Path]:
    try:
        checked_anchor = Path(anchor_root)  # type: ignore[arg-type]
        checked_planning = Path(planning_input_root)  # type: ignore[arg-type]
        checked_output = Path(output_root)  # type: ignore[arg-type]
    except TypeError as error:
        raise _E2EIssue(
            "E2E_INPUT_INVALID",
            "/paths",
            "pathType",
            expected="Path-compatible values",
            actual_type="invalid-path-type",
        ) from error
    parent = checked_output.parent
    if (
        checked_output.exists()
        or checked_output.is_symlink()
        or not parent.exists()
        or parent.is_symlink()
        or not parent.is_dir()
    ):
        raise _E2EIssue(
            "E2E_OUTPUT_ROOT_INVALID",
            "/output_root",
            "missingChildOfRegularParent",
            expected="missing output root under existing regular parent",
            actual_type="invalid-output-path",
            artifact_path="output_root",
        )
    return checked_anchor, checked_planning, checked_output


def run_e2e_demo(
    anchor_root: Path,
    planning_input_root: Path,
    output_root: Path,
) -> ValidationResult[E2EDemoSummary]:
    """Run each approved offline stage once and install one static result."""

    try:
        checked_anchor, checked_planning, checked_output = _check_paths(
            anchor_root,
            planning_input_root,
            output_root,
        )
    except _E2EIssue as issue:
        return _failure(issue)

    staging_root: Path | None = None
    installed = False
    completed: ValidationResult[E2EDemoSummary] | None = None
    failure: ValidationResult[E2EDemoSummary] | None = None
    try:
        try:
            staging_root = Path(
                tempfile.mkdtemp(
                    prefix=f".{checked_output.name}.",
                    suffix=".staging",
                    dir=checked_output.parent,
                )
            )
        except OSError as error:
            raise _E2EIssue(
                "E2E_TRANSACTION_FAILED",
                "/output_root",
                "sameParentStaging",
                expected="writable same-parent staging directory",
                actual_type="staging-failure",
                artifact_path="output_root",
            ) from error

        recovery_result = run_wu2_recovery(
            checked_anchor,
            staging_root / "recovery",
        )
        if recovery_result.problems:
            raise _StageRejected(
                _safe_stage_problems(
                    recovery_result.problems,
                    anchor_root=checked_anchor,
                    planning_input_root=checked_planning,
                    staging_root=staging_root,
                )
            )
        if recovery_result.value is None:
            raise _E2EIssue(
                "E2E_INTERNAL_FAILURE",
                "/stages/recovery",
                "resultValue",
                expected="Recovery value or explicit problems",
                actual_type="empty-result",
            )

        evidence_result = run_evidence_runtime(
            staging_root / "recovery",
            staging_root / "evidence",
        )
        if evidence_result.problems:
            raise _StageRejected(
                _safe_stage_problems(
                    evidence_result.problems,
                    anchor_root=checked_anchor,
                    planning_input_root=checked_planning,
                    staging_root=staging_root,
                )
            )
        if evidence_result.value is None:
            raise _E2EIssue(
                "E2E_INTERNAL_FAILURE",
                "/stages/evidence",
                "resultValue",
                expected="Evidence Runtime value or explicit problems",
                actual_type="empty-result",
            )

        planner_result = run_coarse_planner(
            staging_root / "recovery",
            staging_root / "evidence",
            checked_planning,
            staging_root / "planning",
        )
        if planner_result.problems:
            raise _StageRejected(
                _safe_stage_problems(
                    planner_result.problems,
                    anchor_root=checked_anchor,
                    planning_input_root=checked_planning,
                    staging_root=staging_root,
                )
            )
        if planner_result.value is None:
            raise _E2EIssue(
                "E2E_INTERNAL_FAILURE",
                "/stages/planning",
                "resultValue",
                expected="Planner value or explicit problems",
                actual_type="empty-result",
            )

        documents = _load_stage_documents(staging_root)
        _validate_stage_controls(
            documents,
            recovery_run_id=recovery_result.value.run_id,
            evidence_run_id=evidence_result.value.run_id,
            planning_run_id=planner_result.value.run_id,
        )
        report_bytes = _render_html(documents)
        report_root = staging_root / "report"
        try:
            report_root.mkdir()
        except OSError as error:
            raise _E2EIssue(
                "E2E_TRANSACTION_FAILED",
                "/report",
                "exclusiveDirectory",
                expected="new report directory",
                actual_type="directory-failure",
            ) from error
        _write_exclusive(report_root / "index.html", report_bytes)
        top_summary = _build_top_summary(
            documents,
            report_bytes,
            staging_root,
        )
        summary_bytes = _json_bytes(top_summary)
        _write_exclusive(staging_root / "run-summary.json", summary_bytes)
        _validate_prepared(
            staging_root,
            report_bytes,
            top_summary,
            summary_bytes,
        )
        _install_directory(staging_root, checked_output)
        installed = True
        _validate_installed(checked_output, report_bytes, summary_bytes)

        result_value = _object(
            _member(top_summary, "result", "/run-summary"),
            "/run-summary/result",
        )
        output_sha256 = {
            stage_path: _sha256_bytes(
                checked_output.joinpath(
                    *stage_path.split("/")
                ).read_bytes()
            )
            for stage_path in (
                "recovery/run-summary.json",
                "evidence/run-summary.json",
                "planning/run-summary.json",
                "report/index.html",
                "run-summary.json",
            )
        }
        completed = ValidationResult(
            E2EDemoSummary(
                run_id=_string(
                    _member(top_summary, "run_id", "/run-summary"),
                    "/run-summary/run_id",
                ),
                run_summary_path=checked_output / "run-summary.json",
                report_path=checked_output / "report" / "index.html",
                planning_status=_string(
                    _member(
                        result_value,
                        "planning_status",
                        "/run-summary/result",
                    ),
                    "/run-summary/result/planning_status",
                ),
                draft_created=_boolean(
                    _member(
                        result_value,
                        "draft_created",
                        "/run-summary/result",
                    ),
                    "/run-summary/result/draft_created",
                ),
                publishable=_boolean(
                    _member(
                        result_value,
                        "publishable",
                        "/run-summary/result",
                    ),
                    "/run-summary/result/publishable",
                ),
                generation_allowed_input=_boolean(
                    _member(
                        result_value,
                        "generation_allowed_input",
                        "/run-summary/result",
                    ),
                    "/run-summary/result/generation_allowed_input",
                ),
                scheduled_count=_integer(
                    _member(
                        result_value,
                        "scheduled_count",
                        "/run-summary/result",
                    ),
                    "/run-summary/result/scheduled_count",
                ),
                blocked_count=_integer(
                    _member(
                        result_value,
                        "blocked_count",
                        "/run-summary/result",
                    ),
                    "/run-summary/result/blocked_count",
                ),
                network_attempts=0,
                llm_calls=0,
                output_sha256=output_sha256,
            ),
            (),
        )
    except _StageRejected as rejected:
        failure = ValidationResult(None, rejected.problems)
    except _E2EIssue as issue:
        failure = _failure(issue)
    except Exception:
        failure = _failure(
            _E2EIssue(
                "E2E_INTERNAL_FAILURE",
                "/runtime",
                "internal",
                expected="completed deterministic E2E run",
                actual_type="internal-error",
            )
        )

    if completed is not None:
        return completed

    cleanup_ok = _cleanup_tree(staging_root)
    if installed:
        cleanup_ok = _cleanup_tree(checked_output) and cleanup_ok
    if not cleanup_ok:
        return _failure(
            _E2EIssue(
                "E2E_TRANSACTION_FAILED",
                "/output_root",
                "rollback",
                expected="complete rollback",
                actual_type="cleanup-failure",
                artifact_path="output_root",
            )
        )
    if failure is None:
        return _failure(
            _E2EIssue(
                "E2E_INTERNAL_FAILURE",
                "/runtime",
                "terminalResult",
                expected="success or explicit failure",
                actual_type="missing-result",
            )
        )
    return failure


def _problem_json(problem: ValidationProblem) -> str:
    return json.dumps(
        {
            "error_code": problem.error_code,
            "artifact_path": problem.artifact_path,
            "json_pointer": problem.json_pointer,
            "schema_rule": problem.schema_rule,
            "expected": problem.expected,
            "actual_type": problem.actual_type,
            "message": problem.message,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _exit_code(problems: Sequence[ValidationProblem]) -> int:
    if any(
        item.error_code
        in {
            "E2E_RENDER_INVALID",
            "E2E_TRANSACTION_FAILED",
            "E2E_OUTPUT_HASH_MISMATCH",
            "E2E_INTERNAL_FAILURE",
        }
        for item in problems
    ):
        return 5
    if any(
        item.error_code
        in {"E2E_INPUT_INVALID", "E2E_OUTPUT_ROOT_INVALID"}
        for item in problems
    ):
        return 4
    return 2


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: IO[str] | None = None,
    stderr: IO[str] | None = None,
) -> int:
    """Execute the public E2E entry once with stable safe console output."""

    output_stream = sys.stdout if stdout is None else stdout
    error_stream = sys.stderr if stderr is None else stderr
    parser = _SafeArgumentParser(
        prog="python -m trip_decider.e2e_demo",
        add_help=True,
    )
    parser.add_argument("--anchor-root", required=True)
    parser.add_argument("--planning-input-root", required=True)
    parser.add_argument("--output-root", required=True)
    try:
        arguments = parser.parse_args(argv)
    except _E2EIssue as issue:
        problem = _failure(issue).problems[0]
        error_stream.write(_problem_json(problem) + "\n")
        return 4

    result = run_e2e_demo(
        Path(arguments.anchor_root),
        Path(arguments.planning_input_root),
        Path(arguments.output_root),
    )
    if result.problems:
        for problem in result.problems:
            error_stream.write(_problem_json(problem) + "\n")
        return _exit_code(result.problems)
    if result.value is None:
        problem = _problem(
            "E2E_INTERNAL_FAILURE",
            "/runtime",
            "terminalResult",
            expected="summary value",
            actual_type="missing-result",
        )
        error_stream.write(_problem_json(problem) + "\n")
        return 5
    value = result.value
    output_stream.write(
        f"status={value.planning_status} "
        f"scheduled={value.scheduled_count} "
        f"blocked={value.blocked_count} "
        "publishable=false "
        "report=report/index.html\n"
    )
    return 0


__all__ = [
    "E2EDemoSummary",
    "main",
    "run_e2e_demo",
]


if __name__ == "__main__":
    raise SystemExit(main())
