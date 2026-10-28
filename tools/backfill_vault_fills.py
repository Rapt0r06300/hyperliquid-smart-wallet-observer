"""BACKFILL userFillsByTime des vaults RETENUS + groupe TÉMOIN — LECTURE SEULE.

Le backfill est fail-closed : une fenêtre réseau perdue ou une fenêtre encore
saturée au cap minimal est écrite dans l'audit et interdit de déclarer la
couverture complète. Les réponses ``userFillsByTime`` qui atteignent le cap
sont subdivisées récursivement au lieu d'être acceptées silencieusement comme
un historique complet.

0 ordre, 0 clé, 0 signature. Les seuls appels réseau sont les endpoints publics
Hyperliquid ``userFillsByTime`` et ``userNonFundingLedgerUpdates``.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import collecte_fiable as CF  # noqa: E402
from hl_observer.collection import vault_fills_backfill as VB  # noqa: E402
from hl_observer.collection import vault_ledger as VL  # noqa: E402
from hl_observer.hyperliquid.rest_info_client import (  # noqa: E402
    HyperliquidInfoClient,
    HyperliquidInfoError,
)

URL_HL = "https://api.hyperliquid.xyz/info"
OUT_LEDGER = Path("runtime") / "data" / "vault_ledger.jsonl"
SCORES = Path("runtime") / "data" / "vaults_scores.json"
SUIVIS = Path("runtime") / "data" / "vaults_suivis.json"
OUT_FILLS = Path("runtime") / "data" / "vault_fills.jsonl"
OUT_EPISODES = Path("runtime") / "data" / "vault_episodes.jsonl"
OUT_COUVERTURE = Path("runtime") / "data" / "vault_fills_couverture.json"
LOOKBACK_J_DEFAUT = 14
MIN_PAGINATION_WINDOW_MS = 60_000
MAX_FILL_BACKFILL_REQUESTS = 512

Poster = Callable[[str, int, int], Any]


def _post_userfills(vault: str, start_ms: int, end_ms: int, *, timeout_s: float = 10.0) -> Any:
    corps = json.dumps({"type": "userFillsByTime", "user": vault,
                        "startTime": int(start_ms), "endTime": int(end_ms)}).encode("utf-8")
    req = urllib.request.Request(URL_HL, data=corps, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:      # noqa: S310 (URL constante)
        return json.loads(rep.read().decode("utf-8"))


def _post_ledger(vault: str, start_ms: int, end_ms: int, *, timeout_s: float = 10.0) -> Any:
    corps = json.dumps({"type": "userNonFundingLedgerUpdates", "user": vault,
                        "startTime": int(start_ms), "endTime": int(end_ms)}).encode("utf-8")
    req = urllib.request.Request(URL_HL, data=corps, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:      # noqa: S310 (URL constante)
        return json.loads(rep.read().decode("utf-8"))


def _window_failure(a: int, b: int, exc: BaseException) -> dict[str, Any]:
    return {
        "start_ms": int(a),
        "end_ms": int(b),
        "error_type": type(exc).__name__,
        "error": str(exc)[:300],
    }


class _PosterBackfillClient(HyperliquidInfoClient):
    """Adapt the legacy sync poster to the canonical REST pagination engine."""

    def __init__(self, poster: Poster, limiteur: CF.Limiteur) -> None:
        super().__init__()
        self._poster = poster
        self._limiteur = limiteur

    async def user_fills_by_time(
        self,
        user: str,
        start_time: int,
        end_time: int,
        *,
        aggregate_by_time: bool = False,
    ) -> list[dict[str, Any]]:
        del aggregate_by_time
        await asyncio.to_thread(self._limiteur.attente)
        payload = await asyncio.to_thread(
            self._poster, user, int(start_time), int(end_time)
        )
        if not isinstance(payload, list):
            raise HyperliquidInfoError("userFillsByTime returned non-list response")
        return payload


def backfill_ledger_un_vault_avec_audit(
    root: Path,
    vault: str,
    *,
    lookback_j: int,
    limiteur: CF.Limiteur,
    poster: Poster = _post_ledger,
    fenetre_ms: int = 24 * VB.MS_PAR_HEURE,
) -> tuple[list[dict], dict[str, Any]]:
    """Backfill ledger avec preuve explicite de toute fenêtre manquante."""
    del root
    fin = int(time.time() * 1000)
    debut = fin - int(lookback_j) * 24 * VB.MS_PAR_HEURE
    vault_id = VB.normaliser_vault(vault)
    rows: list[dict] = []
    failures: list[dict[str, Any]] = []
    requested = 0
    for a, b in VB.plan_de_requetes(debut, fin, fenetre_ms=fenetre_ms):
        requested += 1
        limiteur.attente()
        try:
            raw = poster(vault_id, a, b)
            rows.extend(VL.parser_ledger(raw, vault=vault_id))
        except (urllib.error.URLError, OSError, ValueError, TypeError, TimeoutError) as exc:
            failures.append(_window_failure(a, b, exc))
    rows.sort(key=lambda row: (int(row.get("ts_ms") or 0), str(row.get("hash") or "")))
    # Dédup ledger déterministe : hash si présent, sinon identité de mouvement.
    seen: set[tuple[Any, ...]] = set()
    deduped: list[dict] = []
    for row in rows:
        key = (
            VB.normaliser_vault(row.get("vault")),
            int(row.get("ts_ms") or 0),
            str(row.get("hash") or ""),
            str(row.get("type") or ""),
            row.get("delta_usd"),
        )
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    audit = {
        "vault": vault_id,
        "kind": "userNonFundingLedgerUpdates",
        "requested_start_ms": debut,
        "requested_end_ms": fin,
        "requested_windows": requested,
        "failed_windows": failures,
        "n_rows": len(deduped),
        "complete": not failures,
        "paper_read_only": True,
        "real_execution": False,
    }
    return deduped, audit


def backfill_ledger_un_vault(root: Path, vault: str, *, lookback_j: int, limiteur: CF.Limiteur,
                             poster: Poster = _post_ledger) -> list[dict]:
    """Compatibilité historique : rend les lignes ; l'audit complet est disponible séparément."""
    return backfill_ledger_un_vault_avec_audit(
        root, vault, lookback_j=lookback_j, limiteur=limiteur, poster=poster
    )[0]


