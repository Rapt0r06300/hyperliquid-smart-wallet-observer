"""Local CLI for the append-only Codex Discovery V3.1 hypothesis ledger."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
for _path in (_SRC, _REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from hl_observer.research.hypothesis_ledger import (  # noqa: E402
    HypothesisValidationError,
    append_record,
    challenger_required,
    compact_status,
    load_records,
    novelty_score,
    rediscovery_required,
    semantic_fingerprint,
    validate_record,
)

DEFAULT_LEDGER = Path("runtime/codex_research/HYPOTHESIS_LEDGER.jsonl")


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HypothesisValidationError(f"cannot read hypothesis JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise HypothesisValidationError("hypothesis JSON must be an object")
    return payload


def _emit(payload: Mapping[str, Any], *, stream=None) -> None:
    target = stream or sys.stdout
    print(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        file=target,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage the local Codex Discovery V3.1 hypothesis ledger"
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=DEFAULT_LEDGER,
        help="Append-only JSONL ledger path",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    register = sub.add_parser("register", help="Validate and append one hypothesis record")
    register.add_argument("json_path", type=Path)

    score = sub.add_parser("score", help="Score structural novelty without writing")
    score.add_argument("json_path", type=Path)

    status = sub.add_parser("status", help="Emit a compact research-state summary")
    status.add_argument(
        "--family",
        choices=("copy_vault", "lead_lag", "cross_venue_dislocation_v2"),
    )

    rediscovery = sub.add_parser(
        "needs-rediscovery",
        help="Check whether a research lineage must pivot back to Discovery",
    )
    rediscovery.add_argument("hypothesis_id")

    challenger = sub.add_parser(
        "needs-challenger",
        help="Check whether an improving lineage must face orthogonal challengers",
    )
    challenger.add_argument("hypothesis_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        history = load_records(args.ledger)

        if args.command == "register":
            record = append_record(args.ledger, _load_json(args.json_path))
            _emit(
                {
                    "status": "REGISTERED",
                    "record_id": record["record_id"],
                    "hypothesis_id": record["hypothesis_id"],
                    "family": record["family"],
                    "stage": record["stage"],
                    "semantic_fingerprint": semantic_fingerprint(record),
                    "novelty_score": novelty_score(record, history),
                    "ledger": str(args.ledger),
                }
            )
            return 0

        if args.command == "score":
            candidate = validate_record(_load_json(args.json_path))
            fingerprint = semantic_fingerprint(candidate)
            fingerprints = {semantic_fingerprint(item) for item in history}
            _emit(
                {
                    "status": "SCORED",
                    "hypothesis_id": candidate["hypothesis_id"],
                    "family": candidate["family"],
                    "semantic_fingerprint": fingerprint,
                    "duplicate": fingerprint in fingerprints,
                    "novelty_score": novelty_score(candidate, history),
                }
            )
            return 0

        if args.command == "status":
            _emit(compact_status(history, args.family))
            return 0

        if args.command == "needs-rediscovery":
            required = rediscovery_required(history, args.hypothesis_id)
            _emit(
                {
                    "status": "REDISCOVERY_REQUIRED" if required else "CONTINUE",
                    "hypothesis_id": args.hypothesis_id,
                    "rediscovery_required": required,
                }
            )
            return 0

        if args.command == "needs-challenger":
            required = challenger_required(history, args.hypothesis_id)
            _emit(
                {
                    "status": "CHALLENGER_REQUIRED" if required else "CONTINUE",
                    "hypothesis_id": args.hypothesis_id,
                    "challenger_required": required,
                }
            )
            return 0

        raise HypothesisValidationError(f"unsupported command: {args.command}")
    except HypothesisValidationError as exc:
        _emit({"status": "BLOCKED", "error": str(exc)}, stream=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
