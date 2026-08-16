"""Recherche adaptative stricte pour les longs runs autonomes.

Cette voie ne remplace pas ``recherche_scenario``. Elle réutilise ses espaces,
coûts et portes, mais interdit au crible multi-fidélité de regarder la moitié de
validation. Le crible peut éliminer des perdants à partir de TRAIN uniquement ;
il ne peut jamais promouvoir un candidat. Les survivants sont ensuite jugés par
les mêmes moitiés temporelles avec embargo, stress des coûts, plateau, CPCV et
PBO que le moteur historique.

REPLAY/PAPER uniquement : aucune donnée réseau, aucun ordre réel.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from hl_observer.backtesting.ab_flag_replay import DEFAULT_COST_BPS, marks_by_coin, net_baseline_seul
from hl_observer.backtesting.boucle_objectif_replay import boucle_objectif
from hl_observer.backtesting.recherche_scenario import (
    CAP_CRIBLE_CANDIDATS,
    FRACTION_VOISINS_VIVANTS,
    DonneesReplay,
    _sltp,
    annoter_robustesse,
    evaluer_sur_moities,
    filtrer_candidats,
    grille_large,
    porte_robuste,
    raffiner_autour,
    rang_pepite,
    voisins,
)

STRICT_STATE_RELPATH = Path("runtime") / "replay" / "recherche_adaptative_stricte_copy.json"
STRICT_REPORT_RELPATH = Path("runtime") / "replay" / "RECHERCHE_ADAPTATIVE_STRICTE.json"


def _net_arm_a(payload: dict[str, Any]) -> float:
    try:
        return float((payload.get("arm_a") or {}).get("net_total_usd") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def cribler_train_only(
    donnees: DonneesReplay,
    configs: Iterable[dict[str, Any]],
    *,
    screen: Callable[..., dict[str, Any]] = net_baseline_seul,
    cap_candidats: int = CAP_CRIBLE_CANDIDATS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Élimine les pertes évidentes sans jamais consulter la moitié validation.

    Pour chaque horizon, ``moities_avec_embargo`` définit TRAIN et VALIDATION.
    Seule la première moitié est utilisée ici. Afin de garder un coût borné, on
    prend au maximum les ``cap_candidats`` observations les plus récentes de
    TRAIN ; elles restent strictement antérieures à la zone d'embargo.
    """

    liste = [dict(cfg) for cfg in configs]
    if not liste or not donnees.candidats:
        return liste, {
            "schema": "alina.strict_train_scout.v1",
            "input_configs": len(liste),
            "retained_configs": len(liste),
            "screened_configs": 0,
            "validation_rows_seen": 0,
            "status": "NO_SCREEN",
        }

    idx_marks = marks_by_coin(donnees.marks)
    cache_train: dict[tuple[float, tuple[tuple[str, Any], ...]], list[dict[str, Any]]] = {}
    retenues: list[dict[str, Any]] = []
    screened = 0
    failures_open = 0
    train_rows_max = 0

    for i, cfg in enumerate(liste, 1):
        horizon = float(cfg.get("horizon_min") or 60.0)
        filtres = cfg.get("filtres") or {}
        filtre_key = tuple(sorted(filtres.items()))
        key = (horizon, filtre_key)
        train = cache_train.get(key)
        if train is None:
            train_half, _validation_half = donnees.moities_avec_embargo(horizon)
            train = filtrer_candidats(train_half, filtres)
            train.sort(key=lambda row: float(row.get("recorded_at") or 0.0))
            if cap_candidats > 0 and len(train) > cap_candidats:
                train = train[-cap_candidats:]
            cache_train[key] = train
        train_rows_max = max(train_rows_max, len(train))

        # Un crible avec trop peu de TRAIN ne sait rien : il laisse passer.
        if len(train) < 30:
            retenues.append(cfg)
            continue
        screened += 1
        try:
            result = screen(
                train,
                idx_marks,
                base_config=_sltp(cfg),
                horizon_min=horizon,
                cost_bps=DEFAULT_COST_BPS,
            )
            if _net_arm_a(result) > 0.0:
                retenues.append(cfg)
        except Exception:  # noqa: BLE001 - fail-open uniquement pour le crible, jamais la porte finale.
            failures_open += 1
            retenues.append(cfg)

        if i % 25 == 0:
            print(
                "    crible TRAIN strict %d/%d (%d retenues)"
                % (i, len(liste), len(retenues)),
                flush=True,
            )

    audit = {
        "schema": "alina.strict_train_scout.v1",
        "input_configs": len(liste),
        "retained_configs": len(retenues),
        "screened_configs": screened,
        "screen_fail_open": failures_open,
        "max_train_rows_used_per_bucket": train_rows_max,
        "validation_rows_seen": 0,
        "validation_used_for_selection": False,
        "cap_train_candidates": int(cap_candidats),
        "status": "TRAIN_ONLY_SCREENED",
    }
    return retenues, audit


