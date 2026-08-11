from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "hl_observer"


def split_supervisor_registry() -> None:
    source = SRC / "ops" / "superviseur_collecteurs.py"
    helper = SRC / "ops" / "collecteur_registry.py"
    text = source.read_text(encoding="utf-8")
    start_marker = "#: 🔴 SOURCE UNIQUE"
    end_marker = "\ndef actif() -> bool:"
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    block = text[start:end].rstrip() + "\n"
    helper_text = '''"""Canonical collector registry and runtime profiles.

Extracted from ``superviseur_collecteurs`` so lifecycle/process supervision stays
small enough to audit. This module is pure configuration/profile selection; it
never launches a process and never performs network or trading actions.
"""
from __future__ import annotations

import os
from typing import Any

''' + block
    helper.write_text(helper_text, encoding="utf-8", newline="\n")
    imports = '''from hl_observer.ops.collecteur_registry import (
    COLLECTEURS_CORE,
    COLLECTEURS_HARVEST,
    COLLECTEURS_MAINTENANCE,
    COLLECTEURS_REQUIS,
    COLLECTEURS_RESEARCH,
    PROFILS_VALIDES,
    REGISTRE,
    collecteurs_pour_profil,
    collecteurs_requis_pour_run,
    experimental_paper_demande,
    normaliser_profil,
    profil_collecteur,
)

'''
    text = text[:start] + imports + text[end + 1 :]
    source.write_text(text, encoding="utf-8", newline="\n")


def split_portable_inventory() -> None:
    source = SRC / "ops" / "portable_clone.py"
    helper = SRC / "ops" / "portable_clone_inventory.py"
    text = source.read_text(encoding="utf-8")
    start_marker = 'MANIFEST_NAME = "PORTABLE_FULL_CLONE_MANIFEST.json"'
    end_marker = "\ndef automatic_destination("
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    block = text[start:end].rstrip() + "\n"
    helper_text = '''"""Inventory, classification and path policy for full portable clones.

Kept separate from clone publication/Git verification so both modules remain
small enough to audit. The policy is fail-closed for secrets, reparse points and
Windows path limits; no runtime state is modified here.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from hl_observer.ops import archive_portable as AP

''' + block
    helper.write_text(helper_text, encoding="utf-8", newline="\n")
    imports = '''from hl_observer.ops.portable_clone_inventory import (
    MAX_WINDOWS_PATH,
    MANIFEST_NAME,
    SCHEMA_VERSION,
    CloneInventory,
    PlannedFile,
    PortableCloneError,
    _assert_reparse_allowed,
    _available_drive_roots,
    _durable_artifact_summary,
    _is_reparse,
    _is_within,
    inventory,
    machine_fingerprint,
)

'''
    text = text[:start] + imports + text[end + 1 :]
    source.write_text(text, encoding="utf-8", newline="\n")


def verify_limits() -> None:
    for rel in ("ops/portable_clone.py", "ops/superviseur_collecteurs.py"):
        path = SRC / rel
        count = len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
        if count > 800:
            raise RuntimeError(f"{rel} still has {count} lines (>800)")
    for rel in ("ops/portable_clone_inventory.py", "ops/collecteur_registry.py"):
        path = SRC / rel
        count = len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
        if count > 800:
            raise RuntimeError(f"new helper {rel} has {count} lines (>800)")


def patch_strategy_gaps() -> None:
    # Imported lazily so the finalizer remains a simple standalone script and
    # the strategy patch can be deleted after its one verified use.
    import finalize_strategy_gaps

    finalize_strategy_gaps.main()


def main() -> None:
    split_supervisor_registry()
    split_portable_inventory()
    verify_limits()
    patch_strategy_gaps()
    print("FINAL_ARCHITECTURE_SPLIT_OK")


if __name__ == "__main__":
    main()
