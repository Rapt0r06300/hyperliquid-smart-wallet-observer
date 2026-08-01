"""[CABLAGE runner] Entrée RUNNABLE de MegaCablage — additive, sans toucher aux gros fichiers (cli.py, routes.py).
Elle suit l'idiome existant de refactor_fusion/runner.py (`run_*` pur → dataclass résultat + `format_*`) et se
lance comme `python -m hl_observer.mega_cablage` (même convention que runtime.persistent_poll_runner).

CHEMIN UNIQUE consolidé : messages bruts (bundles) → feed_adapter.evenements_depuis_bundles → MegaCablage
.traiter_replay. run_mega_cablage, boucle_continue et --from-logs empruntent TOUS exactement ce chemin ; les
messages bruts userFills/L2/BBO/trades passent donc automatiquement par le feed_adapter. Un flux d'événements
déjà normalisés est accepté comme passe-plat ({evenements:[...]}) sans court-circuiter le chemin.

PAPER STRICT : dry_run only — toute tentative hors dry-run est REFUSÉE (aucune exécution réelle). 0 réseau.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from hl_observer.mega_cablage.pipeline import MegaCablage
from hl_observer.mega_cablage.feed_adapter import evenements_depuis_bundles


@dataclass(frozen=True)
class MegaCablageRunResult:
    ticks: int
    events_traites: int
    fills_executes: int
    cross_venue_executes: int
    equity: float
    realized: float
    unrealized: float
    fees: float
    reconcilie: bool
    dry_run: bool
    notes: tuple[str, ...] = ()


class _EquityMap(dict):
    """Map vault→equity avec valeur par défaut optionnelle (modélisation explicite quand l'equity leader réelle
    n'est pas fournie). Sans défaut → .get rend None → la copie refuse honnêtement (UNMEASURABLE)."""

    def __init__(self, base: dict[str, Any] | None, defaut: Any) -> None:
        super().__init__(base or {})
        self._defaut = defaut

    def get(self, cle: Any, defaut: Any = None) -> Any:  # noqa: A003
        v = super().get(cle)
        if v is not None:
            return v
        return self._defaut if self._defaut is not None else defaut


def _f(x: Any) -> Any:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _signe(row: dict[str, Any]) -> int:
    s = row.get("signe")
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        return 1 if s > 0 else (-1 if s < 0 else 0)
    side = str(row.get("side") or row.get("leader_side") or "").upper()
    if side in ("B", "BUY", "LONG"):
        return 1
    if side in ("A", "S", "SELL", "SHORT"):
        return -1
    return 0


def _row_to_event(row: dict[str, Any]) -> dict[str, Any]:
    px = row.get("px", row.get("price", row.get("mid")))
    return {"coin": str(row.get("coin", "")).upper(), "px": _f(px),
            "sz": _f(row.get("sz", row.get("size", row.get("qty")))), "signe": _signe(row),
            "ts_ms": row.get("ts_ms", row.get("time", row.get("timestamp_ms", row.get("original_timestamp_ms")))),
            "vault": row.get("vault", row.get("user", row.get("wallet_address", row.get("adresse", "")))),
            "book": row.get("book"), "mid": _f(row.get("mid", px))}


def _row_to_bundle(row: dict[str, Any]) -> dict[str, Any]:
    """Ligne de log → bundle. Un frame WS BRUT ({channel:...}) est routé par canal (→ passe par le feed_adapter) ;
    sinon la ligne est une observation déjà normalisée → passe-plat {evenements:[event]}."""
    canal = row.get("channel")
    if canal == "userFills":
        return {"userfills_msg": row}
    if canal == "l2Book":
        data = row.get("data", row)
        return {"l2_par_coin": {str(data.get("coin", "")).upper(): data}}
    if canal == "bbo":
        data = row.get("data", row)
        return {"bbo_par_coin": {str(data.get("coin", "")).upper(): data}}
    if canal == "trades":
        return {"trades_msg": row}
    return {"evenements": [_row_to_event(row)]}


def charger_bundles_logs(chemin: str | Path) -> list[dict[str, Any]]:
    """Charge des bundles depuis un jsonl (ou un dossier de jsonl). Frames bruts → bundles par canal (passent par
    le feed_adapter) ; lignes normalisées → passe-plat. Une ligne sans prix produit un événement rejeté
    honnêtement en aval (pas de fill fabriqué)."""
    p = Path(chemin)
    fichiers = sorted(p.glob("*.jsonl")) if p.is_dir() else ([p] if p.is_file() else [])
    bundles: list[dict[str, Any]] = []
    for fichier in fichiers:
        try:
            lignes = fichier.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for ligne in lignes:
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                row = json.loads(ligne)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                bundles.append(_row_to_bundle(row))
    return bundles


def _flux_evenements(*, bundles: list[dict[str, Any]] | None, evenements: list[dict[str, Any]] | None,
                     from_logs: str | Path | None) -> tuple[list[dict[str, Any]], list[str]]:
    """Assemble TOUS les bundles (bundles fournis + évènements passe-plat + logs) puis passe par le feed_adapter :
    chemin unique et identique quel que soit le point d'entrée."""
    tous: list[dict[str, Any]] = list(bundles or [])
    if evenements:
        tous.append({"evenements": list(evenements)})
    notes: list[str] = []
    if from_logs is not None:
        charges = charger_bundles_logs(from_logs)
        tous.extend(charges)
        if not charges:
            notes.append("AUCUN_EVENEMENT_DANS_LOGS")
    return evenements_depuis_bundles(tous), notes


def _resultat(pipe: MegaCablage, n_events: int, dry_run: bool,
              notes: tuple[str, ...] = ()) -> MegaCablageRunResult:
    r = pipe.resume()
    pnl = r["pnl"]
    return MegaCablageRunResult(ticks=r["ticks"], events_traites=n_events,
                                fills_executes=r["fills_executes"], cross_venue_executes=r["cross_venue_executes"],
                                equity=pnl["equity"], realized=pnl["realized"], unrealized=pnl["unrealized"],
                                fees=pnl["fees"], reconcilie=bool(pnl["reconcilie"]), dry_run=dry_run, notes=notes)


def run_mega_cablage(*, bundles: list[dict[str, Any]] | None = None,
                     evenements: list[dict[str, Any]] | None = None, from_logs: str | Path | None = None,
                     notre_equity: float = 1000.0, notional_max: float = 500.0, fee_bps: float = 4.5,
                     leader_equity_par_vault: dict[str, Any] | None = None,
                     leader_equity_defaut: float | None = None, verifier_unite: bool = True,
                     cross_venue_paper: bool = True, dry_run: bool = True) -> MegaCablageRunResult:
    """One-shot sur le chemin unique (feed_adapter → traiter_replay). Refuse hors dry-run (paper only)."""
    if not dry_run:
        raise ValueError("mega-cablage is paper/dry-run only — real execution is forbidden")
    flux, notes = _flux_evenements(bundles=bundles, evenements=evenements, from_logs=from_logs)
    pipe = MegaCablage(notre_equity=notre_equity, notional_max=notional_max, fee_bps=fee_bps,
                       verifier_unite=verifier_unite, cross_venue_paper=cross_venue_paper)
    if not flux:
        return _resultat(pipe, 0, dry_run, tuple(notes) or ("AUCUN_EVENEMENT",))
    pipe.traiter_replay(flux, leader_equity_par_vault=_EquityMap(leader_equity_par_vault, leader_equity_defaut))
    return _resultat(pipe, len(flux), dry_run, tuple(notes))


def boucle_continue(*, source: Callable[[], Any], notre_equity: float = 1000.0, notional_max: float = 500.0,
                    fee_bps: float = 4.5, leader_equity_par_vault: dict[str, Any] | None = None,
                    leader_equity_defaut: float | None = None, max_iterations: int | None = None,
                    cross_venue_paper: bool = True, dry_run: bool = True) -> MegaCablageRunResult:
    """Runner continu. `source()` rend un batch (liste de bundles OU d'événements) ou None/[] pour l'arrêt. Chaque
    batch emprunte le MÊME chemin (feed_adapter → traiter_replay). Paper strict (dry-run only)."""
    if not dry_run:
        raise ValueError("mega-cablage is paper/dry-run only — real execution is forbidden")
    pipe = MegaCablage(notre_equity=notre_equity, notional_max=notional_max, fee_bps=fee_bps,
                       cross_venue_paper=cross_venue_paper)
    equity_map = _EquityMap(leader_equity_par_vault, leader_equity_defaut)
    n_events = 0
    i = 0
    while max_iterations is None or i < max_iterations:
        batch = source()
        if not batch:
            break
        bundles = list(batch) if (batch and isinstance(batch[0], dict) and
                                  any(k in batch[0] for k in ("userfills_msg", "l2_par_coin", "bbo_par_coin",
                                                              "trades_msg", "allmids", "evenements"))) \
            else [{"evenements": list(batch)}]
        flux = evenements_depuis_bundles(bundles)
        n_events += len(flux)
        if flux:
            pipe.traiter_replay(flux, leader_equity_par_vault=equity_map)
        i += 1
    return _resultat(pipe, n_events, dry_run)


def format_mega_cablage_run(r: MegaCablageRunResult) -> str:
    lignes = [
        "=== mega-cablage (paper, dry-run=%s) ===" % r.dry_run,
        "ticks=%d  events=%d  fills=%d  cross_venue=%d" % (r.ticks, r.events_traites, r.fills_executes,
                                                           r.cross_venue_executes),
        "equity=%.4f  realized=%.4f  unrealized=%.4f  fees=%.4f" % (r.equity, r.realized, r.unrealized, r.fees),
        "PnL reconcilie=%s" % r.reconcilie,
    ]
    if r.notes:
        lignes.append("notes: %s" % ", ".join(r.notes))
    return "\n".join(lignes)


__all__ = ["MegaCablageRunResult", "run_mega_cablage", "boucle_continue",
           "charger_bundles_logs", "format_mega_cablage_run", "_EquityMap"]
