"""La facade historique du diagnostic de carnets : elle DELEGUE, elle ne decide pas.

POURQUOI CE FICHIER EXISTE. La mesure du 21/11/2026 a liste 7 modules qu'aucun test n'atteint.
Celui-ci est une facade de compatibilite : son interet est precisement de ne RIEN classifier
elle-meme (« la verite reste v4 »). Une facade non testee est l'endroit ou un second
classifieur reapparait en silence, et ou deux chemins se mettent a repondre differemment a la
meme question -- c'est exactement le genre d'architecture parallele que le depot refuse.
"""
from __future__ import annotations

from hl_observer.backtesting import lead_lag_causal_gap_compat as F


def test_la_facade_delegue_au_canonique_sans_rien_reclassifier(monkeypatch):
    vus = {}

    def _canonique(shocks, books_par_coin, meta, *, coin, max_book_delay_ms):
        vus.update(shocks=shocks, books=books_par_coin, meta=meta, coin=coin,
                   delai=max_book_delay_ms)
        return {"verdict": "CANONIQUE", "n": 7}

    monkeypatch.setattr(F, "diagnose_causal_book_coverage", _canonique)
    sortie = F.diagnose_causal_book_availability(
        [{"ts_ms": 1}], [{"ts_ms": 2}], coin="eth", max_book_delay_ms=1234,
        microstructure_meta={"x": 1})

    # tout ce que le canonique a decide traverse la facade intact
    assert sortie["verdict"] == "CANONIQUE" and sortie["n"] == 7
    # et la facade lui a bien passe ce qu'on lui a donne
    assert vus["coin"] == "eth" and vus["delai"] == 1234
    assert vus["books"] == {"ETH": [{"ts_ms": 2}]}, "le coin doit etre normalise en MAJUSCULES"
    assert vus["meta"] == {"x": 1}


def test_les_invariants_de_securite_sont_toujours_apposes(monkeypatch):
    """Un diagnostic ne doit JAMAIS pouvoir passer pour un ordre ni pour un changement de strategie."""
    monkeypatch.setattr(F, "diagnose_causal_book_coverage", lambda *a, **k: {})
    sortie = F.diagnose_causal_book_availability([], [])
    assert sortie["paper_read_only"] is True
    assert sortie["real_execution"] is False
    assert sortie["strategy_parameters_changed"] is False
    assert sortie["schema_version"] == F.SCHEMA_VERSION
    assert sortie["purpose"] == "DIAGNOSE_COLLECTOR_GAP_VS_RECORDED_BOOK_CADENCE"


def test_le_canonique_ne_peut_pas_ecraser_un_invariant_de_securite(monkeypatch):
    """Les marques de securite sont apposees APRES le `**result` : elles gagnent toujours."""
    monkeypatch.setattr(F, "diagnose_causal_book_coverage",
                        lambda *a, **k: {"real_execution": True, "paper_read_only": False})
    sortie = F.diagnose_causal_book_availability([], [])
    assert sortie["real_execution"] is False and sortie["paper_read_only"] is True


def test_le_plafond_de_delai_vient_du_canonique_et_non_d_une_copie():
    """Deux constantes qui devraient etre une seule finissent toujours par divergier."""
    from hl_observer.backtesting.lead_lag_causal_diagnostics import (
        DIAGNOSTIC_MAX_BOOK_DELAY_MS,
    )
    assert F.EXECUTABLE_BOOK_LIMIT_MS == DIAGNOSTIC_MAX_BOOK_DELAY_MS


def test_aucun_classifieur_independant_ne_vit_dans_la_facade():
    """La facade ne doit contenir ni seuil ni branche de decision en propre."""
    import inspect

    source = inspect.getsource(F.diagnose_causal_book_availability)
    for interdit in (" if ", "elif ", "while ", "threshold"):
        assert interdit not in source, (
            f"« {interdit} » dans la facade : un second classifieur est en train d'y naitre")


def test_un_appel_reel_de_bout_en_bout_rend_un_diagnostic():
    """Sans monkeypatch : la chaine complete repond, et sa reponse porte les invariants."""
    sortie = F.diagnose_causal_book_availability(
        [{"ts_ms": 1_000, "move_bps": 50.0, "coin": "ETH"}],
        [{"ts_ms": 1_100, "coin": "ETH", "bid": 1.0, "ask": 1.1}],
        coin="ETH")
    assert sortie["schema_version"] == F.SCHEMA_VERSION
    assert sortie["real_execution"] is False
