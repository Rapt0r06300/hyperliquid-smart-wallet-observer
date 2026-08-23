"""VAGUE 1 (#1/#5/#9/#13/#43) — les alertes de rupture, le PnL des refus, la whitelist.

Chaque test verrouille le contrat honnête de son livrable :
  * l'alerte connaît la bande morte et ses DEUX ruptures (la basse = cross-venue only) ;
  * l'OI CONFIRME mais n'est jamais requis ;
  * le PnL des refus mesure sur les marks réels et DIT ses non-mesurables ;
  * la whitelist vide VERROUILLE (deny-by-default), jamais l'inverse.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from hl_observer.funding.funding_previsionnel import (
    NIVEAU_APPROCHE_BASSE, NIVEAU_APPROCHE_HAUTE, NIVEAU_RUPTURE_BASSE, NIVEAU_RUPTURE_HAUTE,
    alerte_rupture,
)

RACINE = Path(__file__).resolve().parents[1]


def _outil(nom):
    spec = importlib.util.spec_from_file_location(nom, RACINE / "tools" / ("%s.py" % nom))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_alerte_les_deux_ruptures_et_la_bande_morte():
    assert alerte_rupture(1.0) is None
    assert alerte_rupture(4.2)["niveau"] == NIVEAU_APPROCHE_HAUTE
    assert alerte_rupture(6.0)["niveau"] == NIVEAU_RUPTURE_HAUTE
    assert alerte_rupture(-4.2)["niveau"] == NIVEAU_APPROCHE_BASSE
    a = alerte_rupture(-6.0)
    assert a["niveau"] == NIVEAU_RUPTURE_BASSE
    assert "CROSS-VENUE" in a["note"]


def test_alerte_l_OI_confirme_mais_n_est_jamais_requis():
    sans = alerte_rupture(4.5)
    avec = alerte_rupture(4.5, delta_oi_pct=3.0)
    faible = alerte_rupture(4.5, delta_oi_pct=0.5)
    assert sans["confirmee_par_oi"] is False and "CONFIRMEE" not in sans["note"]
    assert avec["confirmee_par_oi"] is True and "CONFIRMEE" in avec["note"]
    assert faible["confirmee_par_oi"] is False
    assert alerte_rupture(-6.0, delta_oi_pct=9.0)["confirmee_par_oi"] is False


def test_le_feeder_ECRIT_delta_oi_et_alerte():
    src = (RACINE / "tools" / "ecrire_carry_spot_inputs.py").read_text(encoding="utf-8")
    assert '"delta_oi_pct"' in src and '"alerte_rupture"' in src and "openInterest" in src
    assert "oi_precedent.json" in src


def test_pnl_des_refus_mesure_sur_les_marks_et_classe_par_motif(tmp_path):
    m = _outil("pnl_des_refus")
    cands = [
        {"coin": "HYPE", "direction": "LONG", "current_mid": 100.0, "recorded_at": 0.0,
         "accepte": False, "motif": "EDGE_TROP_FAIBLE"},
        {"coin": "HYPE", "direction": "LONG", "current_mid": 100.0, "recorded_at": 0.0,
         "accepte": True, "motif": "OK"},
        {"coin": "HYPE", "direction": "LONG", "current_mid": None, "recorded_at": 5.0,
         "accepte": False, "motif": "SANS_PRIX"},
    ]
    marks = [{"coin": "HYPE", "ts": t, "mid": px}
             for t, px in ((60.0, 100.2), (120.0, 100.5), (600.0, 101.0))]
    r = m.pnl_des_refus(tmp_path, candidats=cands, marks_rows=marks)
    assert set(r["par_motif"]) == {"EDGE_TROP_FAIBLE", "SANS_PRIX"}
    assert r["par_motif"]["EDGE_TROP_FAIBLE"]["mesures"] == 1
    assert r["non_mesurables"] == 1
    assert "re-mesurer" in r["honnetete"]


def test_pnl_des_refus_sans_donnees_reste_calme(tmp_path):
    m = _outil("pnl_des_refus")
    r = m.pnl_des_refus(tmp_path, candidats=[], marks_rows=[])
    assert r["total_usd"] == 0.0 and r["par_motif"] == {}


def _fill(
    adresse,
    mk,
    ts_ms=1_700_000_000_000,
    *,
    coin="BTC",
    regime=None,
):
    row = {
        "adresse": adresse,
        "side": "LONG",
        "mid_at_fill": 100.0,
        "mid_forward": 100.0 * (1 + mk / 1e4),
        "coin": coin,
        "ts_ms": ts_ms,
    }
    if regime is not None:
        row["regime"] = regime
    return row


def test_whitelist_garde_le_predicteur_robuste_et_rejette_le_contrarien(tmp_path):
    """Une moyenne positive ne suffit plus : la fixture franchit exprès tout le CORE.

    On donne au bon wallet 40 journées indépendantes, deux régimes observés et un
    markout brut +15 bps, soit +6 bps après le coût de suivi de 9 bps. Les votes
    sont homogènes, donc non concentrés et leur borne basse reste positive. Le
    contrarien a la même diversité temporelle mais un markout négatif.
    """
    m = _outil("ecrire_copy_whitelist")
    jour_ms = 86_400_000
    base = 1_700_000_000_000
    bons = [
        _fill(
            "0xBON",
            15.0,
            base + i * jour_ms,
            regime="TREND" if i % 2 == 0 else "RANGE",
        )
        for i in range(40)
    ]
    mauvais = [
        _fill(
            "0xMAUVAIS",
            -6.0,
            base + i * jour_ms,
            regime="TREND" if i % 2 == 0 else "RANGE",
        )
        for i in range(40)
    ]
    r = m.construire_whitelist(tmp_path, fills=bons + mauvais)
    assert [g["adresse"] for g in r["gardes"]] == ["0xBON"]
    assert r["gardes"][0]["verdict_robuste"] == "CANDIDAT"
    detail = next(row for row in r["details"] if row["adresse"] == "0xBON")
    assert detail["n_votes_independants"] >= 20
    assert detail["n_jours"] >= 3
    assert detail["n_regimes_mesures"] >= 2
    assert detail["lcb_net_bps"] > 0
    assert detail["concentration"] <= 0.35
    assert r["rejetes"] == 1


def test_whitelist_VIDE_verrouille_deny_by_default(tmp_path):
    m = _outil("ecrire_copy_whitelist")
    chemin = m.ecrire(tmp_path, fills=[])
    d = json.loads(chemin.read_text(encoding="utf-8"))
    assert d["gardes"] == [] and "verrouille" in d["regle"]


def test_whitelist_historique_trop_court_NON_garde(tmp_path):
    """Deny-by-default de C12 : 3 fills geniaux ne prouvent rien."""
    m = _outil("ecrire_copy_whitelist")
    r = m.construire_whitelist(
        tmp_path,
        fills=[_fill("0xJEUNE", 50.0, 1_700_000_000_000 + i * 1_800_001) for i in range(3)],
    )
    assert r["gardes"] == []
