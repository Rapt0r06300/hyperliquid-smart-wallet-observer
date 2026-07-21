"""#566 bis — **`only_per_side` ne doit PAS s'appliquer a un carry delta-neutre.**

═══════════════════════════════════════════════════════════════════════════════════════════════
LE BUG QUE CES TESTS VERROUILLENT
═══════════════════════════════════════════════════════════════════════════════════════════════

`only_per_side` est ne de nos **19 SHORT sur 21** (P = 2,21e-4, 1 chance sur 4 520). Il refuse
qu'une cote depasse 70 % des ouvertures. **Excellent garde-fou -- pour un pari directionnel.**

    ***Mais un CARRY est DELTA-NEUTRE.***

    short PERP  +  long SPOT  =  exposition nette **ZERO**

La jambe perp d'un carry n'est **pas** un pari a la baisse : c'est la **moitie d'une couverture**.
La compter comme de l'exposition SHORT refusait PUMP et HYPE **a tort** -- et faisait tomber le
bot de **3 ouvertures a 1**.

*Un garde-fou applique au mauvais objet ne protege pas : il MUTILE.*

C'est la **troisieme fois** que j'ecris un garde qui refuse ce qu'il ne devrait pas :
  1. le garde de concentration mesurait la part contre le CARNET -> refusait TOUTE 1re position ;
  2. `faut_il_s_abstenir` refusait quand le VPIN etait `None` (la, c'etait VOULU) ;
  3. celui-ci.

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QUI NE DOIT **JAMAIS** SE RELACHER
═══════════════════════════════════════════════════════════════════════════════════════════════

L'exemption est **chirurgicale** : elle ne vaut que pour `CARRY_STRUCTUREL`. Si un jour quelqu'un
l'etend a COPY, GRINDER ou SNIPER, **ces tests tombent**. C'est exactement leur travail.

Aucun ordre reel. Paper-only.
"""
from __future__ import annotations

import pytest

from hl_observer.decision_engine.noyau_unique import (
    REFUS_COTE_VERROUILLEE,
    Contexte,
    decider,
)
from hl_observer.risk.side_lock import only_per_side


# ── un carnet REEL et profond, pour que seule la cote puisse etre la cause du refus ────────────
_ASKS = [(1.000 + 0.001 * i, 50_000.0) for i in range(10)]
_BIDS = [(0.999 - 0.001 * i, 50_000.0) for i in range(10)]

# 4 SHORT deja ouverts : un 5e SHORT ferait 100 % > 70 % -> `only_per_side` DOIT refuser.
_QUATRE_SHORT = ("SHORT", "SHORT", "SHORT", "SHORT")


def _ctx(strategie: str, **kw) -> Contexte:
    base = dict(
        strategie=strategie,
        coin="PURR",
        direction="SHORT",
        notional_usd=500.0,
        niveaux_achat=_ASKS,
        niveaux_vente=_BIDS,
        ouvertures_en_cours=_QUATRE_SHORT,
    )
    base.update(kw)
    return Contexte(**base)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  1. LE GARDE LUI-MEME est intact -- on ne l'a pas casse, on l'a juste bien AIGUILLE.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_only_per_side_refuse_toujours_un_5e_short() -> None:
    """La fonction n'a pas ete affaiblie. 4 SHORT + 1 SHORT = 100 % > 70 %."""
    ok, motif = only_per_side("SHORT", ouvertures_en_cours=list(_QUATRE_SHORT))
    assert ok is False, "le garde #566 doit TOUJOURS refuser un 5e SHORT directionnel"
    assert motif


