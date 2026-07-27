"""Importable boundary for the WU1 remediation verification entry.

The entry orchestration is intentionally unimplemented in R1.  R2 freezes its
deterministic contract before R3 supplies behavior.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, TextIO


class VerificationDependencies(Protocol):
    """Explicit dependency boundary used by deterministic contract tests."""


def run_verification(
    repo_root: Path,
    *,
    dependencies: VerificationDependencies,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Run all WU1 verification checks and return the stable exit code."""

    raise NotImplementedError("WU1 remediation verification is not implemented")


def main() -> int:
    """Run the real WU1 verification entry."""

    raise NotImplementedError("WU1 remediation verification is not implemented")
