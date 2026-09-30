from __future__ import annotations

from pathlib import Path

from hl_observer.ops.document_authority import (
    audit_document_authority,
    render_document_authority_report,
)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    issues = audit_document_authority(repo_root)
    print(render_document_authority_report(issues))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