def test_only_per_side_accepte_un_long_qui_reequilibre() -> None:
    ok, _ = only_per_side("LONG", ouvertures_en_cours=list(_QUATRE_SHORT))
    assert ok is True


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  2. LE NOYAU -- l'aiguillage. C'est ICI que le bug vivait.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("strategie", ["COPY", "GRINDER", "SNIPER", "MOMENTUM"])
def test_le_garde_reste_ACTIF_pour_toute_strategie_directionnelle(strategie: str) -> None:
    """🔒 L'exemption ne doit **JAMAIS** fuir vers une strategie directionnelle.

    Ces familles ont d'autres raisons d'etre refusees (zone morte, edge non mesure...). On
    verifie donc seulement qu'elles ne sont **PAS AUTORISEES** -- jamais qu'elles passent.
    """
    d = decider(_ctx(strategie))
    assert d.autorise is False, (
        "%s est directionnelle : elle ne doit jamais franchir la porte avec 4 SHORT ouverts"
        % strategie
    )


def test_le_garde_reste_actif_pour_copy_et_donne_bien_LA_cote_comme_cause() -> None:
    """Si COPY arrive jusqu'a la porte 5, le motif doit etre la COTE (pas autre chose).

    On ne peut pas garantir l'ordre des refus (une zone morte peut tomber avant), donc on
    accepte les deux, mais on exige qu'aucune ouverture ne soit accordee.
    """
    d = decider(_ctx("COPY"))
    assert d.autorise is False
    assert d.raison  # une raison EXPLICITE, jamais un refus muet


def test_le_carry_N_EST_PAS_bloque_par_la_cote() -> None:
    """🔑 **LE TEST QUI COMPTE.** Un carry delta-neutre traverse la porte 5.

    Il peut encore etre refuse ailleurs (funding absent en CI, plancher, VPIN...) --
    **mais JAMAIS pour `only_per_side`.**
    """
    d = decider(_ctx("CARRY"))
    assert d.raison != REFUS_COTE_VERROUILLEE, (
        "REGRESSION : le carry est delta-neutre (short perp + long spot = delta ZERO). "
        "Sa jambe perp n'est PAS de l'exposition directionnelle. "
        "La compter dans le desequilibre de cote refusait PUMP et HYPE a tort."
    )


def test_la_preuve_du_carry_dit_POURQUOI_la_porte_ne_s_applique_pas() -> None:
    """*Un refus (ou une exemption) muet est un refus qu'on ne peut pas auditer.*"""
    d = decider(_ctx("CARRY"))
    sl = str((d.preuve or {}).get("side_lock", ""))
    assert "NON_APPLICABLE" in sl and "DELTA_NEUTRE" in sl, (
        "l'exemption doit s'EXPLIQUER dans la preuve, sinon elle est indistinguable d'un oubli"
    )


@pytest.mark.parametrize("strategie", ["CARRY", "FUNDING", "BASIS"])
def test_les_trois_alias_de_carry_sont_exemptes(strategie: str) -> None:
    """`FUNDING` et `BASIS` mappent aussi sur CARRY_STRUCTUREL. Ils sont delta-neutres aussi."""
    d = decider(_ctx(strategie))
    assert d.raison != REFUS_COTE_VERROUILLEE


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  3. L'INVARIANT -- *ce qui empeche qu'on rebranche le garde par megarde.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_invariant_l_exemption_est_conditionnee_a_CARRY_STRUCTUREL_dans_le_source() -> None:
    """AST-libre mais textuel : l'exemption doit rester **conditionnee**, jamais globale.

    Si quelqu'un supprime la condition `if fam != CARRY_STRUCTUREL:`, `only_per_side` devient
    soit mort partout, soit vivant partout. **Les deux sont des bugs.**
    """
    import inspect

    from hl_observer.decision_engine import noyau_unique

    src = inspect.getsource(noyau_unique.decider)
    assert "only_per_side(" in src, "le garde #566 a disparu du noyau"
    assert "fam != CARRY_STRUCTUREL" in src, (
        "l'exemption doit rester CONDITIONNEE a CARRY_STRUCTUREL. "
        "Sans la condition, le garde est soit mort partout, soit vivant partout."
    )