def vaults_cibles(root: Path, *, n_temoin: int = 10) -> tuple[list[str], list[str]]:
    """(retenus, témoins). Pas de score = rien à backfiller (deny-by-default)."""
    retenus: list[str] = []
    temoin: list[str] = []
    try:
        d = json.loads((root / SCORES).read_text(encoding="utf-8"))
        retenus = [str(a) for a in (d.get("retenus") or [])]
        for c in (d.get("classement") or []):
            if not c.get("retenu") and len(temoin) < n_temoin:
                temoin.append(str(c["vault"]))
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return retenus, temoin


def backfill_un_vault_avec_audit(
    root: Path,
    vault: str,
    *,
    lookback_j: int,
    limiteur: CF.Limiteur,
    poster: Poster = _post_userfills,
    cap: int = VB.CAP_USERFILLS,
    fenetre_ms: int = 24 * VB.MS_PAR_HEURE,
    min_fenetre_ms: int = MIN_PAGINATION_WINDOW_MS,
    max_requests: int = MAX_FILL_BACKFILL_REQUESTS,
) -> tuple[list[dict], dict[str, Any]]:
    """Backfill ``userFillsByTime`` adaptatif et fail-closed.

    Une réponse de taille ``cap`` est ambiguë : elle peut être tronquée. On
    subdivise donc la fenêtre jusqu'à obtenir des pages strictement sous le cap.
    Si le cap est encore atteint à la granularité minimale, la couverture reste
    ``complete=False``. Une erreur réseau fait de même ; aucune fenêtre n'est
    prétendue complète par défaut.
    """
    del root
    cap = int(cap)
    if not 0 < cap <= VB.CAP_USERFILLS:
        raise ValueError(f"cap doit etre compris entre 1 et {VB.CAP_USERFILLS}")
    fenetre_ms = int(fenetre_ms)
    min_fenetre_ms = max(0, int(min_fenetre_ms))
    max_requests = int(max_requests)
    if max_requests <= 0:
        raise ValueError("max_requests doit etre > 0")
    fin = int(time.time() * 1000)
    debut = fin - int(lookback_j) * 24 * VB.MS_PAR_HEURE
    vault_id = VB.normaliser_vault(vault)
    client = _PosterBackfillClient(poster, limiteur)
    receipt: dict[str, Any] = {}
    raw_pages: list[dict[str, Any]] = []

    async def collect() -> None:
        async for page, _left, _right in client._iter_user_fills_by_time_windows(
            vault_id,
            debut,
            fin,
            page_window_ms=fenetre_ms,
            max_pages=max_requests,
            min_window_ms=min_fenetre_ms,
            response_cap=cap,
            audit=receipt,
        ):
            raw_pages.extend(page)

    try:
        asyncio.run(collect())
    except HyperliquidInfoError as exc:
        if isinstance(exc.coverage_receipt, dict):
            receipt = exc.coverage_receipt
        elif not receipt:
            receipt.update(
                {
                    "status": "PARTIAL",
                    "reason": "PAGINATION_ERROR",
                    "requested_start_ms": debut,
                    "requested_end_ms": fin,
                    "next_windows": [{"start_ms": debut, "end_ms": fin}],
                    "subrequests": [],
                }
            )
        receipt["pagination_error"] = str(exc)[:300]

    parsed_pages = VB.parser_fills(raw_pages, vault=vault_id)
    invalid_fill_count = len(raw_pages) - len(parsed_pages)
    fills = VB.dedupliquer(parsed_pages)
    attempts = list(receipt.get("subrequests") or [])
    failed_windows = [item for item in attempts if item.get("outcome") == "FAILED"]
    cap_blocked_windows = [item for item in attempts if item.get("outcome") == "CAP_BLOCKED"]
    accepted_windows = sum(
        1 for item in attempts if item.get("outcome") in {"ACCEPTED", "EMPTY"}
    )
    split_windows = sum(1 for item in attempts if item.get("outcome") == "CAP_SPLIT")
    historical_censored = bool(receipt.get("historical_censored")) or (
        len(fills) >= VB.RETENTION_USERFILLS
    )
    complete = (
        receipt.get("status") == "COMPLETE"
        and not historical_censored
        and not invalid_fill_count
    )
    fill_times = [
        int(fill["ts_ms"])
        for fill in fills
        if type(fill.get("ts_ms")) is int and int(fill["ts_ms"]) > 0
    ]
    partial_reasons = list(receipt.get("partial_reasons") or [])
    if historical_censored and "PUBLIC_RETENTION_LIMIT_REACHED" not in partial_reasons:
        partial_reasons.append("PUBLIC_RETENTION_LIMIT_REACHED")
    if invalid_fill_count and "INVALID_FILL_ROWS" not in partial_reasons:
        partial_reasons.append("INVALID_FILL_ROWS")
    if not complete and not partial_reasons:
        partial_reasons.append(str(receipt.get("reason") or "INCOMPLETE_COVERAGE"))
    next_windows = list(receipt.get("next_windows") or [])
    audit = {
        "vault": vault_id,
        "kind": "userFillsByTime",
        "requested_start_ms": debut,
        "requested_end_ms": fin,
        "cap": cap,
        "base_window_ms": fenetre_ms,
        "minimum_window_ms": min_fenetre_ms,
        "max_requests": max_requests,
        "requested_windows": int(receipt.get("request_count") or 0),
        "accepted_windows": accepted_windows,
        "split_windows": split_windows,
        "capped_responses": split_windows + len(cap_blocked_windows),
        "failed_windows": failed_windows,
        "cap_blocked_windows": cap_blocked_windows,
        "api_response_cap": cap,
        "window_attempts": attempts,
        "received_count": int(receipt.get("received_count") or 0),
        "last_observed_boundary_ms": receipt.get("last_observed_boundary_ms"),
        "pending_windows": len(next_windows),
        "pending_window_ranges": next_windows,
        "request_budget_exhausted": receipt.get("reason") == "MAX_PAGES_REACHED",
        "api_history_limit": VB.RETENTION_USERFILLS,
        "historical_censored": historical_censored,
        "censoring_reason": (
            "PUBLIC_RETENTION_LIMIT_REACHED" if historical_censored else None
        ),
        "coverage_status": (
            "COMPLETE_FOR_REQUESTED_RANGE" if complete
            else "CENSORED_OR_PARTIAL"
        ),
        "status": "COMPLETE" if complete else "PARTIAL",
        "partial_reasons": partial_reasons,
        "usable_horizon": {
            "start_ms": min(fill_times) if fill_times else None,
            "end_ms": max(fill_times) if fill_times else None,
            "basis": "observed_historical_rest_fills_only",
        },
        "prospective_capture_separate": True,
        "n_fills": len(fills),
        "complete": bool(complete),
        "paper_read_only": True,
        "real_execution": False,
    }
    return fills, audit


