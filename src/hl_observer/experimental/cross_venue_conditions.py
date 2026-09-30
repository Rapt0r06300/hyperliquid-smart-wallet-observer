"""ALPHA-5 — lead-lag cross-venue CONDITIONNÉ aux événements causaux (SHADOW, pur, 0 réseau, 0 ordre).

`cross_venue_events` détecte DÉJÀ des chocs Binance (PRICE_SHOCK / AGG_IMBALANCE / TAKER_BURST) et mesure le
markout HL net de coûts. Ce module ne le duplique pas : il ajoute la couche que la roadmap ALPHA-5 exige —
**ne pas chercher « Binance mène HL » globalement**, mais conditionner chaque choc sur l'état causal du marché
au moment du choc, puis **compter chaque (condition × horizon) comme un essai** au registre global.

Invariants de vérité (tous testés) :
  • une condition dont l'entrée manque vaut `None` — jamais `False` silencieux, et un `None` n'est **jamais**
    retenu par le filtre (deny-by-default) ;
  • les seuils et les fenêtres d'horloge sont **pré-enregistrés** dans ce fichier, avant toute lecture de
    données : aucun balayage, aucun retune a posteriori ;
  • l'embargo retire réellement les chocs trop proches (fenêtres qui se recouvrent = essais corrélés) ;
  • **tous** les essais sont écrits au registre, y compris les KILL : le DSR doit dégonfler sur la population
    complète, pas sur les survivants ;
  • le verdict maximal est `DISCOVERY_PROBE` — ce module ne promeut jamais rien.

Binance = source de SIGNAL uniquement (aucune jambe Binance, zéro frais Binance). 0 réseau, 0 ordre,
0 clé, 0 signature.
"""
from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from hl_observer.experimental import registre_essais
from hl_observer.experimental.cross_venue_events import deux_fenetres, placebo
from hl_observer.experimental.metaorder_l2_tape import (
    ofi_multi_niveaux,
    profondeur_top5,
    spread_regime,
)

FAMILLE_REGISTRE = "CROSS_VENUE_LEAD_LAG_CONDITIONNE"

#: Conditions pré-enregistrées. Toute condition absente de cette liste est un essai non déclaré.
CONDITIONS: tuple[str, ...] = (
    "OFI_ALIGNE",            # le carnet HL pousse DANS le sens du choc
    "OFI_OPPOSE",            # le carnet HL pousse CONTRE le choc (HL a peut-être déjà absorbé)
    "SPREAD_TIGHT",
    "SPREAD_NORMAL",
    "SPREAD_WIDE",
    "DEPTH_THIN",
    "DEPTH_THICK",
    "VOLATILITY_BURST",
    "CLOCK_SECOND_START",
    "CLOCK_MINUTE_START",
    "CLOCK_M5_START",
    "CLOCK_M15_START",
)

#: Seuils FIXÉS AVANT LECTURE. Les changer = nouvelle pré-registration, pas un réglage.
SEUILS: dict[str, float] = {
    "spread_tight_bps": 3.0,
    "spread_wide_bps": 15.0,
    "depth_thin_usd": 25_000.0,
    "depth_thick_usd": 250_000.0,
    "volatilite_burst_bps": 12.0,
    "ofi_min_abs": 1e-9,          # en-deçà, l'OFI n'est pas un signe exploitable
}

#: (période_ms, tolérance_ms) — un choc « au début » d'une horloge pré-enregistrée.
FENETRES_HORLOGE: dict[str, tuple[int, int]] = {
    "CLOCK_SECOND_START": (1_000, 100),
    "CLOCK_MINUTE_START": (60_000, 500),
    "CLOCK_M5_START": (300_000, 1_000),
    "CLOCK_M15_START": (900_000, 2_000),
}

EMBARGO_MS_DEFAUT = 5_000


# ════════════════════════════ conditions ════════════════════════════
def conditions_horloge(t_ms: int | float | None) -> dict[str, bool | None]:
    """Horloges pré-enregistrées. Arithmétique pure : mesurable dès que `t_ms` existe."""
    if t_ms is None:
        return {nom: None for nom in FENETRES_HORLOGE}
    try:
        t = int(t_ms)
    except (TypeError, ValueError):
        return {nom: None for nom in FENETRES_HORLOGE}
    return {nom: bool(t % periode <= tolerance) for nom, (periode, tolerance) in FENETRES_HORLOGE.items()}


