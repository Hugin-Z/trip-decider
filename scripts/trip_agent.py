"""Command-line bridge from Codex to the local trip-decider workbench."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import sys
from collections.abc import Mapping
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from trip_decider.codex_host import (  # noqa: E402
    CodexHostError,
    confirm_trip_run,
    create_trip_run,
    execute_trip_action,
    execute_trip_run,
    get_next_actions,
    revise_trip_run,
    run_trip_until_blocked,
    submit_evidence,
)


def _object(value: str, label: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        raise argparse.ArgumentTypeError(f"{label} must be valid JSON") from None
    if not isinstance(parsed, Mapping):
        raise argparse.ArgumentTypeError(f"{label} must be a JSON object")
    return dict(parsed)


def _base64_object(value: str, label: str) -> dict[str, object]:
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeError):
        raise argparse.ArgumentTypeError(
            f"{label} must be base64-encoded UTF-8 JSON"
        ) from None
    return _object(decoded, label)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Drive the local trip-decider session workbench.",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8765",
        help="Local product URL (default: http://127.0.0.1:8765).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser(
        "create",
        help="Create an unconfirmed run from a structured TravelIntent.",
    )
    create_input = create.add_mutually_exclusive_group(required=True)
    create_input.add_argument(
        "--intent-json",
        type=lambda value: _object(value, "intent"),
    )
    create_input.add_argument(
        "--intent-base64",
        type=lambda value: _base64_object(value, "intent"),
        help="Base64-encoded UTF-8 JSON; robust in Windows PowerShell.",
    )

    for name, help_text in (
        ("confirm", "Confirm a complete run."),
        ("execute", "Execute a confirmed run."),
        ("next", "Return the next structured Agent actions."),
        (
            "run-until-blocked",
            "Execute local tools until web research or user input is required.",
        ),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("run_id")

    revise = commands.add_parser(
        "revise",
        help="Revise a completed run using a structured Revision.",
    )
    revise.add_argument("run_id")
    revision_input = revise.add_mutually_exclusive_group(required=True)
    revision_input.add_argument(
        "--revision-json",
        type=lambda value: _object(value, "revision"),
    )
    revision_input.add_argument(
        "--revision-base64",
        type=lambda value: _base64_object(value, "revision"),
        help="Base64-encoded UTF-8 JSON; robust in Windows PowerShell.",
    )
    run_action = commands.add_parser(
        "run-action",
        help="Execute a registered 12306, AMap, or Planner action.",
    )
    run_action.add_argument("run_id")
    run_action.add_argument("action_id", choices=("railway", "map", "planner"))

    submit = commands.add_parser(
        "submit",
        help="Submit structured evidence for a Codex web action.",
    )
    submit.add_argument("run_id")
    evidence_input = submit.add_mutually_exclusive_group(required=True)
    evidence_input.add_argument(
        "--evidence-json",
        type=lambda value: _object(value, "evidence"),
    )
    evidence_input.add_argument(
        "--evidence-base64",
        type=lambda value: _base64_object(value, "evidence"),
        help="Base64-encoded UTF-8 JSON; robust in Windows PowerShell.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "create":
            result = create_trip_run(
                arguments.intent_json or arguments.intent_base64,
                base_url=arguments.base_url,
            )
        elif arguments.command == "confirm":
            result = confirm_trip_run(
                arguments.run_id,
                base_url=arguments.base_url,
            )
        elif arguments.command == "execute":
            result = execute_trip_run(
                arguments.run_id,
                base_url=arguments.base_url,
            )
        elif arguments.command == "next":
            result = get_next_actions(
                arguments.run_id,
                base_url=arguments.base_url,
            )
        elif arguments.command == "run-until-blocked":
            result = run_trip_until_blocked(
                arguments.run_id,
                base_url=arguments.base_url,
            )
        elif arguments.command == "run-action":
            result = execute_trip_action(
                arguments.run_id,
                arguments.action_id,
                base_url=arguments.base_url,
            )
        elif arguments.command == "submit":
            result = submit_evidence(
                arguments.run_id,
                arguments.evidence_json or arguments.evidence_base64,
                base_url=arguments.base_url,
            )
        else:
            result = revise_trip_run(
                arguments.run_id,
                arguments.revision_json or arguments.revision_base64,
                base_url=arguments.base_url,
            )
    except CodexHostError as error:
        print(
            json.dumps(
                {"ok": False, "error": str(error)},
                ensure_ascii=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