def chercher_copy_strict(
    root: str | Path,
    *,
    configs: Iterable[dict[str, Any]] | None = None,
    max_essais: int | None = None,
    budget_s: float | None = None,
    donnees: DonneesReplay | None = None,
    evaluer_ab: Callable[..., dict[str, Any]] = net_baseline_seul,
    raffiner: bool = True,
) -> dict[str, Any]:
    """Cherche Copy-Vault avec sélection TRAIN-only puis portes historiques complètes."""

    root_path = Path(root)
    d = donnees if donnees is not None else DonneesReplay.charger(root_path, strategie="copy")
    if not d.candidats:
        return {
            "statut": "INSUFFISANT",
            "strategie": "copy",
            "motif": "aucun candidat copy consolide",
            "essais": [],
            "strict_train_only": True,
        }

    base_configs = list(configs if configs is not None else grille_large())
    survivors, scout = cribler_train_only(d, base_configs, screen=evaluer_ab)
    print(
        "  crible TRAIN-only: %d/%d configs gardees; validation vue=0"
        % (len(survivors), len(base_configs)),
        flush=True,
    )

    def evaluer(config: dict[str, Any]) -> dict[str, Any]:
        return evaluer_sur_moities(d, config, evaluer_ab=evaluer_ab)

    def porte_avec_plateau(rapport: dict[str, Any]) -> bool:
        if not porte_robuste(rapport):
            return False
        nearby = voisins(rapport["config"])
        if not nearby:
            return False
        vivants = 0
        for candidate in nearby:
            replay = evaluer_sur_moities(d, candidate, evaluer_ab=evaluer_ab)
            net = float((replay["moitie_1"].get("net_total_usd") or 0.0)) + float(
                (replay["moitie_2"].get("net_total_usd") or 0.0)
            )
            vivants += int(net > 0.0)
        stable = vivants / len(nearby) >= FRACTION_VOISINS_VIVANTS
        if not stable:
            rapport["instabilite"] = "REJETE_INSTABLE: %d/%d voisins vivants" % (
                vivants,
                len(nearby),
            )
        return stable

    state = root_path / STRICT_STATE_RELPATH
    result = boucle_objectif(
        survivors,
        evaluer,
        porte_avec_plateau,
        etat_path=state,
        max_essais=max_essais,
        budget_s=budget_s,
        s_arreter_au_premier=False,
        total_hint=len(survivors),
    )

    if raffiner and result.get("essais"):
        def net12(row: dict[str, Any]) -> float:
            nets = row.get("nets") or {}
            return float(nets.get("moitie_1") or 0.0) + float(nets.get("moitie_2") or 0.0)

        seeds = [row["config"] for row in result["essais"] if row.get("verdict") == "PROMU"]
        seeds += [
            row["config"]
            for row in sorted(
                (
                    row
                    for row in result["essais"]
                    if row.get("verdict") == "REJETE" and row.get("nets")
                ),
                key=net12,
                reverse=True,
            )[:3]
        ]
        refined: list[dict[str, Any]] = []
        seen: set[str] = set()
        for seed in seeds[:6]:
            for candidate in raffiner_autour(seed, pas_sl=5.0, pas_tp=10.0):
                key = json.dumps(candidate, sort_keys=True, separators=(",", ":"))
                if key not in seen:
                    seen.add(key)
                    refined.append(candidate)
        if refined:
            result2 = boucle_objectif(
                refined,
                evaluer,
                porte_avec_plateau,
                etat_path=state,
                max_essais=max_essais,
                budget_s=budget_s,
                s_arreter_au_premier=False,
                total_hint=len(refined),
            )
            result["essais"] = list(result.get("essais") or []) + list(result2.get("essais") or [])
            result["promus"] = list(result.get("promus") or []) + list(result2.get("promus") or [])
            if result["promus"]:
                result["statut"] = "PROMU"
                best = max(
                    result["promus"],
                    key=lambda row: float((row.get("nets") or {}).get("stress") or 0.0),
                )
                result["gagnant"] = best.get("config")

    for promoted in result.get("promus") or []:
        try:
            promoted.update(rang_pepite(d, promoted["config"], evaluer_ab=evaluer_ab))
        except Exception:  # noqa: BLE001
            promoted.setdefault("rang", "ARGENT")
    annoter_robustesse(d, result, evaluer_ab=evaluer_ab)

    result["strategie"] = "copy"
    result["n_candidats"] = len(d.candidats)
    result["strict_train_only"] = True
    result["scout_audit"] = scout
    result["generated_at_unix"] = time.time()
    result["paper_read_only"] = True
    result["real_execution"] = False
    return result


def write_strict_report(root: str | Path, result: dict[str, Any]) -> Path:
    target = Path(root) / STRICT_REPORT_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


__all__ = [
    "STRICT_REPORT_RELPATH",
    "STRICT_STATE_RELPATH",
    "cribler_train_only",
    "chercher_copy_strict",
    "write_strict_report",
]
