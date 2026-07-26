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
#: outils Optuna qui sont des SAMPLERS (stratégie de proposition des points).
SAMPLERS_OPTUNA = {"tpe": "TPESampler", "cma_es": "CmaEsSampler", "nsga2": "NSGAIISampler", "qmc": "QMCSampler"}
#: outils Optuna qui sont des PRUNERS — passés en `pruner=`, JAMAIS comme un sampler (FX-3).
PRUNERS_OPTUNA = {"successive_halving": "SuccessiveHalvingPruner", "hyperband": "HyperbandPruner"}
#: nsga2 est MULTI-OBJECTIFS (plusieurs objectifs, pas un score scalaire unique).
MULTI_OBJECTIF = {"nsga2"}


def _optuna():
    try:
        import optuna  # type: ignore
        return optuna
    except Exception:  # noqa: BLE001
        return None


def disponibilite() -> dict:
    """État de disponibilité de chaque outil (rôle + raison si indisponible). JAMAIS compté comme dispo juste
    parce que le nom existe : les samplers/pruners Optuna sont indisponibles honnêtement si optuna est absent."""
    opt = _optuna()
    d = {}
    for o in OUTILS:
        if o in ("grid", "random"):
            d[o] = {"disponible": True, "role": "sampler_pur", "raison": "pur Python (toujours dispo)"}
        elif o == "qmc":
            d[o] = {"disponible": True, "role": "sampler",
                    "raison": ("QMCSampler Optuna" if opt else "repli Halton pur (optuna absent)")}
        elif o in PRUNERS_OPTUNA:
            d[o] = {"disponible": bool(opt), "role": "pruner", "classe": PRUNERS_OPTUNA[o],
                    "raison": ("optuna present" if opt else "optuna non installe")}
        else:
            d[o] = {"disponible": bool(opt), "role": ("sampler_multiobjectif" if o in MULTI_OBJECTIF else "sampler"),
                    "classe": SAMPLERS_OPTUNA.get(o), "raison": ("optuna present" if opt else "optuna non installe")}
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

    # ── outils purs (grid/random toujours ; qmc en repli Halton SEULEMENT si Optuna absent) ──
    opt_present = _optuna() is not None
    if outil in ("grid", "random") or (outil == "qmc" and not opt_present):
        if outil == "grid":
            props = _grille(espace, n_trials)
        elif outil == "qmc":
            props = [{k: (dom[int(_halton(i, 2) * len(dom)) % len(dom)] if isinstance(dom, (list, tuple))
                          else dom["min"] + (dom["max"] - dom["min"]) * _halton(i, 3))
                      for k, dom in espace.items()} for i in range(n_trials)]
            base["moteur"] = "halton_pur"
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

    # ── outils Optuna (samplers + pruners) ──
    opt = _optuna()
    if not opt:
        if outil == "qmc":                                   # qmc a un repli pur Python (déjà géré plus haut)
            return base
        return {**base, "disponible": False, "lance": False, "raison": "optuna non installe"}
    try:
        storage = None
        if storage_dir is not None:
            Path(storage_dir).mkdir(parents=True, exist_ok=True)
            storage = "sqlite:///%s" % (Path(storage_dir) / ("optuna_%s.db" % outil))

        def _suggest(trial):
            p = {}
            for k, dom in espace.items():
                if isinstance(dom, (list, tuple)):
                    p[k] = trial.suggest_categorical(k, list(dom))
                elif isinstance(dom, dict):
                    p[k] = trial.suggest_float(k, dom["min"], dom["max"])
            return p

        # 1) SAMPLER (proposition des points)
        sampler = None
        nm = SAMPLERS_OPTUNA.get(outil)
        if nm and hasattr(opt.samplers, nm):
            sampler = getattr(opt.samplers, nm)()

        # 2) PRUNER — passé en `pruner=`, jamais comme sampler (FX-3). Base sampler = TPE (ou Random).
        pruner = None
        pn = PRUNERS_OPTUNA.get(outil)
        if pn and hasattr(opt.pruners, pn):
            pruner = getattr(opt.pruners, pn)()
            sampler = getattr(opt.samplers, "TPESampler")() if hasattr(opt.samplers, "TPESampler") else None

        # 3) NSGA-II : MULTI-OBJECTIFS (maximiser net ET pf), pas un score scalaire unique.
        if outil in MULTI_OBJECTIF:
            study = opt.create_study(directions=["maximize", "maximize"], sampler=sampler, storage=storage,
                                     study_name="af_%s" % outil, load_if_exists=True)

            def _obj_multi(trial):
                sc, m = _eval(_suggest(trial))
                if sc is None or m is None:
                    raise opt.TrialPruned()
                return sc, float(m.get("pf", 1.0) or 1.0)    # deux objectifs distincts

            study.optimize(_obj_multi, n_trials=n_trials, catch=(Exception,))
            etats = [t.state.name for t in study.trials]
            pareto = list(getattr(study, "best_trials", []) or [])
            base.update({"lance": True, "multi_objectif": True, "objectifs": ["net", "pf"],
                         "trials_proposes": len(study.trials), "trials_termines": etats.count("COMPLETE"),
                         "trials_prunes": etats.count("PRUNED"), "trials_echoues": etats.count("FAIL"),
                         "n_pareto": len(pareto), "meilleur": ({"n_solutions_pareto": len(pareto)} if pareto else None),
                         "cpu_s": round(time.time() - t0, 4), "storage": storage,
                         "sampler": nm, "pruner": pn})
            return base

        # 4) mono-objectif (tpe / cma_es / qmc / pruners). Les pruners exigent des rapports intermédiaires.
        study = opt.create_study(direction="maximize", sampler=sampler, pruner=pruner, storage=storage,
                                 study_name="af_%s" % outil, load_if_exists=True)

        def _obj(trial):
            params = _suggest(trial)
            dernier = None
            for step in range(4):                            # étapes -> le pruner peut réellement élaguer
                sc, _ = _eval(params)
                if sc is None:
                    raise opt.TrialPruned()
                dernier = sc
                if pruner is not None:
                    trial.report(sc, step)
                    if trial.should_prune():
                        raise opt.TrialPruned()
            return dernier

        study.optimize(_obj, n_trials=n_trials, catch=(Exception,))
        etats = [t.state.name for t in study.trials]
        base.update({"lance": True, "trials_proposes": len(study.trials),
                     "trials_termines": etats.count("COMPLETE"), "trials_prunes": etats.count("PRUNED"),
                     "trials_echoues": etats.count("FAIL"),
                     "meilleur_score": (round(study.best_value, 4) if study.best_trial else None),
                     "meilleur": ({"params": study.best_params} if study.best_trial else None),
                     "cpu_s": round(time.time() - t0, 4), "storage": storage,
                     "sampler": nm, "pruner": pn})
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


__all__ = ["OUTILS", "SAMPLERS_OPTUNA", "PRUNERS_OPTUNA", "MULTI_OBJECTIF", "disponibilite",
           "objectif_multicritere", "optimiser", "lancer_registre"]
