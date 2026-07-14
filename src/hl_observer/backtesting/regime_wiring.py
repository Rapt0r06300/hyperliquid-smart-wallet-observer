"""#595 — BRANCHER le label de regime dans la recherche de scenarios.

CE QUE CE MODULE FERME
----------------------
`validation_gates.regime_robustness_gate` cherchait un champ `regime` que **personne n'ecrivait**.
Il retombait donc TOUJOURS sur des tranches de temps -- en s'appelant « regime_robustness »
(cf. #127). Depuis #127 il le DECLARE (`mode: tranches_temporelles_FAUTE_DE_LABEL`), mais un aveu
n'est pas une solution.

Ici on lui donne enfin ce qu'il reclame : un **regime par trade**, etiquete sans lire le futur.

LES TROIS REGLES QUI RENDENT CE LABEL HONNETE
---------------------------------------------
1. **CAUSAL** : la variance a l'instant `t` n'utilise QUE les prix < `t`
   (`garch11_variance_causale` -- la version historique lisait le futur DEUX fois, cf. #127).
2. **SEUIL DU TRAIN SEUL** : le seuil HAUTE/BASSE vol se calcule sur la periode d'entrainement.
   Le calculer sur tout l'echantillon serait un lookahead plus discret, mais tout aussi reel :
   le seuil connaitrait le test.
3. **`INCONNU` PLUTOT QU'INVENTE** : sans historique suffisant, on ne devine pas. Un trade
   `INCONNU` forme sa propre tranche -- il ne va pas gonfler artificiellement une des deux autres.

⚠️ PERFORMANCE — LA REGLE QUI REND TOUT CECI GRATUIT
----------------------------------------------------
On n'etiquette QUE les **~40 finalistes** sur le jeu de **TEST**. **JAMAIS** dans `_score_all`,
la boucle qui balaie les 150 M de scenarios. Les series causales sont calculees **une seule fois
par coin** (`PreparationRegime`), puis partagees par tous les finalistes.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field

from hl_observer.backtesting.regime_detection import garch11_variance_causale
from hl_observer.backtesting.regime_label import (
    BASSE_VOL,
    HAUTE_VOL,
    INCONNU,
    WARMUP_DEFAUT,
    SeuilRegime,
)

#: Il faut au moins ca de variances dans le TRAIN pour qu'un seuil veuille dire quelque chose.
MIN_POINTS_TRAIN = 10


@dataclass(frozen=True, slots=True)
class SerieCausale:
    """Pour un coin : a chaque instant, la variance CONNUE a cet instant (jamais apres)."""

    ts: tuple[float, ...] = ()
    var: tuple[float, ...] = ()

    def variance_connue_a(self, t: float) -> float | None:
        """La derniere variance disponible AVANT OU A l'instant `t`. `None` si on ne sait pas.

        `bisect_right` puis `-1` : on prend le dernier point d'indice `i` tel que `ts[i] <= t`.
        C'est LA ligne ou un lookahead se glisserait si on ecrivait `bisect_left` par distraction.
        """
        if not self.ts:
            return None
        i = bisect_right(self.ts, float(t)) - 1
        return self.var[i] if i >= 0 else None


@dataclass(frozen=True, slots=True)
class PreparationRegime:
    """Series causales + seuils, calcules UNE fois, partages par tous les finalistes."""

    series: dict[str, SerieCausale] = field(default_factory=dict)
    seuils: dict[str, SeuilRegime] = field(default_factory=dict)
    fin_du_train_ts: float = 0.0

    @property
    def coins_sans_seuil(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.series) - set(self.seuils)))


def serie_causale(path, *, warmup: int = WARMUP_DEFAUT) -> SerieCausale:
    """`path` = [(ts, mid)] trie. Rend, pour chaque instant, la variance CONNUE a cet instant.

    Detail qui decide de tout : `rendements[i]` est le rendement de `ts[i]` a `ts[i+1]`, et
    `garch11_variance_causale` emet `out[i]` AVANT d'apprendre de `rendements[i]`. Donc `out[i]`
    n'utilise que `rendements[:i]` -- l'information disponible **a l'instant `ts[i]`**.
    On apparie donc `(ts[i], out[i])`, et rien d'autre.
    """
    pts = sorted((float(t), float(m)) for t, m in (path or ()) if float(m) > 0)
    if len(pts) < 3:
        return SerieCausale()

    ts = [t for t, _ in pts]
    mids = [m for _, m in pts]
    rendements = [(mids[i] / mids[i - 1]) - 1.0 for i in range(1, len(mids))]
    variances = garch11_variance_causale(rendements, warmup=warmup)

    couples = [(ts[i], v) for i, v in enumerate(variances) if v is not None]
    return SerieCausale(
        ts=tuple(t for t, _ in couples),
        var=tuple(v for _, v in couples),
    )


def _seuil_du_train(serie: SerieCausale, fin_du_train_ts: float) -> SeuilRegime | None:
    """Mediane des variances OBSERVEES PENDANT LE TRAIN. Rien d'autre ne rentre ici."""
    vals = sorted(v for t, v in zip(serie.ts, serie.var) if t <= fin_du_train_ts)
    if len(vals) < MIN_POINTS_TRAIN:
        return None                      # trop court -> pas de seuil -> INCONNU. On ne devine pas.
    n = len(vals)
    med = vals[n // 2] if n % 2 else 0.5 * (vals[n // 2 - 1] + vals[n // 2])
    return SeuilRegime(seuil=float(med), n_train=n)


def preparer(marks: dict, fin_du_train_ts: float, *, warmup: int = WARMUP_DEFAUT) -> PreparationRegime:
    """UNE fois par run. Les ~40 finalistes se partagent ensuite ce travail."""
    series = {coin: serie_causale(path, warmup=warmup) for coin, path in (marks or {}).items()}
    seuils = {}
    for coin, s in series.items():
        seuil = _seuil_du_train(s, float(fin_du_train_ts))
        if seuil is not None and seuil.fiable:
            seuils[coin] = seuil
    return PreparationRegime(series=series, seuils=seuils, fin_du_train_ts=float(fin_du_train_ts))


def regime_du_trade(prep: PreparationRegime, coin: str, ts: float) -> str:
    """HAUTE_VOL / BASSE_VOL / INCONNU — decide avec la SEULE information disponible a `ts`."""
    seuil = prep.seuils.get(coin)
    if seuil is None:
        return INCONNU                   # pas de seuil credible pour ce marche : on s'abstient
    v = prep.series[coin].variance_connue_a(ts)
    if v is None:
        return INCONNU                   # trade avant la fin du warmup : on ne sait pas encore
    return HAUTE_VOL if v > seuil.seuil else BASSE_VOL


def etiqueter_triplets(prep: PreparationRegime, triplets) -> list[dict]:
    """(coin, ts, pnl) -> [{coin, ts, net_pnl_usdc, regime}] — le format que le gate reclamait.

    `net_pnl_usdc` est la cle que `validation_gates._pnls` lit deja : **aucun autre gate ne change
    de comportement**. On ne fait qu'AJOUTER l'information qui manquait.
    """
    return [
        {
            "coin": coin,
            "ts": float(ts),
            "net_pnl_usdc": float(pnl),
            "regime": regime_du_trade(prep, coin, ts),
        }
        for coin, ts, pnl in triplets
    ]


def repartition(trades: list[dict]) -> dict[str, int]:
    """Combien de trades dans chaque regime. Un `INCONNU` massif est un AVEU, pas un detail."""
    out: dict[str, int] = {}
    for t in trades or ():
        r = str(t.get("regime") or INCONNU)
        out[r] = out.get(r, 0) + 1
    return dict(sorted(out.items()))


__all__ = [
    "MIN_POINTS_TRAIN",
    "PreparationRegime",
    "SerieCausale",
    "etiqueter_triplets",
    "preparer",
    "regime_du_trade",
    "repartition",
    "serie_causale",
]
