"""[AUD-231/235/249/250/251/252/253/254/260] Rigueur de PROMOTION : reconstruction des chemins CPCV,
SPA (Hansen) et StepM (Romano-Wolf, Holm step-down) contre un benchmark, leave-one-out generalise
(session/wallet/venue), BORNE BASSE nette bootstrap OBLIGATOIRE, verdict POSITIVE_OR_NO_PROMOTION
integrant la derive et le protocole SANS EDGE. Deterministe (seed), stdlib pure, 0 reseau, 0 ordre reel."""
from __future__ import annotations

import random
import statistics
from itertools import combinations
from typing import Callable, Mapping, Sequence

PROMOTION_POSITIVE = "PROMOTION_POSITIVE"
NO_PROMOTION = "NO_PROMOTION"


def reconstruire_chemins_cpcv(n_groupes: int, k_test: int) -> dict:
    """Reconstruit les CHEMINS de backtest CPCV : chaque chemin = une combinaison de k blocs en TEST,
    le reste en TRAIN. n_chemins = C(n, k) ; chaque bloc apparait dans C(n-1, k-1) chemins."""
    if not (1 <= k_test < n_groupes):
        raise ValueError("1 <= k_test < n_groupes requis")
    chemins = []
    for combo in combinations(range(n_groupes), k_test):
        test = set(combo)
        chemins.append({"test": list(combo), "train": [g for g in range(n_groupes) if g not in test]})
    return {"n_chemins": len(chemins), "chemins": chemins}


def _t_stat(d: Sequence[float]) -> float:
    T = len(d)
    if T == 0:
        return 0.0
    m = sum(d) / T
    sd = statistics.pstdev(d) or 1e-9
    return m / (sd / (T ** 0.5))


def spa_test(reference: Sequence[float], candidats: Mapping[str, Sequence[float]], *,
             n_boot: int = 400, seed: int = 7) -> dict:
    """Test SPA (Superior Predictive Ability, Hansen) : le MEILLEUR candidat bat-il significativement
    le benchmark, en corrigeant le data-snooping du choix du meilleur ? p-value par bootstrap de la
    stat max-t recentree sous H0. p < 0.05 -> surperformance reelle, pas de la chance."""
    T = len(reference)
    diffs = {k: [candidats[k][t] - reference[t] for t in range(T)] for k in candidats}
    if not diffs:
        return {"p_value": 1.0, "meilleur": None, "significatif": False, "t_obs": 0.0}
    tstat = {k: _t_stat(diffs[k]) for k in diffs}
    t_obs = max(tstat.values())
    meilleur = max(tstat, key=lambda k: tstat[k])
    moyennes = {k: sum(diffs[k]) / T for k in diffs}
    rng = random.Random(seed)
    depasse = 0
    for _ in range(n_boot):
        idx = [rng.randrange(T) for _ in range(T)]
        tmax = -1e18
        for k in diffs:
            dc = [diffs[k][i] - moyennes[k] for i in idx]
            tb = _t_stat(dc)
            if tb > tmax:
                tmax = tb
        if tmax >= t_obs:
            depasse += 1
    p = depasse / n_boot
    return {"p_value": p, "meilleur": meilleur, "significatif": p < 0.05, "t_obs": t_obs}


def stepm_romano_wolf(reference: Sequence[float], candidats: Mapping[str, Sequence[float]], *,
                      alpha: float = 0.05, n_boot: int = 400, seed: int = 7) -> dict:
    """StepM (Romano-Wolf) via Holm step-down sur p-values bootstrap : rend l'ensemble des modeles
    significativement meilleurs que le benchmark en controlant le FWER (pas juste par paire)."""
    T = len(reference)
    rng = random.Random(seed)
    pvals = {}
    for k in candidats:
        d = [candidats[k][t] - reference[t] for t in range(T)]
        m = sum(d) / T
        dc = [x - m for x in d]
        cnt = sum(1 for _ in range(n_boot) if (sum(dc[rng.randrange(T)] for _ in range(T)) / T) >= m)
        pvals[k] = cnt / n_boot
    ordre = sorted(pvals, key=lambda k: pvals[k])
    K = len(ordre)
    rejetes = []
    for i, k in enumerate(ordre):
        if pvals[k] <= alpha / (K - i):
            rejetes.append(k)
        else:
            break
    return {"significatifs": rejetes, "p_values": pvals, "n": len(rejetes)}


def leave_one_out_cv(donnees_par_groupe: Mapping[str, object], evaluer: Callable[[dict, object], float]) -> dict:
    """Leave-One-Out GENERALISE : le groupe est une SESSION (251), un WALLET (252) ou une VENUE (253).
    Pour chaque groupe, on entraine sur tous les autres et on teste sur le groupe retire -> l'edge
    generalise-t-il hors de chaque groupe ? Un edge qui depend d'un seul groupe est fragile."""
    groupes = list(donnees_par_groupe)
    folds = []
    for g in groupes:
        train = {k: v for k, v in donnees_par_groupe.items() if k != g}
        folds.append({"held_out": g, "perf": float(evaluer(train, donnees_par_groupe[g]))})
    perfs = [f["perf"] for f in folds]
    return {"folds": folds, "perf_moyenne": (sum(perfs) / len(perfs)) if perfs else 0.0,
            "pire": min(perfs) if perfs else None, "generalise": all(p > 0 for p in perfs)}


def borne_basse_nette(pnls: Sequence[float], *, alpha: float = 0.05, n_boot: int = 1000, seed: int = 7) -> dict:
    """BORNE BASSE nette bootstrap OBLIGATOIRE : le quantile alpha de la moyenne re-echantillonnee du
    PnL net. On ne promeut JAMAIS sur une moyenne ponctuelle -> il faut que la borne basse soit > 0."""
    n = len(pnls)
    if n == 0:
        return {"borne_basse": None, "moyenne": None, "alpha": alpha}
    rng = random.Random(seed)
    moyennes = sorted(sum(pnls[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    lb = moyennes[min(n_boot - 1, int(alpha * n_boot))]
    return {"borne_basse": lb, "moyenne": sum(pnls) / n, "alpha": alpha}


def protocole_sans_edge(edge_mesure: float | None, *, seuil: float = 0.0) -> dict:
    """Protocole SANS EDGE (deny-by-default) : sans edge positif MESURE (> seuil), la promotion est
    INTERDITE. Un edge non mesurable/nul ne se promeut jamais 'au benefice du doute'."""
    a_un_edge = edge_mesure is not None and float(edge_mesure) > seuil
    return {"edge_positif": a_un_edge, "promotion_autorisee": a_un_edge}


def verdict_promotion(*, borne_basse: float | None, edge_positif: bool, drift_stable: bool,
                      gates_ok: bool = True) -> dict:
    """Verdict POSITIVE_OR_NO_PROMOTION : deny-by-default. On PROMEUT uniquement si TOUT est vrai :
    borne basse nette > 0 (250), edge positif (260), derive stable (254) et gates passees. Sinon
    NO_PROMOTION avec les raisons explicites. Jamais d'ordre reel."""
    raisons = []
    if borne_basse is None or borne_basse <= 0:
        raisons.append("BORNE_BASSE_NETTE_NON_POSITIVE")
    if not edge_positif:
        raisons.append("AUCUN_EDGE_POSITIF")
    if not drift_stable:
        raisons.append("DRIFT_INSTABLE")
    if not gates_ok:
        raisons.append("GATES_ECHOUEES")
    return {"verdict": PROMOTION_POSITIVE if not raisons else NO_PROMOTION,
            "raisons": raisons, "real_execution": False}
