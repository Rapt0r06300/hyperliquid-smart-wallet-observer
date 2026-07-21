"""LA JAMBE SPOT, **DANS LA PORTE** — *un carry a DEUX jambes ; le noyau n'en verifiait qu'UNE.*

═══════════════════════════════════════════════════════════════════════════════════════════════
LA 18e FORME DE LA MALADIE
═══════════════════════════════════════════════════════════════════════════════════════════════

Le noyau validait le carnet **PERP** (`niveaux_achat` / `niveaux_vente`)... et ignorait
**totalement** le carnet **SPOT**. Or un carry, par definition, a **deux jambes**.

🔑 **CE QUE LA MESURE A TROUVE** (`tools/profondeur_spot.py`, carnets reels) :

    PUMP  -> carnet spot : **473 $ disponibles** pour **500 $** voulus. **IL NE SE REMPLIT PAS.**
             Le bot l'aurait ouvert quand meme.
             ***Un carry dont la jambe spot ne se remplit pas n'est pas un carry :
                c'est un short perp A NU.*** Et le short perp a nu, on l'a mesure : -7,97 bps.

    PURR  -> sa jambe de VENTE spot glisse de **47,5 bps**.
             APR : **11,31 % -> 6,91 %**. *Le prix affiche n'est pas le prix qu'on obtient.*

*Une capacite presente (le module `spot_depth`), un chainon manquant (la porte ne le lisait pas),
personne qui se plaint.* **Encore.**

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QUE CES TESTS VERROUILLENT
═══════════════════════════════════════════════════════════════════════════════════════════════

  1. carnet spot **absent** sur un CARRY  -> **REFUS** (*ne pas savoir n'est pas une permission*)
  2. carnet spot **trop mince**           -> **REFUS**
  3. le **slippage spot est SOUSTRAIT** de l'edge publie
     (*un cout qu'on mesure mais qu'on ne soustrait pas est un cout qu'on CACHE* -- 17e fois)
  4. la porte spot ne s'applique **qu'au carry** (pas de fuite vers les autres familles)

Aucun ordre reel. Paper-only.
"""
from __future__ import annotations

import pytest

from hl_observer.decision_engine.noyau_unique import (
    REFUS_EDGE_NET_INSUFFISANT,
    REFUS_JAMBE_SPOT_IMPOSSIBLE,
    Contexte,
    decider,
)

# carnets PERP profonds : ils ne doivent JAMAIS etre la cause du refus dans ces tests.
_PERP_ASKS = [(1.0 + 0.0001 * i, 100_000.0) for i in range(10)]
_PERP_BIDS = [(1.0 - 0.0001 * i, 100_000.0) for i in range(10)]

# carnet SPOT profond -> slippage ~0
_SPOT_PROFOND_ASKS = [(1.0, 1_000_000.0)]
_SPOT_PROFOND_BIDS = [(0.9999, 1_000_000.0)]

# 🔴 LE CARNET DE PUMP, dans sa forme mesuree : il ne porte PAS 500 $.
_SPOT_PUMP_ASKS = [(1.0, 473.0)]          # 473 $ dispo
_SPOT_PUMP_BIDS = [(0.9999, 449.0)]       # 449 $ dispo


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


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  1. UN CARNET SPOT ABSENT = UN REFUS. *Une jambe non verifiee n'est pas une jambe sure.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("absent", [
    {"niveaux_spot_achat": None},
    {"niveaux_spot_vente": None},
    {"niveaux_spot_achat": [], "niveaux_spot_vente": []},
    {"niveaux_spot_achat": None, "niveaux_spot_vente": None},
])
def test_un_carnet_spot_ABSENT_refuse_le_carry(absent: dict) -> None:
    d = decider(_ctx(**absent))
    assert d.autorise is False
    assert d.raison == REFUS_JAMBE_SPOT_IMPOSSIBLE, (
        "un carry SANS jambe spot verifiee est un short perp A NU -- et le short a nu, "
        "on l'a mesure : -7,97 bps. **Il doit etre REFUSE.**"
    )


def test_le_refus_s_EXPLIQUE_dans_la_preuve() -> None:
    """*Un refus muet est un refus qu'on ne peut pas auditer.*"""
    d = decider(_ctx(niveaux_spot_achat=None))
    assert "spot" in (d.preuve or {})


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  2. 🔑 LE CAS PUMP — **le carnet mesure qui ne porte pas notre taille.**
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_LE_CAS_PUMP_le_carnet_spot_trop_mince_est_REFUSE() -> None:
    """🔴 Mesure reelle : le carnet spot de PUMP porte **473 $**. On en veut **500 $**.

    ***Le bot l'aurait ouvert.*** Ce test est la pour que ca n'arrive plus jamais.
    """
    d = decider(_ctx(coin="PUMP",
                     niveaux_spot_achat=_SPOT_PUMP_ASKS,
                     niveaux_spot_vente=_SPOT_PUMP_BIDS))
    assert d.autorise is False
    assert d.raison == REFUS_JAMBE_SPOT_IMPOSSIBLE
    sp = (d.preuve or {}).get("spot") or {}
    assert isinstance(sp, dict) and "motif" in sp


