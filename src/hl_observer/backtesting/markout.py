"""MARKOUT — ce que coûte un remplissage APRÈS le fill. La moitié qui manquait.

CE QUE CE MODULE CORRIGE
------------------------
Le 14/11 au matin, `maker_fill_probe` a mesuré le taux de remplissage (48,2 %) et le gain de
spread (0,0421 USD). **C'était la moitié FAVORABLE de l'équation.** La décomposition complète d'un
remplissage passif est :

    net(τ) = capture + adverse(τ) − frais
    capture    = ε · (m₀ − p) / m₀      [demi-spread encaissé, TOUJOURS ≥ 0, fixé au fill]
    adverse(τ) = ε · (m_τ − m₀) / m₀    [dérive du mid après le fill, ≤ 0 en moyenne]

avec ε = +1 pour un achat passif, −1 pour une vente passive.

**La littérature mesure que, sur Hyperliquid, la seconde moitié est PLUS GROSSE que la première.**
Daru Finance, 9 983 jours-coin et 125,8 M de remplissages simulés, avec la MÊME hypothèse de file
que la nôtre (« queues behind all visible size ») : capture **+0,56 bp**, dérive à 10 s
**−1,02 bp**, net **−0,46 bp AVANT frais**, intervalle à 95 % (groupé par mois ET par coin)
excluant zéro. Conclure « le maker est viable » à partir du seul taux de remplissage serait donc
une erreur, et c'est exactement l'erreur que ce module empêche.

CE QUI CHANGE LE SIGNE : LA POSITION DANS LA FILE
-------------------------------------------------
Albers, Cucuringu, Howison & Shestopaloff mesurent sur le perp BTC d'Hyperliquid, à 5 s :
remplissage maker moyen **−0,48 bp**, mais ceux qui gagnent la **PREMIÈRE PLACE** de la file
**+0,32 bp** — un écart d'environ **0,8 bp**. Ce n'est pas la prédiction qui sépare le gagnant du
perdant, c'est la place dans la file. Toute conclusion maker doit donc dire À QUELLE PLACE elle
vaut. `maker_fill_probe` suppose la DERNIÈRE place : c'est le pire cas, et c'est volontaire.

LES PIÈGES, TOUS REFUSÉS EXPLICITEMENT
---------------------------------------
* **jamais de mid inventé** : si la fenêtre de marché ne couvre pas `fill + τ`, l'horizon est
  `TRONQUE`, pas zéro. Prolonger par le dernier prix connu produirait silencieusement un markout
  de 0 et cacherait l'absence de données ;
* **jointure « as-of », jamais « au plus proche »** : on prend le dernier mid À OU AVANT la cible.
  Prendre le plus proche peut résoudre APRÈS la cible et allonger l'horizon sans le dire ;
* **aucun regard vers le futur** : un fill dont le mid de référence n'existe pas encore est écarté,
  jamais recalé sur un prix postérieur ;
* **péremption bornée** : un mid traîné à travers un trou de flux est aussi faux qu'un mid inventé,
  il échoue seulement en silence. Le seuil n'a PAS de valeur par défaut universelle — ce module
  refuse d'en deviner une ;
* **fills PASSIFS uniquement** : un fill agressif paie le spread à l'entrée, son « markout »
  mélangerait coût du spread et sélection adverse ;
* **« rien mesuré » n'est JAMAIS « sain »** : sans horizon exploitable, le verdict est
  `NON_MESURABLE`, et surtout pas « flux non toxique » ;
* **la moyenne seule ment** : une queue de distribution de quelques fills très mal sélectionnés
  cache une médiane saine. On publie toujours médiane et quartiles.

PAPER / lecture seule.
"""
from __future__ import annotations

import bisect
import math
from typing import Any, Iterable, Mapping, Sequence

ACHAT, VENTE = 1, -1

MESURE = "MESURE"
NON_MESURABLE = "NON_MESURABLE"

TRONQUE = "TRONQUE"          # la fenêtre de marché ne couvre pas fill + horizon
PERIME = "MID_PERIME"        # le mid prévalant est plus vieux que la borne admise
SANS_REFERENCE = "SANS_MID_DE_REFERENCE"   # pas de mid à ou avant le fill


def _fini(valeur: Any) -> float | None:
    try:
        sortie = float(valeur)
    except (TypeError, ValueError):
        return None
    return sortie if math.isfinite(sortie) else None


def mid_prevalant(instants: Sequence[int], mids: Sequence[float], cible: int,
                  *, peremption_ms: int | None) -> tuple[float | None, str | None]:
    """Dernier mid À OU AVANT `cible` — jointure « as-of », jamais « au plus proche ».

    Prendre le plus proche peut resoudre APRES la cible : avec un trou de 1,9 s dans la serie,
    un « markout a 100 ms » devient un markout a 1,9 s, et le diagnostic qu'on cherche a faire
    s'effondre sans prevenir.
    """
    if not instants:
        return None, SANS_REFERENCE
    position = bisect.bisect_right(instants, int(cible)) - 1
    if position < 0:
        return None, SANS_REFERENCE
    age = int(cible) - int(instants[position])
    if peremption_ms is not None and age > int(peremption_ms):
        return None, PERIME
    return _fini(mids[position]), None


