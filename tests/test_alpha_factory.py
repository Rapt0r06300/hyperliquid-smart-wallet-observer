"""ALPHA FACTORY — ligne canonique, coût total honnête, registre append-only, table triée candidats d'abord."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import alpha_factory as F  # noqa: E402


def test_ligne_canonique_defaut_unmeasurable():
    r = F.ligne_canonique("idee X", config_frozen={"h": 1}, verdict="KILL")
    assert r["gross_bps"] == F.UNMEASURABLE and r["capacity_usd"] == F.UNMEASURABLE
    assert r["idea"] == "idee X" and r["verdict"] == "KILL"


def test_cout_total_somme_les_composantes_mesurables():
    r = F.ligne_canonique("i", config_frozen="c", verdict="KILL",
                          fees_bps=9.0, spread_bps=1.0)  # slippage/latency non fournis
    assert r["cost_total_bps"] == 10.0 and r["cost_incomplet"] is True


def test_cout_total_unmeasurable_si_rien():
    r = F.ligne_canonique("i", config_frozen="c", verdict="MORE_DATA")
    assert r["cost_total_bps"] == F.UNMEASURABLE and r["cost_incomplet"] is True


def test_registre_append_et_relit(tmp_path):
    reg = F.TrialRegistry(str(tmp_path / "reg.jsonl"))
    reg.record(F.ligne_canonique("a", config_frozen="c1", verdict="KILL", net_bps=-8.0))
    reg.record(F.ligne_canonique("b", config_frozen="c2", verdict="MORE_DATA"))
    rows = reg.load()
    assert len(rows) == 2 and rows[0]["idea"] == "a"


def test_emit_table_candidats_en_tete():
    rows = [
        F.ligne_canonique("mort", config_frozen="c", verdict="KILL", lcb_net_bps=-8.0),
        F.ligne_canonique("vivant", config_frozen="c", verdict="CANDIDAT", lcb_net_bps=5.0),
    ]
    t = F.emit_table(rows)
    assert "IDEA | CONFIG FROZEN" in t
    # le candidat doit apparaître avant le KILL
    assert t.index("vivant") < t.index("mort")
