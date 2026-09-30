"""[CABLAGE replay réel] Rapport IS/OOS/FORWARD depuis des LOGS (chemin unique feed_adapter → pipeline), et
séparation nette d'avec les fixtures synthétiques.

Vérité honnête : des lignes de log sans prix/carnet (rows d'audit) produisent des NO_TRADE (aucun fill fabriqué),
le ledger se réconcilie quand même, et le rapport est étiqueté REEL — jamais confondu avec un run SYNTHETIQUE_DEMO.
Des lignes de tick normalisées (avec carnet) produisent de vrais fills réconciliés.
"""
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.mega_cablage.replay_driver import driver_depuis_logs, rejouer_is_oos_forward   # noqa: E402

T = 1_700_000_000_000


def _tick_row(i):
    px = 60000.0 + i * 10.0
    return {"coin": "BTC", "px": px, "mid": px, "sz": 0.3, "signe": 1 if i % 2 == 0 else -1,
            "ts_ms": T + i * 1000, "vault": "A",
            "book": {"asks": [[px + 10.0, 5.0]], "bids": [[px - 10.0, 5.0]]}}


# Ligne d'audit RÉELLE (forme de logs/structured/decisions.jsonl) : pas de px, pas de ts_ms exploitable.
_AUDIT = {"action": "WATCH", "coin": "ETH", "recorded_at_ms": T + 99000, "net_pnl_usdc": 0.0, "paper_only": True}


def _somme(rap, champ):
    return sum(seg[champ] for seg in rap["segments"].values())


def test_report_reel_logs_melanges_fills_et_no_trade(tmp_path):
    f = tmp_path / "reel.jsonl"
    lignes = [json.dumps(_tick_row(i)) for i in range(12)] + [json.dumps(_AUDIT) for _ in range(4)]
    f.write_text("\n".join(lignes), encoding="utf-8")
    rap = driver_depuis_logs(f, leader_equity_defaut=100000.0)
    assert rap["verdict"]["note"] == "REEL" and rap["reconcilie_partout"] is True
    assert _somme(rap, "fills") > 0        # les ticks normalisés produisent de vrais fills
    assert _somme(rap, "rejets") > 0       # les rows d'audit sans prix -> NO_TRADE honnête


def test_logs_audit_sans_prix_produisent_no_trade_sans_crash(tmp_path):
    f = tmp_path / "audit.jsonl"
    f.write_text("\n".join(json.dumps(_AUDIT) for _ in range(9)), encoding="utf-8")
    rap = driver_depuis_logs(f, leader_equity_defaut=100000.0)
    assert _somme(rap, "fills") == 0 and _somme(rap, "rejets") > 0 and rap["reconcilie_partout"] is True


def test_separation_reel_vs_synthetique(tmp_path):
    f = tmp_path / "reel.jsonl"
    f.write_text("\n".join(json.dumps(_tick_row(i)) for i in range(6)), encoding="utf-8")
    reel = driver_depuis_logs(f, leader_equity_defaut=100000.0)
    synth = rejouer_is_oos_forward([_tick_row(i) for i in range(6)], source="SYNTHETIQUE",
                                   leader_equity_defaut=100000.0)
    assert reel["verdict"]["note"] == "REEL" and synth["verdict"]["note"] == "SYNTHETIQUE_DEMO"