def markout_d_un_fill(*, prix_fill: float, cote: int, instant_ms: int,
                      instants: Sequence[int], mids: Sequence[float],
                      horizons_ms: Sequence[int],
                      peremption_ms: int | None,
                      instant_ordre_ms: int | None = None) -> dict[str, Any]:
    """Décomposition complète d'un remplissage passif : capture, dérive, net par horizon.

    Renvoie `None` pour un horizon non mesurable — **jamais 0.0**, qui se confondrait avec
    « aucune dérive » et transformerait un trou de données en bonne nouvelle.

    `instant_ordre_ms` CORRIGE UNE MAUVAISE ATTRIBUTION. Sans lui, `m₀` est pris à l'instant du
    REMPLISSAGE, et la capture mesurée vaut alors `ε(m_fill − p)/m_fill`. Or un ordre passif n'est
    rempli que lorsque le marché vient à son prix : au moment du fill, le mid a déjà rejoint `p`,
    et dans un marché qui dérive il l'a dépassé. La « capture » sort alors **négative**, ce qui est
    impossible par construction — on place toujours sous le mid à l'achat. C'est exactement ce
    qu'a produit la mesure du 14/11 : **capture −6,01 bp**.

    Avec l'instant de l'ordre, la décomposition devient honnête et à trois termes :

        capture  = ε(m_ordre − p)/m_ordre     [le demi-spread VERROUILLE au placement, ≥ 0]
        attente  = ε(m_fill − m_ordre)/m_ordre [ce que la derive a coute PENDANT l'attente]
        adverse  = ε(m_τ − m_fill)/m_ordre     [la selection adverse APRES le fill]

    **Le net ne change pas** : `net = ε(m_τ − p)/m₀`, où le choix de `m₀` s'annule au premier
    ordre. Seule l'attribution change — mais une capture négative rend le diagnostic illisible.
    """
    if cote not in (ACHAT, VENTE):
        return {"verdict": NON_MESURABLE, "motif": "COTE_INCONNU"}
    prix = _fini(prix_fill)
    if prix is None or prix <= 0:
        return {"verdict": NON_MESURABLE, "motif": "PRIX_INVALIDE"}

    m0, motif = mid_prevalant(instants, mids, int(instant_ms), peremption_ms=peremption_ms)
    if m0 is None or m0 <= 0:
        # Pas de reference AVANT le fill : le recaler sur un prix posterieur serait un lookahead.
        return {"verdict": NON_MESURABLE, "motif": motif or SANS_REFERENCE}

    # Reference de CAPTURE : l'instant de l'ORDRE quand on le connait, sinon celui du fill.
    reference = m0
    attente_bps = None
    if instant_ordre_ms is not None:
        m_ordre, _ = mid_prevalant(instants, mids, int(instant_ordre_ms),
                                   peremption_ms=peremption_ms)
        if m_ordre is not None and m_ordre > 0:
            reference = m_ordre
            attente_bps = cote * (m0 - m_ordre) / m_ordre * 10_000.0
    capture_bps = cote * (reference - prix) / reference * 10_000.0
    dernier_instant = instants[-1]
    par_horizon: dict[int, Any] = {}
    for horizon in horizons_ms:
        cible = int(instant_ms) + int(horizon)
        if cible > dernier_instant:
            par_horizon[int(horizon)] = {"motif": TRONQUE, "adverse_bps": None,
                                         "net_bps": None}
            continue
        m_tau, motif_h = mid_prevalant(instants, mids, cible, peremption_ms=peremption_ms)
        if m_tau is None:
            par_horizon[int(horizon)] = {"motif": motif_h or PERIME, "adverse_bps": None,
                                         "net_bps": None}
            continue
        adverse_bps = cote * (m_tau - m0) / reference * 10_000.0
        # Le NET reste `eps(m_tau - p)/reference` : la decomposition se recompose exactement,
        # avec le terme d'attente quand il est connu.
        net_bps = capture_bps + adverse_bps + (attente_bps or 0.0)
        par_horizon[int(horizon)] = {"motif": None, "adverse_bps": adverse_bps,
                                     "net_bps": net_bps}
    return {"verdict": MESURE, "capture_bps": capture_bps, "mid_reference": reference,
            "mid_au_fill": m0, "attente_bps": attente_bps, "par_horizon": par_horizon}


