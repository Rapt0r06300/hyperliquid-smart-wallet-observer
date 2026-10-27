#!/usr/bin/env python3
"""Resolve operator family inputs against the canonical strategy scope.

This small bridge is importable by repository tools and executable from GitHub
workflow scripts without installing the full runtime. The policy itself stays
in ``src/hl_observer/strategies/active_scope.py``.
"""
from __future__ import annotations

import importlib.util
import sys
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

ECONOMIC_INTENTS = frozenset(
    {
        "analyze",
        "replay",
        "backtest",
        "oos",
        "forward_paper",
        "module_pnl_proof",
        "scoreboard",
        "full_cycle",
    }
)
FAMILY_NEUTRAL_INTENTS = frozenset({"start_collection", "drain", "pause", "resume", "retry"})


@lru_cache(maxsize=4)
def _scope_module(root: str):
    scope_path = Path(root) / "src" / "hl_observer" / "strategies" / "active_scope.py"
    if not scope_path.is_file():
        raise ValueError(f"STRATEGY_SCOPE_AUTHORITY_MISSING:{scope_path}")
    name = f"_alina_active_scope_{abs(hash(str(scope_path.resolve())))}"
    spec = importlib.util.spec_from_file_location(name, scope_path)
    if spec is None or spec.loader is None:
        raise ValueError("STRATEGY_SCOPE_AUTHORITY_UNLOADABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def normalize_operator_family(
    intent: str,
    selector: str | None,
    config: Mapping[str, Any] | None,
    *,
    scope_root: str | Path | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return one validated family and a copied config with that family pinned.

    ``all`` is permitted for family-neutral collection/control work. For an
    economic intent it expands only the families in the central active-scope
    authority; with today's single-family scope this resolves to ``copy_vault``.
    A nested active family may resolve the workflow's ``all`` selector, but any
    disabled family is refused. An explicit selector may not conflict with
    nested config.
    """
    if not isinstance(intent, str) or intent not in ECONOMIC_INTENTS | FAMILY_NEUTRAL_INTENTS:
        raise ValueError(f"OPERATOR_INTENT_UNSUPPORTED:{intent!r}")
    if config is None:
        normalized_config: dict[str, Any] = {}
    elif isinstance(config, Mapping):
        normalized_config = dict(config)
    else:
        raise ValueError("OPERATOR_CONFIG_MUST_BE_OBJECT")

    selected = "all" if selector in (None, "") else str(selector).strip().lower()
    if not selected:
        selected = "all"
    nested_raw = normalized_config.get("strategy_family")
    nested: str | None = None
    if nested_raw is not None:
        if not isinstance(nested_raw, str) or not nested_raw.strip():
            raise ValueError("OPERATOR_NESTED_FAMILY_INVALID")
        nested = nested_raw.strip().lower()
    if nested is not None and selected != "all" and selected != nested:
        raise ValueError("OPERATOR_FAMILY_CONFLICT")

    effective = nested if selected == "all" and nested is not None else selected
    root = Path(scope_root) if scope_root is not None else Path(__file__).resolve().parents[1]
    authority = _scope_module(str(root.resolve()))
    active = authority.active_strategy_families()
    if effective != "all" and effective not in active:
        try:
            authority.require_active_strategy(effective)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        raise ValueError(f"DISABLED_BY_SCOPE:{effective}")
    if intent in ECONOMIC_INTENTS and effective == "all":
        if len(active) != 1:
            raise ValueError("ECONOMIC_ALL_SCOPE_NOT_SINGLETON")
        effective = next(iter(active))
    if intent in ECONOMIC_INTENTS and effective not in active:
        raise ValueError("COPY_VAULT_FAMILY_REQUIRED")

    normalized_config["strategy_family"] = effective
    return effective, normalized_config

