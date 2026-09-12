from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hyper_smart_observer.audit.archive_audit import write_archive_audit_report  # noqa: E402
from hyper_smart_observer.runtime.archive import (  # noqa: E402
    create_clean_archive,
    default_archive_name,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a clean HyperSmart source archive.")
    parser.add_argument("--root", default=".", help="Project root")
    parser.add_argument("--output-dir", default=None, help="Output directory under project runtime/archives")
    parser.add_argument("--name", default=default_archive_name(), help="Archive file name")
    args = parser.parse_args()
    output_dir = Path(args.output_dir) if args.output_dir else None
    result = create_clean_archive(Path(args.root), output_dir, name=args.name)
    print(f"archive: {result.archive_path}")
    print(f"files_copied: {result.files_copied}")
    print(f"zip_entries: {result.entries}")
    print(f"warnings: {len(result.warnings)}")
    audit_path = write_archive_audit_report(Path(args.root).resolve())
    print(f"archive_audit: {audit_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
