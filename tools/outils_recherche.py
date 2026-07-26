"""REGISTRE DES OUTILS DE RECHERCHE + OPTUNA (Flo 26/07, AF-P5). On ne compte JAMAIS un outil parce que son nom
existe : chaque outil déclare disponible/indisponible (avec raison), et quand il tourne il publie trials
proposés/terminés/prunés/échoués, meilleur résultat et temps CPU. Grid/Random/QMC(Halton) sont purs Python et
tournent RÉELLEMENT ; TPE/CMA-ES/NSGA-II/Hyperband passent par Optuna (SQLite + reprise) si installé, sinon
`disponible=False` honnête. L'objectif est MULTI-CRITÈRES (jamais le PnL brut seul). 0 réseau, 0 ordre.
"""
from __future__ import annotations

import itertools
import random
import time
from pathlib import Path

OUTILS = ("grid", "random", "qmc", "tpe", "cma_es", "nsga2", "successive_halving", "hyperband")
OUTILS_OPTUNA = {"tpe": "TPESampler", "cma_es": "CmaEsSampler", "nsga2": "NSGAIISampler",
                 "hyperband": "HyperbandPruner", "successive_halving": "SuccessiveHalvingPruner"}


def _optuna():
    try:
        import optuna  # type: ignore
        return optuna
    except Exception:  # noqa: BLE001
        return None


def disponibilite() -> dict:
    """État de disponibilité de chaque outil (avec raison si indisponible)."""
    opt = _optuna()
    d = {}
    for o in OUTILS:
        if o in ("grid", "random", "qmc"):
            d[o] = {"disponible": True, "raison": "pur Python (toujours dispo)"}
        else:
            d[o] = {"disponible": bool(opt), "raison": ("optuna present" if opt else "optuna non installe")}
    return d


# ─────────── objectif MULTI-CRITÈRES ───────────
def objectif_multicritere(metriques: dict) -> float:
    """Score composite : maximise net/roi/pf/dsr/stabilité/capacité, pénalise drawdown/coûts/pbo/concentration/
    sensibilité/turnover. Réutilise le scoring du scheduler (source unique)."""
    import scheduler_continue as SCH
    return SCH.score_multicritere(metriques)


# ─────────── générateurs purs ───────────
def _echantillon(espace: dict, tirage) -> dict:
    p = {}
    for k, dom in espace.items():
        if isinstance(dom, (list, tuple)):
            p[k] = dom[int(tirage(len(dom))) % len(dom)]
        elif isinstance(dom, dict) and "min" in dom:
            p[k] = dom["min"] + (dom["max"] - dom["min"]) * tirage(1.0)
    return p


def _halton(i: int, base: int) -> float:
    f, r, x = 1.0, 0.0, i + 1
    while x > 0:
        f /= base
        r += f * (x % base)
        x //= base
    return r


def _grille(espace: dict, n: int):
    axes = []
    for k, dom in espace.items():
        if isinstance(dom, (list, tuple)):
            axes.append([(k, v) for v in dom])
        elif isinstance(dom, dict):
            pas = 5
            axes.append([(k, dom["min"] + (dom["max"] - dom["min"]) * j / (pas - 1)) for j in range(pas)])
    out = []
    for combo in itertools.product(*axes):
        out.append(dict(combo))
        if len(out) >= n:
            break
    return out