def test_un_carnet_spot_PROFOND_laisse_passer() -> None:
    """Le garde ne doit pas refuser TOUT -- *un garde-fou qui refuse tout est CASSE.* (4e fois.)"""
    d = decider(_ctx())
    assert d.raison != REFUS_JAMBE_SPOT_IMPOSSIBLE, (
        "avec un carnet spot profond, la jambe spot ne doit PAS etre la cause d'un refus"
    )


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  3. 🔴 LE SLIPPAGE SPOT DOIT ETRE **SOUSTRAIT**, pas seulement mesure.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_le_slippage_spot_est_SOUSTRAIT_de_l_edge_publie() -> None:
    """*Un cout qu'on mesure mais qu'on ne soustrait pas est un cout qu'on CACHE.* (17e fois.)

    On compare deux carnets identiques sauf le slippage. L'edge net publie doit BAISSER.
    """
    profond = decider(_ctx())
    glissant = decider(_ctx(
        niveaux_spot_achat=[(1.0, 100.0), (1.01, 1_000_000.0)],     # ~1 % plus haut
        niveaux_spot_vente=[(0.9999, 100.0), (0.99, 1_000_000.0)],
    ))
    if not profond.autorise:
        pytest.skip("le carry n'est pas ouvrable ici (funding absent en CI) : rien a comparer")

    sp_p = (profond.preuve or {}).get("spot") or {}
    sp_g = (glissant.preuve or {}).get("spot") or {}
    assert sp_p.get("slippage_total_bps", 0.0) == pytest.approx(0.0, abs=1e-6)
    assert sp_g.get("slippage_total_bps", 0.0) > 0.0

    if glissant.autorise:
        assert glissant.edge_net_bps < profond.edge_net_bps, (
            "REGRESSION : le slippage spot a ete MESURE mais pas SOUSTRAIT de l'edge publie"
        )
    else:
        assert glissant.raison == REFUS_EDGE_NET_INSUFFISANT


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  4. LA PORTE SPOT NE S'APPLIQUE QU'AU CARRY. *Pas de fuite.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("strategie", ["COPY", "GRINDER", "SNIPER"])
def test_les_familles_directionnelles_ne_sont_PAS_refusees_pour_absence_de_spot(
    strategie: str,
) -> None:
    """Une strategie directionnelle n'a **pas** de jambe spot. Le refus doit venir d'ailleurs
    (zone morte, edge non mesure...), **jamais** de `REFUS_JAMBE_SPOT_IMPOSSIBLE`.
    """
    d = decider(_ctx(strategie=strategie,
                     niveaux_spot_achat=None, niveaux_spot_vente=None))
    assert d.autorise is False           # elles sont refusees -- mais pour LEUR raison
    assert d.raison != REFUS_JAMBE_SPOT_IMPOSSIBLE


def test_la_SORTIE_du_perp_est_chiffree_aussi() -> None:
    """🔴 *On ouvre une position ; il faudra bien la REFERMER.*

    `jambe_executable` ne chiffrait que l'**ENTREE**. La porte annoncait **+8,31 %** la ou la
    mesure complete (4 jambes) disait **+6,6 %**. ***Deux nombres pour la meme chose.***

    ***Une sortie qu'on ne chiffre pas est une sortie qu'on suppose gratuite --
    et rien n'est gratuit dans un carnet.***
    """
    d = decider(_ctx())
    sp = (d.preuve or {}).get("spot") or {}
    assert isinstance(sp, dict) and "sortie_perp" in sp, (
        "REGRESSION : la SORTIE du perp n'est plus chiffree -> la porte est OPTIMISTE"
    )


def test_un_perp_ou_l_on_peut_ENTRER_mais_pas_SORTIR_est_REFUSE() -> None:
    """*Une position qu'on ne peut pas refermer n'est pas une position : c'est un piege.*"""
    d = decider(_ctx(
        niveaux_vente=_PERP_BIDS,             # on peut ENTRER (vendre) : carnet profond
        niveaux_achat=[(1.0, 10.0)],          # 10 $ pour RACHETER 500 $ : on est COINCE
    ))
    assert d.autorise is False


def test_invariant_la_porte_spot_est_bien_CONDITIONNEE_au_carry() -> None:
    """🔒 Si quelqu'un supprime la condition, la porte devient morte partout ou vivante partout.
    **Les deux sont des bugs.**
    """
    import inspect

    from hl_observer.decision_engine import noyau_unique

    src = inspect.getsource(noyau_unique.decider)
    assert "marcher_dans_le_carnet(" in src, "la jambe spot a disparu de la porte"
    assert "REFUS_JAMBE_SPOT_IMPOSSIBLE" in src
    assert "niveaux_spot_achat" in src and "niveaux_spot_vente" in src
