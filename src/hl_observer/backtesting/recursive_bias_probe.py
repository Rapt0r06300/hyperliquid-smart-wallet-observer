"""H-160 / GH-02 — LE BIAIS RECURSIF : nos features changent-elles selon la QUANTITE d'historique ?

LA QUESTION, POSEE PROPREMENT
-----------------------------
En **backtest**, on donne a une feature *toute* l'histoire disponible. En **live**, le bot ne garde
qu'un **buffer borne** (les N derniers points). Si la valeur de la feature **au meme instant t**
differe selon la quantite d'historique qui la precede, alors :

    le backtest et le live ne calculent PAS la meme chose.

Et ce n'est pas une subtilite : c'est la reponse la plus banale a « pourquoi mon backtest ne
ressemble pas a mon live » (H-177). Freqtrade en a fait une commande a part entiere
(`recursive-analysis`). Nous, on avait le **comparateur** (`backtesting/recursive_analysis.py`) --
mais **personne ne le nourrissait**. Il etait a 0,00 % de couverture (#599). Ce module est le
chainon manquant : il **fabrique les deux series** et les lui donne.

CE QU'ON COMPARE, EXACTEMENT
----------------------------
Pour chaque instant `t` d'une fenetre d'observation :

    BACKTEST : f(serie[0 : t+1])                      <- toute l'histoire
    LIVE     : f(serie[t+1-H : t+1])                  <- un buffer borne de H points

Une feature **bornee** (`r[-n:]`, fenetre glissante) rend exactement la meme valeur : `delta = 0`.
Une feature **recursive** (EMA amorcee sur `values[0]`, lissage de Wilder du RSI) rend une valeur
**differente** -- et l'ecart est ce qu'on mesure.

⚠️ CE MODULE NE JUGE PAS, IL MESURE. Un ecart non nul n'est pas forcement fatal : il faut le
comparer a ce que la feature **decide** (un seuil a 5 bps se moque d'un ecart de 0,001 bps). C'est
le role du rapport, pas du code.

Lecture seule, pur, deterministe. Aucun ordre, aucun reseau.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from hl_observer.backtesting.recursive_analysis import (
    RecursiveFeatureStability,
    recursive_feature_stability,
)

# Le buffer que le LIVE garde reellement en memoire. Volontairement modeste : c'est l'ordre de
# grandeur d'un deque de marks (cf. MidVolEstimator, maxlen=720).
HISTORIQUE_LIVE_PAR_DEFAUT = 200


@dataclass(frozen=True, slots=True)
class SondeBiaisRecursif:
    """Le resultat d'une sonde, avec de quoi le juger -- pas seulement un booleen."""

    feature: str
    stable: bool
    ecart_max: float
    ecart_moyen: float
    n_points: int
    historique_live: int
    raison: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "feature": self.feature,
            "stable": self.stable,
            "ecart_max": self.ecart_max,
            "ecart_moyen": self.ecart_moyen,
            "n_points": self.n_points,
            "historique_live": self.historique_live,
            "raison": self.raison,
        }


def _valeur(f: Callable[[list[float]], float | None], morceau: list[float]) -> float | None:
    try:
        v = f(morceau)
    except Exception:                                   # noqa: BLE001 — une feature qui plante n'est pas « stable »
        return None
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def series_backtest_et_live(
    f: Callable[[list[float]], float | None],
    serie: Sequence[float],
    *,
    historique_live: int = HISTORIQUE_LIVE_PAR_DEFAUT,
    debut: int | None = None,
) -> tuple[list[float], list[float]]:
    """Les DEUX series, calculees aux MEMES instants. C'est tout le sujet.

    `debut` : le premier instant observe. Par defaut on commence apres `historique_live` points,
    pour que le LIVE ait deja son buffer PLEIN -- sinon on mesurerait un simple manque de donnees,
    pas un biais recursif. *Un test qui mesure autre chose que ce qu'il croit ne prouve rien.*
    """
    xs = [float(v) for v in serie]
    n = len(xs)
    h = max(1, int(historique_live))
    d = int(debut) if debut is not None else h
    if d >= n:
        return [], []

    complet: list[float] = []
    borne: list[float] = []
    for t in range(d, n):
        v_bt = _valeur(f, xs[: t + 1])                  # BACKTEST : toute l'histoire
        v_live = _valeur(f, xs[max(0, t + 1 - h) : t + 1])   # LIVE : buffer borne
        if v_bt is None or v_live is None:
            continue                                    # une des deux n'a pas assez de donnees
        complet.append(v_bt)
        borne.append(v_live)
    return complet, borne


def sonder(
    nom: str,
    f: Callable[[list[float]], float | None],
    serie: Sequence[float],
    *,
    historique_live: int = HISTORIQUE_LIVE_PAR_DEFAUT,
    tolerance: float = 1e-9,
) -> SondeBiaisRecursif:
    """Sonde une feature. Rend l'ECART, pas seulement un verdict -- l'ecart est l'information."""
    complet, borne = series_backtest_et_live(f, serie, historique_live=historique_live)
    if not complet:
        return SondeBiaisRecursif(nom, False, 0.0, 0.0, 0, int(historique_live), "SERIE_TROP_COURTE")

    # C'est ICI que le comparateur mort de #599 reprend du service.
    verdict: RecursiveFeatureStability = recursive_feature_stability(
        feature=nom,
        full_series=complet,
        incremental_series=borne,
        tolerance=tolerance,
    )
    ecarts = [abs(a - b) for a, b in zip(complet, borne)]
    moyen = sum(ecarts) / len(ecarts)
    return SondeBiaisRecursif(
        feature=nom,
        stable=bool(verdict.stable),
        ecart_max=float(verdict.max_abs_delta),
        ecart_moyen=round(moyen, 12),
        n_points=len(complet),
        historique_live=int(historique_live),
        raison=verdict.reason,
    )


__all__ = [
    "HISTORIQUE_LIVE_PAR_DEFAUT",
    "SondeBiaisRecursif",
    "series_backtest_et_live",
    "sonder",
]