def optimiser(evaluer_params, espace: dict, *, outil: str = "random", n_trials: int = 24,
              storage_dir: Path | None = None, seed: int = 0) -> dict:
    """Lance RÉELLEMENT `outil` : propose des paramètres, appelle `evaluer_params(params)->metriques`, calcule
    l'objectif multi-critères, suit le meilleur. Rend les compteurs réels. Optuna si dispo (SQLite + reprise)."""
    t0 = time.time()
    base = {"outil": outil, "disponible": True, "lance": False, "trials_proposes": 0, "trials_termines": 0,
            "trials_prunes": 0, "trials_echoues": 0, "meilleur": None, "meilleur_score": None, "cpu_s": 0.0}
    rng = random.Random(seed)

    def _eval(params):
        try:
            m = evaluer_params(params)
            return objectif_multicritere(m), m
        except Exception:  # noqa: BLE001
            return None, None

    # ── outils purs ──
    if outil in ("grid", "random", "qmc"):
        if outil == "grid":
            props = _grille(espace, n_trials)
        elif outil == "qmc":
            props = [{k: (dom[int(_halton(i, 2) * len(dom)) % len(dom)] if isinstance(dom, (list, tuple))
                          else dom["min"] + (dom["max"] - dom["min"]) * _halton(i, 3))
                      for k, dom in espace.items()} for i in range(n_trials)]
        else:
            props = [_echantillon(espace, lambda n: rng.random() * n) for _ in range(n_trials)]
        base["lance"] = True; base["trials_proposes"] = len(props)
        for params in props:
            sc, m = _eval(params)
            if sc is None:
                base["trials_echoues"] += 1
                continue
            base["trials_termines"] += 1
            if base["meilleur_score"] is None or sc > base["meilleur_score"]:
                base["meilleur_score"], base["meilleur"] = round(sc, 4), {"params": params, "metriques": m}
        base["cpu_s"] = round(time.time() - t0, 4)
        return base

    # ── outils Optuna ──
    opt = _optuna()
    if not opt:
        return {**base, "disponible": False, "lance": False, "raison": "optuna non installe"}
    try:
        storage = None
        if storage_dir is not None:
            Path(storage_dir).mkdir(parents=True, exist_ok=True)
            storage = "sqlite:///%s" % (Path(storage_dir) / ("optuna_%s.db" % outil))
        sampler = None
        nm = OUTILS_OPTUNA.get(outil)
        if nm in ("TPESampler", "CmaEsSampler", "NSGAIISampler") and hasattr(opt.samplers, nm):
            sampler = getattr(opt.samplers, nm)()
        study = opt.create_study(direction="maximize", sampler=sampler, storage=storage,
                                 study_name="af_%s" % outil, load_if_exists=True)

        def _obj(trial):
            params = {}
            for k, dom in espace.items():
                if isinstance(dom, (list, tuple)):
                    params[k] = trial.suggest_categorical(k, list(dom))
                elif isinstance(dom, dict):
                    params[k] = trial.suggest_float(k, dom["min"], dom["max"])
            sc, _ = _eval(params)
            if sc is None:
                raise opt.TrialPruned()
            return sc

        study.optimize(_obj, n_trials=n_trials, catch=(Exception,))
        etats = [t.state.name for t in study.trials]
        base.update({"lance": True, "trials_proposes": len(study.trials),
                     "trials_termines": etats.count("COMPLETE"), "trials_prunes": etats.count("PRUNED"),
                     "trials_echoues": etats.count("FAIL"),
                     "meilleur_score": (round(study.best_value, 4) if study.best_trial else None),
                     "meilleur": ({"params": study.best_params} if study.best_trial else None),
                     "cpu_s": round(time.time() - t0, 4), "storage": storage})
        return base
    except Exception as e:  # noqa: BLE001
        return {**base, "disponible": True, "lance": False, "raison": "erreur optuna: %s" % str(e)[:120]}


def lancer_registre(evaluer_params, espace: dict, *, n_trials: int = 16, storage_dir: Path | None = None) -> dict:
    """Lance chaque outil DISPONIBLE et rend un tableau d'état (les indisponibles restent listés avec raison)."""
    res = {}
    for o in OUTILS:
        res[o] = optimiser(evaluer_params, espace, outil=o, n_trials=n_trials, storage_dir=storage_dir)
    return {"outils": res, "n_disponibles": sum(1 for v in res.values() if v.get("disponible")),
            "n_lances": sum(1 for v in res.values() if v.get("lance")),
            "n_avec_trials_reels": sum(1 for v in res.values() if (v.get("trials_termines") or 0) > 0)}


__all__ = ["OUTILS", "disponibilite", "objectif_multicritere", "optimiser", "lancer_registre"]
