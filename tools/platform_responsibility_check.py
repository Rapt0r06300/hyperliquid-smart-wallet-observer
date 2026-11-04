#!/usr/bin/env python3
"""Fail-closed runtime contract for the two supported hosted platforms.

This check is deliberately small and dependency-free because it runs before
the repository test suite on both GitHub-hosted Linux and Windows runners.
It validates only platform responsibilities and PAPER safety; it does not
claim that a complete test suite or a release artifact succeeded.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PlatformContract:
    platform: str
    runner: str
    python: str
    required_commands: tuple[str, ...]
    missing_commands: tuple[str, ...]
    paper_flags_ok: bool
    hosted_context_ok: bool
    ok: bool


def _runner_name(system: str) -> str:
    if system == "Linux":
        return "ubuntu-latest"
    if system == "Windows":
        return "windows-latest"
    return "unsupported"


def _required_commands(system: str) -> tuple[str, ...]:
    if system == "Linux":
        return ("bash", "git", "python")
    if system == "Windows":
        return ("cmd", "git", "python", "pwsh")
    return ()


def _which(command: str) -> str | None:
    if command == "cmd":
        candidate = os.environ.get("COMSPEC") or "cmd.exe"
        return candidate if os.path.isfile(candidate) or shutil.which(candidate) else None
    return shutil.which(command)


def evaluate(*, hosted_required: bool = False) -> PlatformContract:
    system = platform.system()
    required = _required_commands(system)
    missing = tuple(command for command in required if _which(command) is None)
    paper_flags_ok = all(
        os.environ.get(name, "").strip().casefold() in {"0", "false", "no"}
        for name in (
            "HL_ENABLE_MAINNET_EXECUTION",
            "HL_ENABLE_TESTNET_EXECUTION",
            "REAL_MAINNET_TRADING",
            "TESTNET_EXECUTION_ENABLED",
        )
    )
    hosted_context_ok = not hosted_required or os.environ.get("GITHUB_ACTIONS", "").casefold() == "true"
    return PlatformContract(
        platform=system,
        runner=_runner_name(system),
        python=sys.executable,
        required_commands=required,
        missing_commands=missing,
        paper_flags_ok=paper_flags_ok,
        hosted_context_ok=hosted_context_ok,
        ok=system in {"Linux", "Windows"}
        and not missing
        and paper_flags_ok
        and hosted_context_ok,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hosted", action="store_true", help="require GitHub-hosted context")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable report")
    args = parser.parse_args(argv)
    report = evaluate(hosted_required=args.hosted)
    payload = asdict(report)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"platform={report.platform} runner={report.runner} ok={str(report.ok).lower()}")
        if report.missing_commands:
            print("missing_commands=" + ",".join(report.missing_commands))
        if not report.paper_flags_ok:
            print("paper_flags_ok=false")
        if not report.hosted_context_ok:
            print("hosted_context_ok=false")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
