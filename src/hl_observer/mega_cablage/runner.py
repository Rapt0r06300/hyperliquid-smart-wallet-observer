"""[CABLAGE runner] Entrée RUNNABLE de MegaCablage — additive, sans toucher aux gros fichiers (cli.py, routes.py).
Elle suit l'idiome existant de refactor_fusion/runner.py (`run_*` pur → dataclass résultat + `format_*`) et se
lance comme `python -m hl_observer.mega_cablage` (même convention que runtime.persistent_poll_runner).

Deux modes :
  - run_mega_cablage(...)  : one-shot sur un flux d'événements en mémoire OU chargé depuis des logs jsonl ;
  - boucle_continue(...)   : runner continu qui tire des batches d'événements d'une source injectée (callable),
    thread chaque batch dans le pipeline, jusqu'à épuisement / max_iterations.
PAPER STRICT : dry_run only — toute tentative hors dry-run est REFUSÉE (aucune exécution réelle). 0 réseau.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from hl_observer.mega_cablage.pipeline import MegaCablage


@dataclass(frozen=True)
class MegaCablageRunResult:
    ticks: int
    events_traites: int
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


def charger_evenements_logs(chemin: str | Path) -> list[dict[str, Any]]:
    """Charge un flux d'événements depuis un jsonl (ou un dossier de jsonl). Mapping tolérant des noms de champs
    (px/price/mid, sz/size/qty, side/leader_side→signe, time/timestamp_ms→ts_ms, user/wallet_address→vault,
    book, mid). Une ligne sans prix produira un événement rejeté honnêtement en aval (pas de fill fabriqué)."""
    p = Path(chemin)
    fichiers = sorted(p.glob("*.jsonl")) if p.is_dir() else ([p] if p.is_file() else [])
    evenements: list[dict[str, Any]] = []
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
            if not isinstance(row, dict):
                continue
            px = row.get("px", row.get("price", row.get("mid")))
            evenements.append({
                "coin": str(row.get("coin", "")).upper(),
                "px": _f(px), "sz": _f(row.get("sz", row.get("size", row.get("qty")))),
                "signe": _signe(row),
                "ts_ms": row.get("ts_ms", row.get("time", row.get("timestamp_ms",
                          row.get("original_timestamp_ms")))),
                "vault": row.get("vault", row.get("user", row.get("wallet_address", row.get("adresse", "")))),
                "book": row.get("book"), "mid": _f(row.get("mid", px))})
    return evenements


def _resultat(pipe: MegaCablage, n_events: int, dry_run: bool,
              notes: tuple[str, ...] = ()) -> MegaCablageRunResult:
    r = pipe.resume()
    pnl = r["pnl"]
    return MegaCablageRunResult(ticks=r["ticks"], events_traites=n_events, equity=pnl["equity"],
                                realized=pnl["realized"], unrealized=pnl["unrealized"], fees=pnl["fees"],
                                reconcilie=bool(pnl["reconcilie"]), dry_run=dry_run, notes=notes)


def run_mega_cablage(*, evenements: list[dict[str, Any]] | None = None, from_logs: str | Path | None = None,
                     notre_equity: float = 1000.0, notional_max: float = 500.0, fee_bps: float = 4.5,
                     leader_equity_par_vault: dict[str, Any] | None = None,
                     leader_equity_defaut: float | None = None, verifier_unite: bool = True,
                     dry_run: bool = True) -> MegaCablageRunResult:
    """One-shot. Refuse hors dry-run (paper only). Charge depuis logs si from_logs fourni."""
    if not dry_run:
        raise ValueError("mega-cablage is paper/dry-run only — real execution is forbidden")
    flux = list(evenements or [])
    notes: list[str] = []
    if from_logs is not None:
        charges = charger_evenements_logs(from_logs)
        flux.extend(charges)
        if not charges:
            notes.append("AUCUN_EVENEMENT_DANS_LOGS")
    pipe = MegaCablage(notre_equity=notre_equity, notional_max=notional_max, fee_bps=fee_bps,
                       verifier_unite=verifier_unite)
    if not flux:
        return _resultat(pipe, 0, dry_run, tuple(notes) or ("AUCUN_EVENEMENT",))
    equity_map = _EquityMap(leader_equity_par_vault, leader_equity_defaut)
    pipe.traiter_replay(flux, leader_equity_par_vault=equity_map)
    return _resultat(pipe, len(flux), dry_run, tuple(notes))


def boucle_continue(*, source: Callable[[], Any], notre_equity: float = 1000.0, notional_max: float = 500.0,
                    fee_bps: float = 4.5, leader_equity_par_vault: dict[str, Any] | None = None,
                    leader_equity_defaut: float | None = None, max_iterations: int | None = None,
                    dry_run: bool = True) -> MegaCablageRunResult:
    """Runner continu. `source()` rend un batch d'événements (list) ou None/[] pour signaler l'arrêt. Chaque
    batch est threadé par tick. S'arrête sur source vide/None ou max_iterations. Paper strict (dry-run only)."""
    if not dry_run:
        raise ValueError("mega-cablage is paper/dry-run only — real execution is forbidden")
    pipe = MegaCablage(notre_equity=notre_equity, notional_max=notional_max, fee_bps=fee_bps)
    equity_map = _EquityMap(leader_equity_par_vault, leader_equity_defaut)
    n_events = 0
    i = 0
    while max_iterations is None or i < max_iterations:
        batch = source()
        if not batch:
            break
        n_events += len(batch)
        pipe.traiter_replay(list(batch), leader_equity_par_vault=equity_map)
        i += 1
    return _resultat(pipe, n_events, dry_run)


def format_mega_cablage_run(r: MegaCablageRunResult) -> str:
    lignes = [
        "=== mega-cablage (paper, dry-run=%s) ===" % r.dry_run,
        "ticks=%d  events=%d" % (r.ticks, r.events_traites),
        "equity=%.4f  realized=%.4f  unrealized=%.4f  fees=%.4f" % (r.equity, r.realized, r.unrealized, r.fees),
        "PnL reconcilie=%s" % r.reconcilie,
    ]
    if r.notes:
        lignes.append("notes: %s" % ", ".join(r.notes))
    return "\n".join(lignes)


__all__ = ["MegaCablageRunResult", "run_mega_cablage", "boucle_continue",
           "charger_evenements_logs", "format_mega_cablage_run"]