def _quantile(valeurs: Sequence[float], q: float) -> float:
    ordonnees = sorted(valeurs)
    if not ordonnees:
        return float("nan")
    position = (len(ordonnees) - 1) * q
    bas = int(math.floor(position))
    haut = int(math.ceil(position))
    if bas == haut:
        return ordonnees[bas]
    return ordonnees[bas] + (ordonnees[haut] - ordonnees[bas]) * (position - bas)


def agreger(resultats: Iterable[Mapping[str, Any]], *, horizons_ms: Sequence[int],
            frais_bps: float = 0.0) -> dict[str, Any]:
    """Courbe de markout par horizon, avec distribution — et un verdict qui refuse de mentir.

    `frais_bps` est explicite : un net « avant frais » positif peut devenir negatif une fois le
    frais paye, et l'oublier est la facon la plus simple de se raconter une histoire.
    """
    captures: list[float] = []
    nets: dict[int, list[float]] = {int(h): [] for h in horizons_ms}
    adverses: dict[int, list[float]] = {int(h): [] for h in horizons_ms}
    tronques: dict[int, int] = {int(h): 0 for h in horizons_ms}
    ecartes: dict[str, int] = {}

    for resultat in resultats:
        if not isinstance(resultat, Mapping):
            continue
        if resultat.get("verdict") != MESURE:
            motif = str(resultat.get("motif") or NON_MESURABLE)
            ecartes[motif] = ecartes.get(motif, 0) + 1
            continue
        capture = _fini(resultat.get("capture_bps"))
        if capture is not None:
            captures.append(capture)
        for horizon, details in (resultat.get("par_horizon") or {}).items():
            cle = int(horizon)
            if cle not in nets:
                continue
            net = _fini(details.get("net_bps")) if isinstance(details, Mapping) else None
            adverse = _fini(details.get("adverse_bps")) if isinstance(details, Mapping) else None
            if net is None or adverse is None:
                tronques[cle] += 1
                continue
            nets[cle].append(net - float(frais_bps))
            adverses[cle].append(adverse)

    par_horizon: dict[int, Any] = {}
    exploitables: list[int] = []
    for horizon in sorted(nets):
        valeurs = nets[horizon]
        if not valeurs:
            par_horizon[horizon] = {"n": 0, "verdict": NON_MESURABLE,
                                    "tronques": tronques[horizon]}
            continue
        exploitables.append(horizon)
        par_horizon[horizon] = {
            "n": len(valeurs),
            "tronques": tronques[horizon],
            "net_moyen_bps": sum(valeurs) / len(valeurs),
            "net_median_bps": _quantile(valeurs, 0.5),
            "net_p25_bps": _quantile(valeurs, 0.25),
            "net_p75_bps": _quantile(valeurs, 0.75),
            "adverse_moyen_bps": sum(adverses[horizon]) / len(adverses[horizon]),
            "verdict": MESURE,
        }

    if not exploitables:
        return {"verdict": NON_MESURABLE, "motif": "AUCUN_HORIZON_EXPLOITABLE",
                "par_horizon": par_horizon, "ecartes": dict(sorted(ecartes.items())),
                "capture_moyenne_bps": (sum(captures) / len(captures)) if captures else None,
                "lecture": ("NON MESURABLE : aucun horizon exploitable. Ce n'est PAS « flux non "
                            "toxique » — c'est « rien n'a ete mesure ».")}

    negatifs = [h for h in exploitables if par_horizon[h]["net_moyen_bps"] < 0]
    part_negative = len(negatifs) / len(exploitables)
    return {
        "verdict": MESURE,
        "capture_moyenne_bps": (sum(captures) / len(captures)) if captures else None,
        "par_horizon": par_horizon,
        "horizons_exploitables": exploitables,
        "part_negative": part_negative,
        "toxique": part_negative > 0.5,
        "frais_bps": float(frais_bps),
        "ecartes": dict(sorted(ecartes.items())),
        "lecture": _lecture(par_horizon, exploitables, part_negative, captures, frais_bps),
    }


def _lecture(par_horizon, exploitables, part_negative, captures, frais_bps) -> str:
    capture = (sum(captures) / len(captures)) if captures else float("nan")
    morceaux = [f"capture moyenne {capture:+.2f} bp"]
    for horizon in exploitables:
        details = par_horizon[horizon]
        morceaux.append(f"{horizon} ms : net {details['net_moyen_bps']:+.2f} bp "
                        f"(derive {details['adverse_moyen_bps']:+.2f}, n={details['n']})")
    verdict = ("FLUX TOXIQUE : la derive reprend plus que le spread encaisse"
               if part_negative > 0.5 else
               "flux non toxique sur la majorite des horizons")
    return " | ".join(morceaux) + f" | frais {frais_bps:.2f} bp | {verdict}"


__all__ = ["ACHAT", "VENTE", "MESURE", "NON_MESURABLE", "TRONQUE", "PERIME", "SANS_REFERENCE",
           "mid_prevalant", "markout_d_un_fill", "agreger"]
