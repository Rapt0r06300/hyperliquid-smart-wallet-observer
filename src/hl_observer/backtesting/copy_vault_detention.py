"""COMBIEN DE TEMPS LES LEADERS TIENNENT-ILS ? — mesuré, au lieu d'être choisi.

POURQUOI CE MODULE (17/11/2026). Tout le modèle de copie rapide repose sur un **horizon de
détention que NOUS choisissons** : le tunnel d'exécutabilité mesure une sortie à `entrée + 300 s`,
et `copy_vault_v5_lifecycle_train` explore une grille de `max_hold_ms`. Vérifié par recherche sur
tout le dépôt : **personne n'a jamais mesuré la durée que les leaders tiennent vraiment.**

Or la donnée est là. Mesure sur une seule journée du coffre (17/11, 618 264 fills) :

```
Close Long  152 219     Open Short  140 446     Short > Long  4 380
Close Short 146 040     Open Long   137 308     Long > Short  4 295
```

Les sorties sont donc explicitement étiquetées, avec `closedPnl`. Si les leaders tiennent des
heures, un horizon de 300 s ne mesure pas leur stratégie mais une autre, et l'amortissement des
9,0 bps de frais aller-retour change complètement d'échelle.

CE QUE CE MODULE GARANTIT :

* **appariement FIFO par (compte, coin)** : chaque ouverture est une tranche ; chaque clôture
  consomme les tranches les plus anciennes, en taille. Une réduction partielle ferme donc une
  partie de tranche, et le reste continue de courir ;
* **une ouverture non refermée dans la fenêtre est CENSURÉE** — jamais une durée nulle, jamais une
  clôture supposée. La part censurée est publiée : une médiane calculée sur les seules positions
  refermées est biaisée vers le court, et le dire fait partie de la mesure ;
* **horloge d'échange par défaut** (`ts_ms`) : on mesure le comportement du leader, pas notre
  latence d'observation. Pour une question de copiabilité, l'appelant demande `received_at_ms` ;
* **aucune direction devinée** : un `dir` inconnu est compté à part et n'entre dans aucun
  appariement.

PAPER / LECTURE SEULE : aucune décision, aucun ordre. C'est une statistique descriptive sur des
observations publiques.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

SCHEMA = "hypersmart.copy_vault_detention.v1"

#: Étiquettes `dir` d'OUVERTURE et de CLÔTURE, telles qu'observées au coffre. Le vocabulaire vient
#: de la mesure du 17/11 et non d'une supposition ; une étiquette inconnue est comptée, pas rangée.
OUVERTURES: dict[str, int] = {"open long": 1, "open short": -1}
CLOTURES: dict[str, int] = {"close long": 1, "close short": -1}
#: Un retournement ferme la position existante ET en ouvre une opposée : les deux à la fois.
RETOURNEMENTS: dict[str, int] = {"long > short": 1, "short > long": -1}


def _etiquette(valeur: Any) -> str:
    return " ".join(str(valeur or "").strip().casefold().split())


def _nombre(valeur: Any) -> float | None:
    if isinstance(valeur, bool) or valeur is None:
        return None
    try:
        x = float(valeur)
    except (TypeError, ValueError, OverflowError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def _entier(valeur: Any) -> int | None:
    if type(valeur) is not int or isinstance(valeur, bool):
        return None
    return valeur


def _percentiles(valeurs: Sequence[float], points: Sequence[float]) -> dict[str, float | None]:
    if not valeurs:
        return {f"p{int(p * 100)}": None for p in points}
    ordonnes = sorted(valeurs)
    sortie: dict[str, float | None] = {}
    for p in points:
        i = min(len(ordonnes) - 1, max(0, int(round(p * (len(ordonnes) - 1)))))
        sortie[f"p{int(p * 100)}"] = float(ordonnes[i])
    return sortie


def cle_d_identite(fill: Mapping[str, Any]) -> tuple:
    """L'identité d'UN fill d'échange, pour ne pas le compter deux fois.

    17/11/2026 — PIÈGE MESURÉ, ET MA PREMIÈRE MESURE Y ÉTAIT TOMBÉE. La famille `fills_forward`
    contient le même fill d'échange observé par PLUSIEURS sources : sur la journée du 17/11,
    618 264 lignes pour **579 363 fills distincts**, soit **6,3 % de doublons** entre `LIVE_POLL`,
    `LIVE_WS` et `LIVE_TWAP`. Sans déduplication, une ouverture vue deux fois remplit deux fois la
    file FIFO et déforme la distribution des durées.

    MAIS SURTOUT, LE PIÈGE : on ne peut PAS dédupliquer sur `hash`.

    * `stable_event_id` n'existe que sur les lignes `LIVE_WS` : **20 338 sur 618 264 (3,3 %)** ;
    * `hash` est le hash de TRANSACTION, pas du fill. Mesuré : **83 862 hashes portent plusieurs
      lignes**, et le hash sentinelle `0x0000…0000` en porte **40 915** — les sous-fills d'un TWAP.
      Dédupliquer dessus écraserait 40 915 fills distincts en un seul.

    La clé est donc `stable_event_id` quand il existe, sinon la clé NATURELLE d'échange
    `(compte, coin, horodatage, taille, prix, sens)`. La source n'y entre volontairement PAS :
    c'est précisément ce qu'on veut réunir.
    """
    identite = fill.get("stable_event_id")
    if isinstance(identite, str) and identite:
        return ("sid", identite)
    return ("naturelle", str(fill.get("vault") or "").lower(), str(fill.get("coin") or ""),
            fill.get("ts_ms"), fill.get("sz"), fill.get("px"), _etiquette(fill.get("dir")))


def apparier(fills: Iterable[Mapping[str, Any]], *, horloge: str = "ts_ms",
             dedupliquer: bool = True) -> dict[str, Any]:
    """Apparie les ouvertures et les clôtures des leaders, et rend les durées de détention.

    Rend les durées APPARIÉES (en ms, pondérables par la taille), les ouvertures CENSURÉES
    restées ouvertes en fin de fenêtre, et le détail par compte. Fonction pure.
    """
    tranches: dict[tuple[str, str, int], deque] = {}
    durees: list[float] = []
    durees_ponderees: list[tuple[float, float]] = []
    par_compte: dict[str, dict[str, Any]] = {}
    etiquettes_inconnues: dict[str, int] = {}
    lignes = 0
    sans_horloge = 0
    sans_taille = 0
    doublons_ignores = 0
    vus: set[tuple] = set()
    appariees = 0
    cloture_sans_ouverture = 0
    pnl_clos: list[float] = []

    def _compte(nom: str) -> dict[str, Any]:
        return par_compte.setdefault(nom, {"ouvertures": 0, "clotures": 0, "appariees": 0,
                                           "durees_ms": [], "censurees": 0})

    # On trie par horloge : un appariement FIFO n'a de sens que dans l'ordre du temps.
    rangees = []
    for fill in fills or ():
        lignes += 1
        if dedupliquer:
            cle = cle_d_identite(fill)
            if cle in vus:
                doublons_ignores += 1
                continue
            vus.add(cle)
        instant = _entier(fill.get(horloge))
        coin = fill.get("coin")
        vault = str(fill.get("vault") or "").lower()
        if instant is None or not isinstance(coin, str) or not coin or not vault:
            sans_horloge += 1
            continue
        taille = _nombre(fill.get("sz"))
        if taille is None or taille <= 0:
            sans_taille += 1
            continue
        rangees.append((instant, vault, str(coin), taille, _etiquette(fill.get("dir")),
                        _nombre(fill.get("closedPnl", fill.get("closed_pnl")))))
    rangees.sort(key=lambda r: r[0])

    for instant, vault, coin, taille, label, pnl in rangees:
        sens_ouverture = OUVERTURES.get(label)
        sens_cloture = CLOTURES.get(label)
        sens_retournement = RETOURNEMENTS.get(label)
        if sens_ouverture is None and sens_cloture is None and sens_retournement is None:
            etiquettes_inconnues[label or "(vide)"] = etiquettes_inconnues.get(label or "(vide)", 0) + 1
            continue
        bloc = _compte(vault)
        if sens_cloture is not None or sens_retournement is not None:
            # Un retournement ferme le sens EXISTANT, qui est celui d'où l'on part.
            sens_ferme = sens_cloture if sens_cloture is not None else sens_retournement
            file = tranches.get((vault, coin, sens_ferme))
            reste = taille
            bloc["clotures"] += 1
            if pnl is not None:
                pnl_clos.append(pnl)
            while reste > 1e-12 and file:
                ouvert_a, dispo = file[0]
                pris = min(reste, dispo)
                duree = float(instant - ouvert_a)
                if duree >= 0.0:
                    durees.append(duree)
                    durees_ponderees.append((duree, pris))
                    bloc["durees_ms"].append(duree)
                    appariees += 1
                    bloc["appariees"] += 1
                reste -= pris
                if dispo - pris <= 1e-12:
                    file.popleft()
                else:
                    file[0] = (ouvert_a, dispo - pris)
            if reste > 1e-12:
                # On ferme une position dont on n'a pas vu l'ouverture : la fenetre commence
                # apres. Ce n'est PAS une duree de zero, c'est une observation tronquee a gauche.
                cloture_sans_ouverture += 1
        if sens_ouverture is not None or sens_retournement is not None:
            sens_ouvre = sens_ouverture if sens_ouverture is not None else -sens_retournement
            tranches.setdefault((vault, coin, sens_ouvre), deque()).append((instant, taille))
            bloc["ouvertures"] += 1

    # Ce qui reste ouvert est CENSURE : on ne sait pas quand ca s'est ferme, et on ne l'invente pas.
    censurees = 0
    taille_censuree = 0.0
    for (vault, _coin, _sens), file in tranches.items():
        for _ouvert_a, dispo in file:
            censurees += 1
            taille_censuree += dispo
            _compte(vault)["censurees"] += 1

    poids_total = sum(p for _, p in durees_ponderees)
    mediane_ponderee: float | None = None
    if poids_total > 0:
        cumul = 0.0
        for duree, poids in sorted(durees_ponderees):
            cumul += poids
            if cumul >= poids_total / 2.0:
                mediane_ponderee = duree
                break

    for bloc in par_compte.values():
        d = bloc.pop("durees_ms")
        bloc["mediane_ms"] = _percentiles(d, (0.5,))["p50"]
        bloc["n_durees"] = len(d)

    return {
        "schema": SCHEMA,
        "horloge": str(horloge),
        "lignes_lues": lignes,
        "doublons_ignores": doublons_ignores,
        "deduplique": bool(dedupliquer),
        "lignes_sans_horloge_ou_identite": sans_horloge,
        "lignes_sans_taille": sans_taille,
        "etiquettes_inconnues": dict(sorted(etiquettes_inconnues.items(), key=lambda kv: -kv[1])),
        "appariees": appariees,
        "cloture_sans_ouverture_observee": cloture_sans_ouverture,
        "censurees": censurees,
        "taille_censuree": round(taille_censuree, 8),
        "part_censuree": (round(censurees / (censurees + appariees), 4)
                          if (censurees + appariees) else None),
        "detention_ms": _percentiles(durees, (0.1, 0.25, 0.5, 0.75, 0.9, 0.99)),
        "detention_mediane_ponderee_par_taille_ms": mediane_ponderee,
        "pnl_clos_observes": len(pnl_clos),
        "comptes": dict(sorted(par_compte.items())),
        "avertissement": ("une mediane calculee sur les seules positions REFERMEES est biaisee vers "
                          "le court : la part censuree doit etre lue avec elle"),
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = ["SCHEMA", "OUVERTURES", "CLOTURES", "RETOURNEMENTS", "cle_d_identite", "apparier"]