def backfill_un_vault(root: Path, vault: str, *, lookback_j: int, limiteur: CF.Limiteur,
                      poster: Poster = _post_userfills) -> list[dict]:
    """Compatibilité historique : backfill adaptatif puis rend les fills dédupliqués."""
    return backfill_un_vault_avec_audit(
        root, vault, lookback_j=lookback_j, limiteur=limiteur, poster=poster
    )[0]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    if text:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backfill userFillsByTime des vaults (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--lookback-j", type=int, default=LOOKBACK_J_DEFAUT)
    p.add_argument("--max-requests", type=int, default=MAX_FILL_BACKFILL_REQUESTS)
    p.add_argument("--une-fois", action="store_true", default=True)
    a = p.parse_args(argv)
    root = Path(a.root)
    retenus, temoin = vaults_cibles(root)
    if not retenus:
        print("[backfill-fills] aucun vault retenu (deny-by-default) — rien a backfiller", flush=True)
        return 0

    limiteur = CF.Limiteur(0.2)
    tous_fills: list[dict] = []
    tous_ledger: list[dict] = []
    fill_audits: list[dict[str, Any]] = []
    ledger_audits: list[dict[str, Any]] = []

    for grp, vaults in (("RETENU", retenus), ("TEMOIN", temoin)):
        for v in vaults:
            fills, fill_audit = backfill_un_vault_avec_audit(
                root,
                v,
                lookback_j=a.lookback_j,
                limiteur=limiteur,
                max_requests=a.max_requests,
            )
            ledger, ledger_audit = backfill_ledger_un_vault_avec_audit(
                root, v, lookback_j=a.lookback_j, limiteur=limiteur
            )
            fill_audit["groupe"] = grp
            ledger_audit["groupe"] = grp
            fill_audits.append(fill_audit)
            ledger_audits.append(ledger_audit)
            for f in fills:
                f["groupe"] = grp
            tous_fills.extend(fills)
            tous_ledger.extend(ledger)
            print(
                f"[backfill-fills] {grp} {VB.normaliser_vault(v)[:10]} : "
                f"{len(fills)} fills (complete={fill_audit['complete']}), "
                f"ledger={len(ledger)} (complete={ledger_audit['complete']})",
                flush=True,
            )

    tous_fills = VB.dedupliquer(tous_fills)
    # Dédup ledger inter-groupes/vaults par identité stable.
    ledger_seen: set[tuple[Any, ...]] = set()
    ledger_dedup: list[dict] = []
    for row in sorted(tous_ledger, key=lambda item: (int(item.get("ts_ms") or 0), str(item.get("hash") or ""))):
        key = (
            VB.normaliser_vault(row.get("vault")), int(row.get("ts_ms") or 0),
            str(row.get("hash") or ""), str(row.get("type") or ""), row.get("delta_usd"),
        )
        if key not in ledger_seen:
            ledger_seen.add(key)
            ledger_dedup.append(row)
    tous_ledger = ledger_dedup

    episodes = VL.marquer_retraits_ledger(
        VB.reconstruire_episodes(tous_fills), tous_ledger,
        heuristique_secours=VB.marquer_retraits,
    )

    _write_jsonl(root / OUT_FILLS, tous_fills)
    _write_jsonl(root / OUT_EPISODES, episodes)
    _write_jsonl(root / OUT_LEDGER, tous_ledger)

    cov = VB.couverture(tous_fills)
    cov["n_episodes"] = len(episodes)
    cov["n_entrees_alpha"] = len(VB.entrees_alpha(episodes))
    cov["n_retraits_ledger"] = sum(1 for e in episodes if e.get("retrait_source") == "ledger")
    cov["n_retraits_heuristique"] = sum(1 for e in episodes if e.get("retrait_source") == "heuristique")
    cov["backfill_fill_audits"] = fill_audits
    cov["backfill_ledger_audits"] = ledger_audits
    cov["backfill_complete"] = all(row.get("complete") is True for row in fill_audits + ledger_audits)
    cov["paper_read_only"] = True
    cov["real_execution"] = False
    (root / OUT_COUVERTURE).parent.mkdir(parents=True, exist_ok=True)
    (root / OUT_COUVERTURE).write_text(json.dumps(cov, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"[backfill-fills] couverture: {cov['n_fills']} fills, {cov['span_h']:.1f} h, "
        f"{len(cov['coins'])} coins, {cov['n_episodes']} episodes, "
        f"{cov['n_entrees_alpha']} entrees alpha "
        f"(retraits ledger={cov['n_retraits_ledger']} "
        f"heur={cov['n_retraits_heuristique']}) "
        f"complete={cov['backfill_complete']}",
        flush=True,
    )
    # Les données partielles restent disponibles pour diagnostic, mais une
    # couverture incomplète ne peut pas être certifiée par un exit code vert.
    return 0 if cov["backfill_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
