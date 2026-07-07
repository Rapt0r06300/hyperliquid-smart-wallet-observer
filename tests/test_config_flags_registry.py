"""AUDIT-C: le générateur de registre de flags produit un markdown cohérent."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("gen_config_flags", ROOT / "tools" / "gen_config_flags.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)


def test_build_markdown_marks_dead_flags():
    data = {"code": {"HYPERSMART_A": 3, "HYPERSMART_B": 1}, "launcher": {"HYPERSMART_A", "HYPERSMART_DEAD"}}
    md = gen.build_markdown(data)
    assert "HYPERSMART_A" in md and "HYPERSMART_DEAD" in md
    assert "MORT" in md                       # le flag launcher sans consommateur code
    assert "Flags morts à retirer" in md
    assert "`HYPERSMART_DEAD`" in md


def test_real_scan_has_no_dead_flag_after_cleanup():
    data = gen.scan()
    dead = [f for f in data["launcher"] if f not in data["code"]]
    assert dead == []   # ALLOW_MARKET_FLOW_SOLO retiré → plus aucun flag mort
