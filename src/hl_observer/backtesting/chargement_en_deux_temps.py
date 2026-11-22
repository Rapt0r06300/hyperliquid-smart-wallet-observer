"""Charger les carnets EN DEUX TEMPS : les instants d'abord, le contenu seulement s'il sert.

LE PROBLEME, mesure des deux cotes :

```
le split du labo exige >= 6 journees UTC distinctes DANS UNE SEULE tranche
le chargement COMPLET des carnets a atteint 24,2 Go de RSS sur 8 jours (22/11/2026),
   RAM libre tombee a 0,6 Go -> passe arretee ; ~28 Go pour 6 jours (18/11/2026)
```

Or la porte qui echoue ensuite (`_bounds`, via `evaluable_signals`) ne lit **qu'un `ts_ms`**
par carnet. Payer 24 Go pour apprendre qu'on va refuser est donc du gaspillage pur -- et c'est
ce qui faisait tomber la machine. Les memes instants en `array("q")` tiennent dans **0,084 Go**
(mesure : 11,3 M carnets, 270 coins, 26 s).

LA REGLE, en une phrase : on demande d'abord aux HORLOGES si la separation temporelle peut
exister ; on ne paye le contenu que si la reponse est oui.

CE QUI NE CHANGE PAS. Quand le split se forme, le chargement complet a lieu comme avant et le
rejeu ne voit aucune difference. Quand il ne se forme pas, le flux rend EXACTEMENT le meme
refus par le meme chemin (`TEMPORAL_SPLIT_INVALID_AFTER_PURGE` et son `split_diagnostic`) --
simplement sans avoir charge 24 Go pour y arriver.

POURQUOI LES DEPENDANCES SONT INJECTEES. `_bounds` vit dans `copy_vault_local_lab`, qui
appellerait ce module : les importer ici ferait un cycle. Elles arrivent donc en parametres,
ce qui a un second merite -- ce module se teste avec des doubles, sans lire 8 Go de rubans.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any


def octets_des_horloges(horloges: Mapping[str, Any]) -> int:
    """Combien pesent les horloges, mesure et non estime (8 o par instant)."""
    total = 0
    for serie in horloges.values():
        try:
            total += serie.buffer_info()[1] * serie.itemsize
        except AttributeError:          # une liste : on ne sait pas, on ne devine pas
            return -1
    return total


def charger_carnets_en_deux_temps(
    workspace: Any,
    metaorders: Sequence[Mapping[str, Any]],
    *,
    tranche: tuple[int, int] | None,
    seuil_jours: int,
    charger: Callable[..., tuple[Any, dict[str, Any]]],
    apparier: Callable[..., Mapping[str, Any]],
    bornes: Callable[..., Any],
    diagnostic: Callable[..., Mapping[str, Any]] | None = None,
    dire: Callable[[str], None] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Rend `(carnets, audit)` : des carnets COMPLETS si le split peut se former, sinon les
    horloges seules.

    L'audit porte toujours `phase_1_horloges` : `split_possible`, le poids mesure des horloges
    et si les carnets complets ont ete charges. Sans cette trace, on ne saurait pas, en lisant
    un rapport, si le rejeu a vu des prix ou seulement des instants.
    """
    coins = {str(row["coin"]) for row in metaorders}
    horloges, audit_horloges = charger(
        workspace, coins=coins,
        depuis_ms=tranche[0] if tranche else None,
        as_of_ms=tranche[1] if tranche else None,
        horloges_seulement=True,
    )
    # VERIFIER, PAS SUPPOSER. Un chargeur qui ignore le drapeau -- un double de test, une
    # version anterieure -- rend des carnets COMPLETS. Les passer comme horloges ferait
    # comparer un dict a un entier dans la dichotomie (TypeError mesuree sur 3 tests du
    # labo le 22/11/2026). On lit donc ce que l audit DIT du mode, et on s y adapte.
    en_horloges = bool((audit_horloges or {}).get("horloges_seulement"))
    if en_horloges:
        alignement = apparier(metaorders, horloges=horloges, min_signals_per_day=None)
    else:
        # Le premier element porte des lignes completes : il part en `books` (positionnel).
        alignement = apparier(metaorders, horloges, min_signals_per_day=None)
    split_possible = bornes(alignement["timestamps"], seuil_jours=seuil_jours) is not None
    poids = octets_des_horloges(horloges) if en_horloges else -1

    if split_possible:
        carnets, audit = charger(
            workspace, coins=coins,
            depuis_ms=tranche[0] if tranche else None,
            as_of_ms=tranche[1] if tranche else None,
        )
        audit = {**audit, "phase_1_horloges": {
            "split_possible": True,
            "octets_horloges": poids,
            "carnets_complets_charges": True,
            "mode_horloges_honore": en_horloges,
        }}
        return carnets, audit

    if dire is not None:
        dire("Separation temporelle impossible sur les horloges : les carnets COMPLETS ne sont"
             " pas charges (24,2 Go epargnes), le refus est rendu tel quel.")
    trace: dict[str, Any] = {
        "split_possible": False,
        "octets_horloges": poids,
        "carnets_complets_charges": False,
        "mode_horloges_honore": en_horloges,
    }
    if diagnostic is not None:
        trace["diagnostic"] = dict(
            diagnostic(alignement["timestamps"], seuil_jours=seuil_jours))
    return horloges, {**audit_horloges, "phase_1_horloges": trace}
