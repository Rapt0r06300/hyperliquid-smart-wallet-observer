"""IMPROVE-20 (#127) — ÉTIQUETER le régime d'un trade, sans jamais lire le futur.

POURQUOI CE MODULE EXISTE
-------------------------
`validation_gates.regime_robustness_gate` — le gate qui donne son sens au mot « robuste » dans la
recherche 150 M — cherche un champ `regime` sur chaque trade. **Personne ne l'écrivait jamais.**
Le gate retombait donc **en silence** sur des tranches de temps, et le « split par régime »
(IMPROVE-10, marqué *completed*) n'a jamais eu lieu.

C'est la 8e fois : *une capacité présente, un chaînon manquant, et personne qui se plaint.*

LA MINE QU'ON A DÉSAMORCÉE EN CHEMIN
------------------------------------
`garch11_variance` (la version historique) **lit le futur deux fois** : elle s'amorce sur la
variance de TOUTE la série, et elle publie `out[i]` APRÈS avoir vu `r[i]`. La brancher naïvement
aurait injecté du lookahead dans le gate anti-lookahead lui-même. On utilise donc ici
`garch11_variance_causale`.

LE SEUIL AUSSI PEUT MENTIR
--------------------------
Séparer « haute vol » et « basse vol » par la **médiane de tout l'échantillon** serait un lookahead
plus discret mais tout aussi réel : le seuil connaîtrait le test. Le seuil se calcule donc sur le
**TRAIN uniquement**, puis s'applique tel quel au test.

Aucune décision, aucun ordre : ce module ÉTIQUETTE. Quand il ne sait pas, il dit `INCONNU` —
il n'invente pas de label.
"""

from __future__ import annotations

from dataclasses import dataclass

from hl_observer.backtesting.regime_detection import garch11_variance_causale

HAUTE_VOL = "HAUTE_VOL"
BASSE_VOL = "BASSE_VOL"
INCONNU = "INCONNU"  # pas assez d'historique -> refus honnête, jamais un label fabriqué

WARMUP_DEFAUT = 20


@dataclass(frozen=True, slots=True)
class SeuilRegime:
    """Le seuil qui sépare les deux régimes, et d'où il vient.

    `n_train` est là pour qu'on ne puisse pas oublier sur quoi il a été calibré : un seuil sans
    provenance, c'est un chiffre qu'on finit par croire.
    """

    seuil: float
    n_train: int
    source: str = "median_variance_TRAIN"

    @property
    def fiable(self) -> bool:
        return self.n_train >= 10


def variances_causales(returns, *, warmup: int = WARMUP_DEFAUT) -> list:
    """Variance conditionnelle à chaque instant, calculée UNIQUEMENT sur le passé.

    Les `warmup` premières valent `None`. Un `None` est une information : « je ne sais pas encore ».
    """
    return garch11_variance_causale(returns, warmup=warmup)


def seuil_depuis_le_train(returns_train, *, warmup: int = WARMUP_DEFAUT) -> SeuilRegime | None:
    """Médiane des variances causales du TRAIN. Renvoie None si le train est trop court.

    🔴 Ne JAMAIS calculer ce seuil sur train+test : le seuil connaîtrait alors le futur, et le
    « split par régime » deviendrait un split par information privilégiée.
    """
    vs = [v for v in variances_causales(returns_train, warmup=warmup) if v is not None]
    if len(vs) < 10:
        return None
    vs.sort()
    n = len(vs)
    med = vs[n // 2] if n % 2 else 0.5 * (vs[n // 2 - 1] + vs[n // 2])
    return SeuilRegime(seuil=float(med), n_train=n)


def etiqueter(returns, seuil: SeuilRegime | None, *, warmup: int = WARMUP_DEFAUT) -> list[str]:
    """Un label par instant : HAUTE_VOL / BASSE_VOL / INCONNU.

    `etiqueter(...)[i]` ne dépend que de `returns[:i]` — c'est l'invariant que le test différentiel
    vérifie (modifier le futur ne doit changer AUCUN label passé).
    """
    if seuil is None or not seuil.fiable:
        return [INCONNU] * len(list(returns))
    out = []
    for v in variances_causales(returns, warmup=warmup):
        if v is None:
            out.append(INCONNU)
        else:
            out.append(HAUTE_VOL if v > seuil.seuil else BASSE_VOL)
    return out


def trades_etiquetes(trades: list[dict], labels: list[str]) -> list[dict]:
    """Pose le champ `regime` que `regime_robustness_gate` cherchait — et ne trouvait jamais.

    On ne modifie pas les trades en place : un trade est une observation, pas un brouillon.
    """
    if len(trades) != len(labels):
        raise ValueError(
            "trades (%d) et labels (%d) doivent être alignés 1-pour-1 : sinon on collerait "
            "le régime d'un trade sur un autre." % (len(trades), len(labels))
        )
    return [dict(t, regime=lab) for t, lab in zip(trades, labels)]


__all__ = [
    "HAUTE_VOL",
    "BASSE_VOL",
    "INCONNU",
    "SeuilRegime",
    "variances_causales",
    "seuil_depuis_le_train",
    "etiqueter",
    "trades_etiquetes",
]