def conditions_microstructure(
    direction: int | None,
    *,
    resume_avant: Mapping[str, Any] | None = None,
    resume_apres: Mapping[str, Any] | None = None,
    mid_avant: float | None = None,
    mid_apres: float | None = None,
    seuils: Mapping[str, float] | None = None,
) -> dict[str, bool | None]:
    """État du carnet HL au moment du choc. Toute entrée manquante ⇒ `None` (jamais `False`)."""
    s = dict(SEUILS)
    if seuils:
        s.update(seuils)
    out: dict[str, bool | None] = {
        "OFI_ALIGNE": None, "OFI_OPPOSE": None,
        "SPREAD_TIGHT": None, "SPREAD_NORMAL": None, "SPREAD_WIDE": None,
        "DEPTH_THIN": None, "DEPTH_THICK": None,
        "VOLATILITY_BURST": None,
    }

    ofi = ofi_multi_niveaux(resume_avant, resume_apres)
    if ofi is not None and direction in (1, -1):
        valeur = ofi.get("integrated_ofi")
        if isinstance(valeur, (int, float)) and abs(valeur) > s["ofi_min_abs"]:
            aligne = (valeur > 0) == (direction > 0)
            out["OFI_ALIGNE"] = bool(aligne)
            out["OFI_OPPOSE"] = bool(not aligne)

    regime = spread_regime(resume_apres, tight_bps=s["spread_tight_bps"], wide_bps=s["spread_wide_bps"])
    if regime != "UNMEASURABLE":
        out["SPREAD_TIGHT"] = regime == "TIGHT"
        out["SPREAD_NORMAL"] = regime == "NORMAL"
        out["SPREAD_WIDE"] = regime == "WIDE"

    profondeur = profondeur_top5(resume_apres)
    if profondeur is not None:
        out["DEPTH_THIN"] = bool(profondeur <= s["depth_thin_usd"])
        out["DEPTH_THICK"] = bool(profondeur >= s["depth_thick_usd"])

    if isinstance(mid_avant, (int, float)) and isinstance(mid_apres, (int, float)) and mid_avant > 0:
        variation_bps = abs(mid_apres - mid_avant) / mid_avant * 1e4
        out["VOLATILITY_BURST"] = bool(variation_bps >= s["volatilite_burst_bps"])
    return out


def conditions_du_choc(choc: Mapping[str, Any], contexte: Mapping[str, Any] | None = None,
                       *, seuils: Mapping[str, float] | None = None) -> dict[str, bool | None]:
    """Toutes les conditions pré-enregistrées pour un choc donné."""
    ctx = dict(contexte or {})
    res = conditions_horloge(choc.get("t"))
    res.update(
        conditions_microstructure(
            choc.get("dir"),
            resume_avant=ctx.get("resume_avant"),
            resume_apres=ctx.get("resume_apres"),
            mid_avant=ctx.get("mid_avant"),
            mid_apres=ctx.get("mid_apres"),
            seuils=seuils,
        )
    )
    return {nom: res.get(nom) for nom in CONDITIONS}


def conditionner(mesures: Iterable[Mapping[str, Any]], contextes: Mapping[Any, Mapping[str, Any]] | None = None,
                 *, seuils: Mapping[str, float] | None = None) -> list[dict[str, Any]]:
    """Attache les conditions à chaque mesure, sans muter l'entrée."""
    ctxs = dict(contextes or {})
    out = []
    for m in mesures:
        enrichie = dict(m)
        enrichie["conditions"] = conditions_du_choc(m, ctxs.get(m.get("t_choc")), seuils=seuils)
        out.append(enrichie)
    return out


def filtrer_par_condition(mesures: Iterable[Mapping[str, Any]], condition: str) -> list[dict[str, Any]]:
    """Ne garde que les chocs où la condition est VRAIE. `None` (non mesurable) n'est jamais retenu."""
    return [dict(m) for m in mesures if (m.get("conditions") or {}).get(condition) is True]


def appliquer_embargo(mesures: Sequence[Mapping[str, Any]], embargo_ms: int = EMBARGO_MS_DEFAUT) -> list[dict[str, Any]]:
    """Retire les chocs trop rapprochés : deux fenêtres qui se recouvrent ne sont pas deux preuves."""
    ordonnees = sorted((dict(m) for m in mesures), key=lambda m: m.get("t_choc") or 0)
    gardes: list[dict[str, Any]] = []
    dernier: float | None = None
    for m in ordonnees:
        t = m.get("t_choc")
        if t is None:
            continue
        if dernier is None or (t - dernier) >= embargo_ms:
            gardes.append(m)
            dernier = t
    return gardes


# ════════════════════════════ registre des essais ════════════════════════════
def plan_essais(*, familles: Sequence[str], conditions: Sequence[str] = CONDITIONS,
                horizons: Sequence[int], data_cutoff: Any = None, univers: str = "HL_BINANCE") -> list[dict[str, Any]]:
    """Plan PRÉ-ENREGISTRÉ : chaque (famille × condition × horizon) est un essai déclaré AVANT lecture."""
    plan = []
    for famille in familles:
        for condition in conditions:
            for horizon in horizons:
                params = {"famille": famille, "condition": condition, "horizon_ms": int(horizon),
                          "seuils": dict(SEUILS), "embargo_ms": EMBARGO_MS_DEFAUT}
                plan.append({
                    "family": FAMILLE_REGISTRE,
                    "variant": "%s|%s|%dms" % (famille, condition, int(horizon)),
                    "params": params,
                    "parameter_hash": registre_essais.parameter_hash(params),
                    "data_cutoff": data_cutoff,
                    "universe": univers,
                    "horizon": int(horizon),
                })
    return plan


