"""Fenetres de signal et predicats de rejouabilite : les outils PURS du chargeur.

Extraits de `copy_vault_book_loader.py` le 22/11/2026. Pourquoi : ce chargeur faisait
774 lignes et le plafond general du depot est de 800. Mes ajouts (filtre par fenetres de
signal, mode horloges) l'ont porte a 892. Epingler un plafond pour lui aurait ete le
relevement que j'avais refuse pour le labo deux heures plus tot -- on extrait.

CE QUE CE MODULE CONTIENT, et pourquoi c'est pur :

* `fenetres_normalisees` / `dans_les_fenetres` : borner la lecture des carnets aux instants
  qu'un signal regarde reellement. La marge n'elargit que vers le PASSE -- vers le futur elle
  ferait entrer des carnets posterieurs au signal, donc du lookahead.
* `predicats_de_rejouabilite` : les deux predicats du bilan (`non causal`, `safe causal`),
  evalues sur la ligne qui vient d'etre construite. Ils vivent ICI pour qu'il n'en existe
  qu'une version : le mode complet et le mode horloges appellent la MEME fonction, sur le
  MEME objet. Deux copies divergeraient un jour.
* `trier_horloges` : la dichotomie de `evaluable_signals` exige des instants ORDONNES.

Aucun acces disque, aucun reseau, aucune semantique economique.
"""
from __future__ import annotations

import array
import bisect
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

#: Marge par defaut autour de chaque signal. Le labo n apparie un carnet que s il precede le
#: signal de moins de `MAX_TARGET_LAG_MS` (30 s) : une fenetre plus large ne change donc AUCUN
#: appariement, elle ne fait que garder des lignes inutiles.
MARGE_FENETRE_SIGNAL_MS = 30_000


def fenetres_normalisees(
    fenetres: Iterable[tuple[int, int]], *, marge_ms: int = 0
) -> list[tuple[int, int]]:
    """Fenetres triees et FUSIONNEES, elargies de `marge_ms` vers le passe.

    Fusionner evite de tester vingt fois le meme intervalle ; trier permet la recherche
    dichotomique. La marge n elargit que vers le PASSE : vers le futur, elle ferait entrer
    des carnets posterieurs au signal, donc du lookahead.
    """
    brutes: list[tuple[int, int]] = []
    for fenetre in fenetres:
        debut, fin_f = int(fenetre[0]), int(fenetre[1])
        if fin_f < debut:
            raise ValueError(f"FENETRE_INVERSEE: {debut} > {fin_f}")
        brutes.append((max(0, debut - int(marge_ms)), fin_f))
    if not brutes:
        # Une liste VIDE ne veut pas dire << tout prendre >> ni << rien prendre >> : elle veut
        # dire que l appelant n a pas su construire ses fenetres. Rendre zero carnet ferait
        # croire a un corpus sans carnets -- un zero favorable, interdit par le contrat.
        raise ValueError("AUCUNE_FENETRE_DE_SIGNAL: liste vide, refus plutot que zero carnet")
    brutes.sort()
    fusionnees: list[tuple[int, int]] = [brutes[0]]
    for debut, fin_f in brutes[1:]:
        dernier_debut, dernier_fin = fusionnees[-1]
        if debut <= dernier_fin + 1:
            fusionnees[-1] = (dernier_debut, max(dernier_fin, fin_f))
        else:
            fusionnees.append((debut, fin_f))
    return fusionnees


def dans_les_fenetres(ts_ms: int, bornes: Sequence[tuple[int, int]]) -> bool:
    """`ts_ms` tombe-t-il dans une fenetre ? Bornes INCLUSIVES, comme `as_of_ms`."""
    index = bisect.bisect_right(bornes, (ts_ms, float("inf"))) - 1
    if index < 0:
        return False
    debut, fin_f = bornes[index]
    return debut <= ts_ms <= fin_f

def predicats_de_rejouabilite(row: Mapping[str, Any]) -> tuple[bool, bool]:
    """`(non_causal, safe_causal)` pour une ligne de carnet deja construite.

    Une seule version, appelee par les deux modes du chargeur : recopier ces predicats
    ailleurs creerait deux verites, et ce depot a deja paye ce defaut plusieurs fois.
    """
    non_causal = row.get("causal_observation") is not True
    safe_causal = (
        row.get("causal_observation") is True
        and row.get("source_quality_status") == "SAFE"
        and row.get("source_manifest_verified") is True
        and row.get("source_replay_compatible") is True
        and "bids5" in row
        and "asks5" in row
    )
    return non_causal, bool(safe_causal)


def trier_horloges(horloges: Mapping[str, array.array]) -> None:
    """Trie chaque serie EN PLACE : `evaluable_signals` fait une dichotomie."""
    for serie in horloges.values():
        ordonnee = sorted(serie)
        del serie[:]
        serie.extend(ordonnee)

def lignes_ou_horloges(
    by_coin: Mapping[str, list], horloges: Mapping[str, array.array],
    *, horloges_seulement: bool, non_causaux_vus: int,
) -> tuple[int, list, int, bool]:
    """`(valid, all_rows, non_causal_rows, aucune_ligne)` selon le mode du chargeur.

    Le mode complet recompte sur les lignes ; le mode horloges lit le compteur incremente
    pendant la lecture. Les deux doivent rendre les MEMES nombres -- un test d'equivalence
    (`tests/test_carnets_mode_horloges.py`) le verifie, sans quoi le mode econome
    declarerait rejouable un corpus que le mode complet refuse.
    """
    if horloges_seulement:
        trier_horloges(horloges)
        valide = sum(len(serie) for serie in horloges.values())
        return valide, [], non_causaux_vus, valide == 0
    for rows in by_coin.values():
        rows.sort(key=lambda row: row["ts_ms"])
    valide = sum(len(rows) for rows in by_coin.values())
    toutes = [row for rows in by_coin.values() for row in rows]
    non_causales = sum(predicats_de_rejouabilite(row)[0] for row in toutes)
    return valide, toutes, non_causales, not toutes

def bornes_ou_rien(
    fenetres: Iterable[tuple[int, int]] | None, *, marge_ms: int = MARGE_FENETRE_SIGNAL_MS
) -> list[tuple[int, int]] | None:
    """Les bornes normalisees, ou `None` quand l'appelant ne filtre pas.

    `None` et une liste VIDE ne veulent pas dire la meme chose : `None` = << je ne filtre
    pas >>, `[]` = << je n'ai pas su construire mes fenetres >> et `fenetres_normalisees`
    refuse alors, plutot que de rendre zero carnet.
    """
    if fenetres is None:
        return None
    return fenetres_normalisees(fenetres, marge_ms=marge_ms)


def ranger(
    coin: str, row: Mapping[str, Any], ts_ms: int,
    by_coin: dict[str, list], horloges: dict[str, array.array],
    *, horloges_seulement: bool,
) -> None:
    """Range la ligne, ou seulement son instant quand le contenu ne servira pas."""
    if horloges_seulement:
        horloges.setdefault(coin, array.array("q")).append(int(ts_ms))
    else:
        by_coin.setdefault(coin, []).append(dict(row) if not isinstance(row, dict) else row)
