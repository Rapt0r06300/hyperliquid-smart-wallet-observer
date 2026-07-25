"""LOT 4 — vérificateur 30 min (verdict pur) + réconciliation registre 8/12 (Flo 25/07)."""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("vrf", _ROOT / "tools" / "verifier_lab_30min.py")
VRF = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(VRF)


def test_registre_8_composants_12_variantes():
    from hl_observer.research_parallel import registre as REG
    importlib.import_module("hl_observer.research_parallel.plugins.lab_data")
    importlib.import_module("hl_observer.research_parallel.plugins.vague1")
    comps = REG.lister()
    assert len(comps) == 8, "DATA_CTX + REGIME_ROUTER + 6 signaux"
    assert REG.total_variantes() == 12 and REG.total_variantes() <= REG.MAX_VARIANTES_TOTAL


def _snap(pid, hb_age, tailles, main_mtimes, ts):
    return {"ts": ts, "run_id": "lab-x", "pid": pid, "heartbeat_age_s": hb_age,
            "tailles": tailles, "main_mtimes": main_mtimes}


def test_verdict_pass_si_tout_va_bien():
    d = _snap(100, 5.0, {"asset_ctx.jsonl": 1000}, {"runtime/data/bbo_heartbeat.json": 10.0}, 0)
    f = _snap(100, 5.0, {"asset_ctx.jsonl": 5000}, {"runtime/data/bbo_heartbeat.json": 20.0}, 1800)
    v = VRF.comparer(d, f)
    assert v["verdict"] == "PASS" and v["pid_unique_stable"] and v["fichiers_ont_grossi"] and v["main_toujours_vivant"]


def test_attention_si_pid_change():
    d = _snap(100, 5.0, {"a.jsonl": 1}, {"runtime/data/bbo_heartbeat.json": 10.0}, 0)
    f = _snap(200, 5.0, {"a.jsonl": 9}, {"runtime/data/bbo_heartbeat.json": 20.0}, 1800)   # PID a changé
    assert VRF.comparer(d, f)["verdict"] == "ATTENTION"


def test_attention_si_fichiers_ne_grossissent_pas():
    d = _snap(100, 5.0, {"a.jsonl": 9}, {"runtime/data/bbo_heartbeat.json": 10.0}, 0)
    f = _snap(100, 5.0, {"a.jsonl": 9}, {"runtime/data/bbo_heartbeat.json": 20.0}, 1800)   # taille figée
    assert VRF.comparer(d, f)["fichiers_ont_grossi"] is False


def test_attention_si_main_gele():
    # le main NE bat PLUS (mtime identique) -> le labo l'aurait impacté -> ATTENTION
    d = _snap(100, 5.0, {"a.jsonl": 1}, {"runtime/data/bbo_heartbeat.json": 10.0}, 0)
    f = _snap(100, 5.0, {"a.jsonl": 9}, {"runtime/data/bbo_heartbeat.json": 10.0}, 1800)
    assert VRF.comparer(d, f)["main_toujours_vivant"] is False
