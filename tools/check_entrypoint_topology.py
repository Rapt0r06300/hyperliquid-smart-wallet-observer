from __future__ import annotations

from pathlib import Path

from hl_observer.ops.entrypoint_topology import audit_entrypoint_topology, render_entrypoint_topology_report


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    issues = audit_entrypoint_topology(root)
    print(render_entrypoint_topology_report(issues))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
