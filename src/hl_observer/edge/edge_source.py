"""Q1 -- LA PORTE UNIQUE DE L'EDGE BRUT. Elle dit TOUJOURS d'ou vient le chiffre.

Avant : deux formules inventees produisaient l'edge brut de toute la chaine de decision.

    opportunities/fresh_opportunity.py:342
        14.0 + score*0.55 + wallets*9.0 + notional/25000 + tightness*10
    copy_wallet/wallet_mirror_runtime.py:144
        24.0 + score*24.0 + copyability*18.0

Onze constantes magiques. Aucune n'a jamais ete mesuree. Et comme `edge_net = edge_brut - couts`,
un brut invente rend le net invente -- et le refus « edge insuffisant » ne refusait rien de reel.

Ce module impose UNE porte, et un choix EXPLICITE :

    HYPERSMART_EDGE_SOURCE = table     (DEFAUT) l'edge vient de la table MESUREE.
                                       Pas de cellule -> pas de valeur -> NO_TRADE.
                           = formule   la vieille formule. Autorisee, mais CHAQUE decision est
                                       estampillee `fabrique=True` + raison EDGE_FABRIQUE_FORMULE.
                                       On peut mentir a la machine ; on ne se ment plus a soi-meme.

⚠️ CE QUE LE DEFAUT `table` PRODUIT, MESURE LE 2026-07-13 SUR 22 472 MARKOUTS REELS :
   le moteur de copie REFUSE quasiment tout. Ce n'est pas une panne. La table dit « OUI » sur
   18 signaux de test... et le prix fait -14,69 bps net. L'edge n'existe pas ; le refus est le
   comportement CORRECT. (3e confirmation independante, apres la preuve OOS du 11/07.)

Lecture seule. Aucun ordre, aucune cle, aucune signature.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from hl_observer.edge.measured_edge_table import (
    EDGE_TABLE_ABSENTE,
    Features,
    TableEdgeMesuree,
)

SOURCE_TABLE = "table"
SOURCE_FORMULE = "formule"

EDGE_FABRIQUE_FORMULE = "EDGE_FABRIQUE_FORMULE"
EDGE_SOURCE_INCONNUE = "EDGE_SOURCE_INCONNUE"

CHEMIN_TABLE_DEFAUT = Path("data") / "reports" / "table_edge_mesuree.json"

# #594 : un chemin EXPLICITE vers la table. Sert aux tests (qui pointent vers une TEST_FIXTURE
# au lieu de lire l'etat VIVANT de la production) et a un futur A/B de tables. En production le
# lanceur ne le pose pas : la table est celle du depot.
ENV_CHEMIN_TABLE = "HYPERSMART_EDGE_TABLE_PATH"


@dataclass(frozen=True, slots=True)
class EdgeBrut:
    """`valeur_bps is None` => REFUS. `fabrique=True` => le chiffre est une INVENTION assumee."""

    valeur_bps: float | None
    fabrique: bool
    raison: str
    detail: dict[str, object] = field(default_factory=dict)

    @property
    def utilisable(self) -> bool:
        return self.valeur_bps is not None

    def as_dict(self) -> dict[str, object]:
        return {
            "edge_brut_bps": self.valeur_bps,
            "fabrique": self.fabrique,
            "raison": self.raison,
            **self.detail,
        }


def source_configuree() -> str:
    """Deny-by-default : une valeur inconnue n'est PAS 'formule par securite'. C'est un refus."""
    v = str(os.environ.get("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE) or "").strip().lower()
    return v or SOURCE_TABLE


# ------------------------------------------------------------------ chargement (cache par mtime)

_CACHE: dict[str, tuple[float, TableEdgeMesuree | None]] = {}


def charger_table(chemin: Path | None = None, *, racine: Path | None = None) -> TableEdgeMesuree | None:
    """Charge la table mesuree. Rend None si absente -- et None veut dire REFUS, pas 'zero'."""
    # PRECEDENCE, et elle compte : un appelant EXPLICITE gagne toujours sur un defaut d'environnement.
    #   chemin= (le plus explicite)  >  racine=  >  $HYPERSMART_EDGE_TABLE_PATH  >  $HYPERSMART_ROOT
    # Sans cette regle, ma 1re version faisait gagner l'ENV sur un `racine=` explicite -- et deux
    # tests qui verifiaient « pas de table -> REFUS » trouvaient soudain la TEST_FIXTURE de conftest.
    # Un defaut qui ecrase une consigne explicite n'est plus un defaut : c'est un bug.
    if chemin is not None:
        p = chemin
    elif racine is not None:
        p = racine / CHEMIN_TABLE_DEFAUT
    else:
        _env = str(os.environ.get(ENV_CHEMIN_TABLE, "") or "").strip()
        p = (Path(_env) if _env
             else (Path(os.environ.get("HYPERSMART_ROOT", ".") or ".") / CHEMIN_TABLE_DEFAUT))
    cle = str(p)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        _CACHE.pop(cle, None)
        return None
    vu = _CACHE.get(cle)
    if vu is not None and vu[0] == mtime:
        return vu[1]
    try:
        t = TableEdgeMesuree.depuis_json(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        t = None
    _CACHE[cle] = (mtime, t)
    return t


def vider_le_cache() -> None:
    """Pour les tests. En production la table ne bouge pas pendant un run."""
    _CACHE.clear()


# ------------------------------------------------------------------ LA PORTE


def edge_brut(
    *,
    coin: str,
    direction: str,
    signal_age_ms: float | None,
    leader_score: float | None,
    consensus_wallets: float | None,
    signal_ms: float | None,
    strategie: str = "COPY",
    formule_de_secours: Callable[[], float] | None = None,
    table: TableEdgeMesuree | None = None,
    racine: Path | None = None,
) -> EdgeBrut:
    """L'UNIQUE source de l'edge brut. Elle refuse, ou elle dit d'ou vient le chiffre.

    `formule_de_secours` n'est JAMAIS appelee en mode `table`. Elle n'existe que pour le mode
    `formule`, ou son resultat est explicitement marque comme fabrique. Aucun repli silencieux.
    """
    src = source_configuree()

    if src == SOURCE_FORMULE:
        if formule_de_secours is None:
            return EdgeBrut(None, False, EDGE_SOURCE_INCONNUE,
                            {"source": src, "note": "mode formule mais aucune formule fournie"})
        try:
            v = float(formule_de_secours())
        except Exception:                                   # noqa: BLE001
            return EdgeBrut(None, False, EDGE_SOURCE_INCONNUE, {"source": src})
        # LA VALEUR EST UTILISABLE, MAIS ELLE EST MARQUEE. Personne ne pourra dire « on ne savait
        # pas ». La raison remonte dans le decision_context, les logs, le dashboard et l'audit.
        return EdgeBrut(v, True, EDGE_FABRIQUE_FORMULE, {"source": src})

    if src != SOURCE_TABLE:
        return EdgeBrut(None, False, EDGE_SOURCE_INCONNUE, {"source": src})

    t = table if table is not None else charger_table(racine=racine)
    if t is None:
        return EdgeBrut(None, False, EDGE_TABLE_ABSENTE, {"source": src})

    r = t.chercher(
        Features(
            strategie=strategie,
            coin=coin,
            direction=direction,
            signal_age_ms=signal_age_ms,
            leader_score=leader_score,
            consensus_wallets=consensus_wallets,
        ),
        signal_ms=signal_ms,
    )
    if not r.mesure or r.edge_brut_bps is None:
        return EdgeBrut(None, False, r.raison,
                        {"source": src, "cle": r.cle, **_zone_morte(strategie)})
    return EdgeBrut(
        r.edge_brut_bps, False, r.raison,
        {"source": src, "niveau": r.niveau, "n": r.n,
         "moyenne_bps": r.moyenne_bps, "cle": r.cle, **_zone_morte(strategie)},
    )


def _zone_morte(strategie: str) -> dict:
    """Q3 -- ESTAMPILLE LA ZONE MORTE SUR LE REFUS. C'est ce qui rend le verdict DURABLE.

    Sans ca, un refus dit seulement « pas de donnee pour ce bucket » -- et six mois plus tard,
    quelqu'un (peut-etre moi) conclura « il suffit de collecter plus ». Faux : le fill public
    d'un leader ne porte AUCUNE information, et c'est MESURE (Q3, 38 388 signaux, panel strict :
    le prix court CONTRE le trade de -7,75 bps AVANT le fill, puis ne fait plus rien apres).

    Le refus doit donc porter POURQUOI, pas seulement QUE.
    """
    try:
        from hl_observer.signals.signal_taxonomy import (
            DISCRETIONNAIRE_PUBLIC,
            est_une_zone_morte,
            verdict_du_signal,
        )
        # Les strategies de copie sont, par nature, du discretionnaire PUBLIC deja execute.
        fam = DISCRETIONNAIRE_PUBLIC if str(strategie or "").upper().startswith("COPY") else ""
        if fam and est_une_zone_morte(fam):
            _, raison = verdict_du_signal(fam)
            return {"famille_du_signal": fam, "zone_morte": True, "zone_morte_raison": raison}
        return {"famille_du_signal": fam or "INCONNUE", "zone_morte": False}
    except Exception:                                        # noqa: BLE001
        return {}


__all__ = [
    "CHEMIN_TABLE_DEFAUT",
    "ENV_CHEMIN_TABLE",
    "EDGE_FABRIQUE_FORMULE",
    "EDGE_SOURCE_INCONNUE",
    "EdgeBrut",
    "SOURCE_FORMULE",
    "SOURCE_TABLE",
    "charger_table",
    "edge_brut",
    "source_configuree",
    "vider_le_cache",
]
