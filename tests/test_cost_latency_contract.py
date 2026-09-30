"""P1B — contrat coûts/latence : pas de double comptage, latence étiquetée honnêtement."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.simulation import cost_latency_contract as K  # noqa: E402


# --- §3.4 taxonomie de latence ----------------------------------------------
def test_segment_mesure_de_deux_horodatages_reels():
    tax = K.taxonomie_latence({"exchange_ts_ms": 1000, "receive_ts_ms": 1040})
    assert tax["exchange_to_receive_ms"] == {"value_ms": 40.0, "statut": K.MEASURED}


def test_segment_sans_horodatage_est_unmeasurable_jamais_zero():
    tax = K.taxonomie_latence({"exchange_ts_ms": 1000})       # receive absent
    assert tax["exchange_to_receive_ms"]["statut"] == K.UNMEASURABLE
    assert tax["exchange_to_receive_ms"]["value_ms"] is None
    assert "exchange_to_receive_ms" in tax["unmeasurable"]


def test_horodatage_incoherent_ne_fabrique_pas_de_latence_mesuree():
    tax = K.taxonomie_latence({"decision_ts_ms": 1000, "fill_ts_ms": 950})   # fill avant décision
    assert tax["decision_to_fill_ms"]["statut"] == K.UNMEASURABLE
    assert tax["decision_to_fill_ms"].get("note") == "HORODATAGE_INCOHERENT"


def test_execution_externe_est_assumed_jamais_measured():
    tax = K.taxonomie_latence({}, assumed_external_execution_ms=300.0)
    assert tax["assumed_external_execution_ms"] == {"value_ms": 300.0, "statut": K.ASSUMED}


def test_latency_markout_bps_mesure_si_deux_mids():
    tax = K.taxonomie_latence({}, mid_decision=100.0, mid_fill=100.05, side="BUY")
    assert tax["latency_markout_bps"]["statut"] == K.MEASURED
    assert tax["latency_markout_bps"]["value_bps"] == 5.0


def test_latency_markout_unmeasurable_sans_mid_fill():
    tax = K.taxonomie_latence({}, mid_decision=100.0, side="BUY")
    assert tax["latency_markout_bps"]["statut"] == K.UNMEASURABLE


def test_signal_age_mesure_si_fourni():
    tax = K.taxonomie_latence({}, signal_age_ms=420.0)
    assert tax["signal_age_ms"] == {"value_ms": 420.0, "statut": K.MEASURED}


# --- §3.3 convention de coûts : aucun double comptage -----------------------
def test_frais_explicites_comptes_une_fois():
    comps = [
        K.ComposanteCout("spread", 3.0, included_in_price=True),     # déjà dans le prix
        K.ComposanteCout("slippage", 2.0, included_in_price=True),   # déjà dans le prix
        K.ComposanteCout("fees", 4.5, included_in_price=False),      # déduit une fois
    ]
    r = K.verifier_convention_couts(gross_edge_bps=20.0, composantes=comps)
    assert r.verdict == "OK" and r.net_bps == 15.5           # 20 - 4.5 (spread/slippage déjà dans gross)
    assert r.double_comptes == ()


def test_latence_dans_le_prix_et_explicite_est_un_double_compte():
    # La latence causale est DÉJÀ dans le prix ; une taxe scalaire par-dessus la re-compte.
    comps = [
        K.ComposanteCout("latency", 2.0, included_in_price=True),    # dérive causale, dans le prix
        K.ComposanteCout("latency", 2.0, included_in_price=False),   # + taxe scalaire = double
        K.ComposanteCout("fees", 4.5, included_in_price=False),
    ]
    r = K.verifier_convention_couts(gross_edge_bps=20.0, composantes=comps)
    assert r.verdict == "DOUBLE_COMPTE" and "latency" in r.double_comptes


def test_net_unmeasurable_si_gross_absent():
    comps = [K.ComposanteCout("fees", 4.5, included_in_price=False)]
    r = K.verifier_convention_couts(gross_edge_bps=None, composantes=comps)
    assert r.net_bps is None and r.verdict == "UNMEASURABLE"


def test_couts_tous_dans_le_prix_net_egale_gross():
    comps = [
        K.ComposanteCout("spread", 3.0, included_in_price=True),
        K.ComposanteCout("slippage", 2.0, included_in_price=True),
    ]
    r = K.verifier_convention_couts(gross_edge_bps=12.0, composantes=comps)
    assert r.net_bps == 12.0 and r.verdict == "OK"           # rien à re-déduire


def test_to_dict_marque_real_execution_false():
    r = K.verifier_convention_couts(20.0, [K.ComposanteCout("fees", 4.5, included_in_price=False)])
    d = r.to_dict()
    assert d["real_execution"] is False and d["schema_version"] == K.SCHEMA_VERSION
    assert d["net_bps"] == 15.5


# --- §5.3 contrat d'horloge -------------------------------------------------
def _event_complet(**over):
    ev = {"exchange_ts_ms": 1000, "receive_ts_ms": 1005, "normalize_ts_ms": 1006,
          "signal_ts_ms": 1007, "decision_ts_ms": 1008, "fill_ts_ms": 1258,
          "receive_monotonic_ns": 123456789}
    ev.update(over)
    return ev


def test_contrat_horloges_complet():
    r = K.valider_contrat_horloges(_event_complet())
    assert r["statut"] == "COMPLET" and r["manquants"] == [] and r["ordre_causal_ok"] is True


def test_contrat_horloges_incomplet_liste_les_manquants_jamais_now():
    ev = _event_complet()
    del ev["signal_ts_ms"]
    r = K.valider_contrat_horloges(ev)
    assert r["statut"] == "INCOMPLET" and "signal_ts_ms" in r["manquants"]


def test_contrat_horloges_ordre_incoherent():
    r = K.valider_contrat_horloges(_event_complet(fill_ts_ms=900))    # fill avant tout le reste
    assert r["statut"] == "ORDRE_INCOHERENT" and r["ordre_causal_ok"] is False
    assert any("fill_ts_ms" in v for v in r["violations_ordre"])


def test_contrat_horloges_monotonic_requis():
    ev = _event_complet()
    del ev["receive_monotonic_ns"]
    r = K.valider_contrat_horloges(ev)
    assert r["statut"] == "INCOMPLET" and r["monotonic_present"] is False


def test_contrat_horloges_monotonic_optionnel():
    ev = _event_complet()
    del ev["receive_monotonic_ns"]
    r = K.valider_contrat_horloges(ev, exiger_monotonic=False)
    assert r["statut"] == "COMPLET"
