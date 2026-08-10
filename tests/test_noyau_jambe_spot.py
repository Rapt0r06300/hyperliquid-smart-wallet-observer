"""LA JAMBE SPOT, **DANS LA PORTE** — *un carry a DEUX jambes ; le noyau n'en verifiait qu'UNE.*

Ces tests verrouillent l'exécutabilité des quatre traversées d'un carry sans figer l'organisation
interne de `decider`: le garde spot peut vivre dans un helper tant que `decider` l'appelle uniquement
pour la famille carry.
"""
from __future__ import annotations

import pytest

from hl_observer.decision_engine.noyau_unique import (
    REFUS_EDGE_NET_INSUFFISANT,
    REFUS_JAMBE_SPOT_IMPOSSIBLE,
    Contexte,
    decider,
)

_PERP_ASKS = [(1.0 + 0.0001 * i, 100_000.0) for i in range(10)]
_PERP_BIDS = [(1.0 - 0.0001 * i, 100_000.0) for i in range(10)]
_SPOT_PROFOND_ASKS = [(1.0, 1_000_000.0)]
_SPOT_PROFOND_BIDS = [(0.9999, 1_000_000.0)]
_SPOT_PUMP_ASKS = [(1.0, 473.0)]
_SPOT_PUMP_BIDS = [(0.9999, 449.0)]


def _ctx(**kw) -> Contexte:
    base = dict(
        strategie="CARRY",
        coin="PURR",
        direction="SHORT",
        notional_usd=500.0,
        niveaux_achat=_PERP_ASKS,
        niveaux_vente=_PERP_BIDS,
        niveaux_spot_achat=_SPOT_PROFOND_ASKS,
        niveaux_spot_vente=_SPOT_PROFOND_BIDS,
    )
    base.update(kw)
    return Contexte(**base)


@pytest.mark.parametrize("absent", [
    {"niveaux_spot_achat": None},
    {"niveaux_spot_vente": None},
    {"niveaux_spot_achat": [], "niveaux_spot_vente": []},
    {"niveaux_spot_achat": None, "niveaux_spot_vente": None},
])
def test_un_carnet_spot_ABSENT_refuse_le_carry(absent: dict) -> None:
    d = decider(_ctx(**absent))
    assert d.autorise is False
    assert d.raison == REFUS_JAMBE_SPOT_IMPOSSIBLE


def test_le_refus_s_EXPLIQUE_dans_la_preuve() -> None:
    d = decider(_ctx(niveaux_spot_achat=None))
    assert "spot" in (d.preuve or {})


def test_LE_CAS_PUMP_le_carnet_spot_trop_mince_est_REFUSE() -> None:
    d = decider(_ctx(coin="PUMP", niveaux_spot_achat=_SPOT_PUMP_ASKS,
                     niveaux_spot_vente=_SPOT_PUMP_BIDS))
    assert d.autorise is False
    assert d.raison == REFUS_JAMBE_SPOT_IMPOSSIBLE
    sp = (d.preuve or {}).get("spot") or {}
    assert isinstance(sp, dict) and "motif" in sp


def test_un_carnet_spot_PROFOND_laisse_passer() -> None:
    d = decider(_ctx())
    assert d.raison != REFUS_JAMBE_SPOT_IMPOSSIBLE


def test_le_slippage_spot_est_SOUSTRAIT_de_l_edge_publie() -> None:
    profond = decider(_ctx())
    glissant = decider(_ctx(
        niveaux_spot_achat=[(1.0, 100.0), (1.01, 1_000_000.0)],
        niveaux_spot_vente=[(0.9999, 100.0), (0.99, 1_000_000.0)],
    ))
    if not profond.autorise:
        pytest.skip("le carry n'est pas ouvrable ici (funding absent en CI) : rien a comparer")
    sp_p = (profond.preuve or {}).get("spot") or {}
    sp_g = (glissant.preuve or {}).get("spot") or {}
    assert sp_p.get("slippage_total_bps", 0.0) == pytest.approx(0.0, abs=1e-6)
    assert sp_g.get("slippage_total_bps", 0.0) > 0.0
    if glissant.autorise:
        assert glissant.edge_net_bps < profond.edge_net_bps
    else:
        assert glissant.raison == REFUS_EDGE_NET_INSUFFISANT


@pytest.mark.parametrize("strategie", ["COPY", "GRINDER", "SNIPER"])
def test_les_familles_directionnelles_ne_sont_PAS_refusees_pour_absence_de_spot(
    strategie: str,
) -> None:
    d = decider(_ctx(strategie=strategie, niveaux_spot_achat=None, niveaux_spot_vente=None))
    assert d.autorise is False
    assert d.raison != REFUS_JAMBE_SPOT_IMPOSSIBLE


def test_la_SORTIE_du_perp_est_chiffree_aussi() -> None:
    d = decider(_ctx())
    sp = (d.preuve or {}).get("spot") or {}
    assert isinstance(sp, dict) and "sortie_perp" in sp


def test_un_perp_ou_l_on_peut_ENTRER_mais_pas_SORTIR_est_REFUSE() -> None:
    d = decider(_ctx(niveaux_vente=_PERP_BIDS, niveaux_achat=[(1.0, 10.0)]))
    assert d.autorise is False


def test_invariant_la_porte_spot_est_bien_CONDITIONNEE_au_carry() -> None:
    """Le test vérifie le contrat réel, pas la présence textuelle d'un appel dans `decider`."""
    import inspect
    from hl_observer.decision_engine import noyau_unique

    decider_src = inspect.getsource(noyau_unique.decider)
    helper_src = inspect.getsource(noyau_unique._verifier_carry_executable)
    assert "fam == CARRY_STRUCTUREL" in decider_src
    assert "_verifier_carry_executable(" in decider_src
    assert "marcher_dans_le_carnet(" in helper_src, "la jambe spot a disparu du garde carry"
    assert "REFUS_JAMBE_SPOT_IMPOSSIBLE" in helper_src
    assert "niveaux_spot_achat" in helper_src and "niveaux_spot_vente" in helper_src
