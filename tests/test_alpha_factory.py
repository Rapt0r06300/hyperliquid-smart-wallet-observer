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


def test_p13_hashes_deterministes_et_trial_id():
    a = F.ligne_canonique("idee", config_frozen="c", verdict="KILL", event="e", horizon="h")
    b = F.ligne_canonique("idee", config_frozen="c", verdict="KILL", event="e", horizon="h")
    diff = F.ligne_canonique("idee", config_frozen="c", verdict="KILL", event="AUTRE", horizon="h")
    assert a["config_hash"] == b["config_hash"]                 # meme config -> meme hash
    assert a["config_hash"] != diff["config_hash"]              # config differente -> hash different
    assert a["trial_id"] == a["config_hash"][:12] and len(a["trial_id"]) == 12


def test_p13_registre_append_only(tmp_path):
    reg = F.TrialRegistry(str(tmp_path / "r.jsonl"))
    reg.record(F.ligne_canonique("a", config_frozen="c", verdict="KILL"))
    reg.record(F.ligne_canonique("b", config_frozen="c", verdict="KILL"))
    reg.record(F.ligne_canonique("c", config_frozen="c", verdict="KILL"))
    assert len(reg.load()) == 3                                 # 3 essais DISTINCTS conserves


def test_fix03_dedup_et_code_sha(tmp_path):
    reg = F.TrialRegistry(str(tmp_path / "r.jsonl"))
    row = F.ligne_canonique("a", config_frozen="c", verdict="KILL", code_sha="deadbeef")
    reg.record(row)
    r2 = reg.record(row)                                        # byte-identique -> dedup
    assert r2.get("_deduped") is True and len(reg.load()) == 1
    assert reg.load()[0]["code_sha"] == "deadbeef"
    # persistance : un nouveau registre relit l'empreinte -> toujours dedup (aucun reset)
    reg2 = F.TrialRegistry(str(tmp_path / "r.jsonl"))
    reg2.record(row)
    assert len(reg2.load()) == 1
    reg2.record(F.ligne_canonique("b", config_frozen="c", verdict="KILL"))   # distinct -> ajoute
    assert len(reg2.load()) == 2


def test_fix34_metriques_distribution_pf_es():
    # PF = gains/|pertes| ; ES = moyenne du pire decile.
    r = F.metriques_distribution([10.0, 20.0, -5.0, -5.0], es_q=0.5)
    assert r["pf"] == 3.0                                        # (10+20)/(5+5)
    assert r["es"] == -5.0 and r["n"] == 4                       # pire 50% = [-5,-5]
    # aucune perte -> downside non mesure -> PF UNMEASURABLE (jamais infini fabrique)
    assert F.metriques_distribution([1.0, 2.0])["pf"] == F.UNMEASURABLE
    # distribution vide -> tout UNMEASURABLE
    vide = F.metriques_distribution([])
    assert vide["pf"] == F.UNMEASURABLE and vide["es"] == F.UNMEASURABLE and vide["n"] == 0


def test_fix34_drawdown_ordonne():
    assert F.drawdown([10.0, -4.0, -3.0, 8.0]) == 7.0            # equity 10,6,3,11 -> pic 10 - creux 3
    assert F.drawdown([5.0]) == F.UNMEASURABLE                   # <2 points -> pas de DD fabrique
    assert F.drawdown([]) == F.UNMEASURABLE


def test_fix34_ligne_porte_pf_es_dd_dans_le_schema():
    # les champs risque font partie du schema canonique (mesurables ou UNMEASURABLE, jamais absents)
    for champ in ("pf", "dd", "es", "n_raw", "n_independent", "capacity_usd", "oos", "forward"):
        assert champ in F.CHAMPS
    r = F.ligne_canonique("i", config_frozen="c", verdict="KILL", pf=1.5, es=-3.0, dd=4.0)
    assert r["pf"] == 1.5 and r["es"] == -3.0 and r["dd"] == 4.0


def test_emit_table_candidats_en_tete():
    rows = [
        F.ligne_canonique("mort", config_frozen="c", verdict="KILL", lcb_net_bps=-8.0),
        F.ligne_canonique("vivant", config_frozen="c", verdict="CANDIDAT", lcb_net_bps=5.0),
    ]
    t = F.emit_table(rows)
    assert "IDEA | CONFIG FROZEN" in t
    # le candidat doit apparaître avant le KILL
    assert t.index("vivant") < t.index("mort")