def enregistrer_plan(root: Path | str, plan: Sequence[Mapping[str, Any]]) -> int:
    """Écrit la pré-registration de TOUS les essais avant d'en mesurer un seul."""
    for essai in plan:
        registre_essais.enregistrer(Path(root), {**essai, "phase": "preregistration", "result": None,
                                                 "pass_kill": None})
    return len(plan)


def enregistrer_resultats(root: Path | str, resultats: Sequence[Mapping[str, Any]]) -> int:
    """Écrit le résultat de TOUS les essais, y compris les KILL — sinon le DSR ne dégonfle que les survivants."""
    for essai in resultats:
        registre_essais.enregistrer(Path(root), {**essai, "phase": "resultat"})
    return len(resultats)


# ════════════════════════════ verdict (jamais une promotion) ════════════════════════════
def _sharpe(nets: Sequence[float]) -> float | None:
    if len(nets) < 2:
        return None
    ecart = statistics.pstdev(nets)
    if ecart <= 1e-12:
        return None
    return statistics.mean(nets) / ecart


def nets_horizon(mesures: Iterable[Mapping[str, Any]], horizon_ref: int) -> list[float]:
    """Nets exploitables d'un horizon donné. Un horizon `NON_MESURABLE` est exclu, jamais compté 0."""
    out = []
    for m in mesures:
        if m.get("statut") != "OK":
            continue
        h = (m.get("par_horizon") or {}).get(str(horizon_ref)) or {}
        if h.get("statut") == "OK" and isinstance(h.get("net_bps"), (int, float)):
            out.append(float(h["net_bps"]))
    return out


def verdict_conditionne(mesures: Sequence[Mapping[str, Any]], horizon_ref: int, *,
                        sharpes_essais: Sequence[float] = (), min_chocs: int = 20,
                        embargo_ms: int = EMBARGO_MS_DEFAUT) -> dict[str, Any]:
    """Verdict SHADOW d'une condition. Statuts possibles : `SHADOW_DONNEES_INSUFFISANTES`, `SHADOW_KILL`,
    `DISCOVERY_PROBE`. **Aucune promotion n'est possible depuis ce module.**"""
    apres_embargo = appliquer_embargo(mesures, embargo_ms)
    nets = nets_horizon(apres_embargo, horizon_ref)
    base: dict[str, Any] = {
        "n_avant_embargo": len(list(mesures)),
        "n_apres_embargo": len(apres_embargo),
        "n_mesurables": len(nets),
        "horizon_ref_ms": int(horizon_ref),
        "embargo_ms": int(embargo_ms),
        "shadow": True,
        "real_execution": False,
        "promotion_possible": False,
    }
    if len(nets) < 2 * min_chocs:
        return {**base, "statut": "SHADOW_DONNEES_INSUFFISANTES",
                "raison": "%d chocs mesurables < %d requis" % (len(nets), 2 * min_chocs),
                "pnl_net_bps": None, "sharpe": None, "dsr": None}

    pnl = round(sum(nets), 3)
    sharpe = _sharpe(nets)
    fenetres = deux_fenetres(apres_embargo, horizon_ref, min_chocs=min_chocs)
    contre = placebo(apres_embargo, horizon_ref)

    dsr_res: dict[str, Any] = {"dsr": None, "motif": "pas de population d'essais"}
    if sharpes_essais:
        try:
            from hl_observer.research_parallel.validation import dsr as _dsr
            dsr_res = _dsr(nets, sharpes_essais=list(sharpes_essais))
        except Exception:  # noqa: BLE001
            dsr_res = {"dsr": None, "motif": "DSR indisponible"}

    armable = bool(fenetres.get("probe_armable")) and pnl > 0
    return {**base, "statut": "DISCOVERY_PROBE" if armable else "SHADOW_KILL",
            "pnl_net_bps": pnl, "pnl_moyen_bps": round(pnl / len(nets), 4),
            "sharpe": round(sharpe, 4) if sharpe is not None else None,
            "deux_fenetres": fenetres, "placebo": contre, "dsr": dsr_res}


__all__ = [
    "CONDITIONS", "SEUILS", "FENETRES_HORLOGE", "EMBARGO_MS_DEFAUT", "FAMILLE_REGISTRE",
    "conditions_horloge", "conditions_microstructure", "conditions_du_choc", "conditionner",
    "filtrer_par_condition", "appliquer_embargo", "plan_essais", "enregistrer_plan",
    "enregistrer_resultats", "nets_horizon", "verdict_conditionne",
]
