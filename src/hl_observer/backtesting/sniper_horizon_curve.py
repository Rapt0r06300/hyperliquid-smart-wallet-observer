"""LA COURBE EDGE / HORIZON DU SNIPER — 100 ms à 5 min (2026-07-11). Phase 7 du brief.

LA SEULE RAISON HONNÊTE D'ESPÉRER ENCORE QUELQUE CHOSE DU COPY-TRADING.

Ce qu'on a mesuré, et qui tient : sur 24 133 signaux réels, hors échantillon, **le copy-trading n'a
pas d'edge**. Après l'ordre d'une whale, le prix bouge de ~0 bps (bruit : 50-100). Même à coût zéro :
**−7,97 bps.**

MAIS — et c'est le point que je n'avais pas mesuré — **cette mesure portait sur des signaux dont
l'âge médian était de 57 secondes**, avec des horizons en secondes ou en minutes. Les horizons
**sub-seconde n'ont JAMAIS été testés**, pour une raison simple : *la donnée n'existait pas.*

Or c'est précisément là que l'edge d'un signal de copie devrait vivre, s'il vit quelque part.
Un fill de whale est une information publique : elle se consomme en millisecondes, pas en minutes.
Mesurer son effet à 60 s revient à chercher une empreinte de pas une heure après la marée.

Le firehose sub-seconde et l'enregistrement L2 changent ça. **Ce module mesure la courbe.**

CE QU'IL FAIT — et rien de plus :
    pour chaque horizon (100 ms, 250 ms, 500 ms, 1 s, 2 s, 5 s, 10 s, 30 s, 60 s, 5 min) :
    le mouvement de prix RÉEL après un fill de leader, dans le sens du leader, en bps.

CE QU'IL REFUSE DE FAIRE :
  * inventer un horizon que la donnée ne permet pas -> `SOURCE_RESOLUTION_INSUFFICIENT` ;
  * soustraire une moyenne calculée SUR LA PÉRIODE TESTÉE (c'est du lookahead -- je me suis déjà
    fait prendre : « +35 bps d'edge » qui n'existait pas) ;
  * rendre une moyenne sans son écart-type et sans le nombre d'observations. Un chiffre sans
    dispersion ni taille d'échantillon n'est pas une mesure, c'est une impression.

⚠️ Ce module NE PROMET AUCUN PnL. Il rend une courbe. Si elle est plate, on saura, et on cessera
d'y croire.

PUR, sans I/O réseau. Aucun ordre réel.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

# Les horizons du brief. Les 4 premiers n'ont JAMAIS ete mesures faute de donnee.
HORIZONS_MS: tuple[int, ...] = (100, 250, 500, 1_000, 2_000, 5_000, 10_000, 30_000, 60_000, 300_000)

RESOLUTION_INSUFFISANTE = "SOURCE_RESOLUTION_INSUFFICIENT"

# Sous ce nombre d'observations, une "mesure" n'est qu'un accident.
MIN_OBSERVATIONS = 200


@dataclass(frozen=True, slots=True)
class PointCourbe:
    horizon_ms: int
    n: int
    edge_median_bps: float | None
    edge_moyen_bps: float | None
    ecart_type_bps: float | None
    # Le juge de paix : un mouvement median de 5 bps avec un ecart-type de 80 est du BRUIT.
    ratio_signal_bruit: float | None
    statut: str          # MEASURED | SOURCE_RESOLUTION_INSUFFICIENT | SAMPLE_TOO_SMALL

    @property
    def exploitable(self) -> bool:
        """Un edge n'est exploitable que s'il est MESURÉ, significatif, et au-dessus du bruit."""
        return (
            self.statut == "MEASURED"
            and self.edge_median_bps is not None
            and self.ratio_signal_bruit is not None
            and self.ratio_signal_bruit >= 0.20      # sinon : indiscernable du hasard
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "horizon_ms": self.horizon_ms,
            "n": self.n,
            "edge_median_bps": self.edge_median_bps,
            "edge_moyen_bps": self.edge_moyen_bps,
            "ecart_type_bps": self.ecart_type_bps,
            "ratio_signal_bruit": self.ratio_signal_bruit,
            "statut": self.statut,
            "exploitable": self.exploitable,
        }


def _mediane(v: Sequence[float]) -> float | None:
    if not v:
        return None
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _ecart_type(v: Sequence[float]) -> float | None:
    n = len(v)
    if n < 2:
        return None
    moy = sum(v) / n
    return math.sqrt(sum((x - moy) ** 2 for x in v) / (n - 1))


def mouvement_apres(
    *,
    prix_signal: float,
    side: str,
    chemin_prix: Iterable[tuple[int, float]],
    horizon_ms: int,
    tolerance_ms: int = 0,
) -> float | None:
    """Mouvement RÉEL, en bps, `horizon_ms` après le signal, DANS LE SENS du leader.

    `chemin_prix` : (delta_ms depuis le signal, prix). Renvoie None si la donnée ne couvre pas
    l'horizon — **on ne l'extrapole pas.** Une courbe qui invente ses points ne mesure rien.
    """
    if prix_signal <= 0:
        return None
    cible = horizon_ms
    limite = cible + (tolerance_ms if tolerance_ms > 0 else max(1, cible // 10))

    meilleur: tuple[int, float] | None = None
    for dt, prix in chemin_prix:
        if dt < cible or dt > limite or prix <= 0:
            continue
        if meilleur is None or dt < meilleur[0]:
            meilleur = (dt, prix)
    if meilleur is None:
        return None                      # la source ne descend pas a cette resolution

    variation = (meilleur[1] - prix_signal) / prix_signal * 10_000.0
    return variation if str(side).upper() in {"LONG", "BUY"} else -variation


def construire_courbe(
    signaux: Iterable[Mapping[str, Any]],
    *,
    horizons_ms: Sequence[int] = HORIZONS_MS,
) -> dict[int, PointCourbe]:
    """La courbe. Chaque signal : {prix_signal, side, chemin_prix: [(delta_ms, prix), ...]}.

    **Aucun coût n'est retiré ici** : on mesure d'abord si un mouvement EXISTE. Les coûts (13 bps
    d'aller-retour) viendront ensuite trancher s'il est exploitable. Mélanger les deux empêcherait
    de savoir laquelle des deux choses manque.
    """
    par_horizon: dict[int, list[float]] = {h: [] for h in horizons_ms}

    for s in signaux:
        if not isinstance(s, Mapping):
            continue
        try:
            prix = float(s.get("prix_signal") or 0.0)
        except (TypeError, ValueError):
            continue
        side = str(s.get("side") or "")
        chemin = s.get("chemin_prix") or ()
        for h in horizons_ms:
            m = mouvement_apres(prix_signal=prix, side=side, chemin_prix=chemin, horizon_ms=h)
            if m is not None and math.isfinite(m):
                par_horizon[h].append(m)

    courbe: dict[int, PointCourbe] = {}
    for h in horizons_ms:
        vals = par_horizon[h]
        n = len(vals)
        if n == 0:
            courbe[h] = PointCourbe(h, 0, None, None, None, None, RESOLUTION_INSUFFISANTE)
            continue
        med = _mediane(vals)
        moy = sum(vals) / n
        sd = _ecart_type(vals)
        # signal / bruit : un mouvement median de 5 bps avec 80 bps d'ecart-type ne veut RIEN dire.
        #
        # BUG ATTRAPE PAR SON PROPRE TEST (2026-07-11) : quand l'ecart-type est NUL, le mouvement
        # est PARFAITEMENT regulier -- c'est le meilleur signal imaginable, pas du bruit. Le code
        # rendait `None` (= "non mesurable") et declarait donc un signal parfait INEXPLOITABLE.
        # On ne verra jamais une variance exactement nulle sur des vraies donnees, mais un module
        # qui confond "aucun bruit" et "que du bruit" a une faille de raisonnement -- pas un
        # simple cas limite.
        if med is None or sd is None:
            rsb = None                       # moins de 2 observations : rien a dire
        elif sd > 0:
            rsb = abs(med) / sd
        else:
            rsb = float("inf") if abs(med) > 0 else 0.0
        statut = "MEASURED" if n >= MIN_OBSERVATIONS else "SAMPLE_TOO_SMALL"
        courbe[h] = PointCourbe(
            horizon_ms=h, n=n,
            edge_median_bps=(round(med, 4) if med is not None else None),
            edge_moyen_bps=round(moy, 4),
            ecart_type_bps=(round(sd, 4) if sd is not None else None),
            ratio_signal_bruit=(
                rsb if (rsb is not None and not math.isfinite(rsb))
                else (round(rsb, 4) if rsb is not None else None)
            ),
            statut=statut,
        )
    return courbe


def verdict(courbe: Mapping[int, PointCourbe], *, cout_aller_retour_bps: float = 13.0) -> dict[str, Any]:
    """Le verdict HONNÊTE. Un edge n'existe que s'il est mesuré, hors du bruit, ET au-dessus des coûts."""
    exploitables = {h: p for h, p in courbe.items() if p.exploitable}
    rentables = {
        h: p for h, p in exploitables.items()
        if p.edge_median_bps is not None and p.edge_median_bps > cout_aller_retour_bps
    }

    if not any(p.statut == "MEASURED" for p in courbe.values()):
        conclusion = ("AUCUNE MESURE POSSIBLE — la source ne descend pas a ces horizons. "
                      "Ce n'est PAS une preuve d'absence d'edge : c'est une absence de donnee.")
    elif not exploitables:
        conclusion = ("AUCUN HORIZON NE SORT DU BRUIT — le mouvement apres un fill de leader est "
                      "indiscernable du hasard. Aucun reglage ne sauvera ca.")
    elif not rentables:
        meilleur = max(exploitables.values(), key=lambda p: p.edge_median_bps or 0.0)
        conclusion = (
            f"UN MOUVEMENT EXISTE ({meilleur.edge_median_bps} bps a {meilleur.horizon_ms} ms) "
            f"MAIS IL NE COUVRE PAS LES COUTS ({cout_aller_retour_bps} bps). Le signal est reel "
            f"et economiquement inutile -- c'est la pire des situations, car elle donne envie d'y croire."
        )
    else:
        meilleur = max(rentables.values(), key=lambda p: p.edge_median_bps or 0.0)
        conclusion = (
            f"UN HORIZON SURVIT AUX COUTS : {meilleur.edge_median_bps} bps a {meilleur.horizon_ms} ms "
            f"(n={meilleur.n}, signal/bruit={meilleur.ratio_signal_bruit}). "
            f"CELA NE PROMET AUCUN PnL : il reste a le valider HORS ECHANTILLON, et a verifier "
            f"qu'on peut reellement executer a cette vitesse."
        )

    return {
        "courbe": {h: p.as_dict() for h, p in sorted(courbe.items())},
        "horizons_exploitables": sorted(exploitables),
        "horizons_rentables_apres_couts": sorted(rentables),
        "cout_aller_retour_bps": cout_aller_retour_bps,
        "conclusion": conclusion,
        "paper_only": True,
        "real_execution": False,
    }


__all__ = [
    "HORIZONS_MS",
    "MIN_OBSERVATIONS",
    "RESOLUTION_INSUFFISANTE",
    "PointCourbe",
    "construire_courbe",
    "mouvement_apres",
    "verdict",
]
