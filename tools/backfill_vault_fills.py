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
# Deeper leader-fill history = more copyable signals to backtest against,
# which shortens the calendar time to a measurable edge. Hyperliquid's
# userFillsByTime serves well beyond this; 90 days stays within the 8h
# collector budget and the time-windowed paginator.
LOOKBACK_J_DEFAUT = 90
# Leaders LENTS (classés par le labo) : ce sont les seuls qu'une copie lente peut suivre, et l'étude de
# leurs décisions agressives a besoin de mois d'histoire. Leur historique de fills est tenu à part, de
# façon incrémentale : il ne passe ni par la liste « retenus » ni par le pipeline de copie.
OUT_FILLS_LEADERS = Path("runtime") / "data" / "leader_fills_backfill.jsonl"
ETAT_LEADERS = Path("runtime") / "data" / "leader_fills_backfill_etat.json"
SCHEMA_ETAT_LEADERS = "hypersmart.leader_fills_backfill_etat.v1"
LOOKBACK_LEADERS_J = 200                      # profondeur des prix horaires disponibles (208 jours)
BUDGET_LEADERS_S = 2400.0
FRONTIERE_MS = 2_000                          # fills relus à la jointure de deux passages (dédupliqués par identité)
# Pagination AU CURSEUR pour ce ruban. Vérifié sur l'API le 2026-11-11 : ``userFillsByTime`` rend ses
# fills par instant croissant, et une page pleine (2 000) contient les plus ANCIENS de la fenêtre ; on
# reprend donc au dernier instant reçu (relu, dédupliqué par identité). Une requête par 2 000 fills, là où
# la subdivision de fenêtres en demandait une trentaine. Un leader qui dépasse ce nombre de pages produit
# trop de fills pour une copie lente : rien n'est écrit pour lui (jamais une couverture partielle) et il
# est laissé de côté tant que le quota n'est pas relevé.
MAX_PAGES_PAR_LEADER = 12
MIN_PAGINATION_WINDOW_MS = 60_000
MAX_FILL_BACKFILL_REQUESTS = 512

Poster = Callable[[str, int, int], Any]
ATTENTE_REFUS_DEBIT_S = 30.0
# Dépôts/retraits : UNE fenêtre pour toute la période (au lieu d'une par jour : 90 fois moins de
# requêtes pour un vault ordinaire). Une réponse d'au moins ``CAP_LEDGER`` lignes est tenue pour
# possiblement tronquée : sa fenêtre est redemandée en deux moitiés, jusqu'à la journée.
# ``FENETRE_LEDGER_MS`` reste la fenêtre d'une semaine, pour qui veut un découpage fixe.
FENETRE_LEDGER_MS = 7 * 24 * 3_600_000
CAP_LEDGER = 2_000


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
        # la pause est RÉELLEMENT prise (``attente`` seule ne faisait que la calculer)
        await asyncio.to_thread(CF.prendre_la_pause, self._limiteur)
        payload = await asyncio.to_thread(
            self._poster, user, int(start_time), int(end_time)
        )
        if not isinstance(payload, list):
            raise HyperliquidInfoError("userFillsByTime returned non-list response")
        # une réponse coûte aussi une unité par 20 fills renvoyés : une page pleine pèse six fois une vide
        cadence = float(getattr(self._limiteur, "intervalle_s", 0.0) or 0.0)
        supplement = CF.pause_pour_poids(len(payload) / 20.0) if cadence > 0 else 0.0
        if supplement > 0:
            await asyncio.sleep(supplement)
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
    a_faire = list(reversed(VB.plan_de_requetes(debut, fin, fenetre_ms=fenetre_ms)))
    while a_faire:
        a, b = a_faire.pop()
        requested += 1
        CF.ceder_au_direct()
        CF.prendre_la_pause(limiteur)
        try:
            try:
                raw = poster(vault_id, a, b)
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or not float(getattr(limiteur, "intervalle_s", 0.0) or 0.0) > 0:
                    raise
                time.sleep(ATTENTE_REFUS_DEBIT_S)        # refus de débit : une attente, un seul nouvel essai
                raw = poster(vault_id, a, b)
            if isinstance(raw, list) and len(raw) >= CAP_LEDGER and b - a > 24 * VB.MS_PAR_HEURE:
                milieu = (a + b) // 2                    # réponse pleine : peut-être tronquée, on redemande plus fin
                a_faire.extend([(milieu + 1, b), (a, milieu)])
                continue
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

    parsed_pages, fill_parse_audit = VB.parser_fills_with_audit(raw_pages, vault=vault_id)
    invalid_fill_count = fill_parse_audit["rejected_count"]
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
        "fill_parse_audit": fill_parse_audit,
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


def _leaders_lents(root: Path) -> list[str]:
    """Leaders que le labo classe lents ou swing ; liste vide si le plan du labo est absent."""
    try:
        sys.path.insert(0, str(RACINE / "tools"))
        from collecter_vaults import leaders_lents
        return list(leaders_lents(root))
    except Exception as exc:  # noqa: BLE001 - ce complément ne doit jamais faire échouer le rattrapage principal
        print(f"[backfill-fills] leaders lents indisponibles ({type(exc).__name__}) : étape sautée", flush=True)
        return []


def _etat_leaders(root: Path) -> dict[str, dict[str, Any]]:
    try:
        brut = json.loads((root / ETAT_LEADERS).read_text(encoding="utf-8"))
        etat = brut.get("leaders") if brut.get("_schema") == SCHEMA_ETAT_LEADERS else None
    except (OSError, ValueError, AttributeError):
        etat = None
    return etat if isinstance(etat, dict) else {}


def _sauver_etat_leaders(root: Path, etat: dict[str, dict[str, Any]]) -> None:
    chemin = root / ETAT_LEADERS
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(chemin.name + ".tmp")
    tmp.write_text(json.dumps({"_schema": SCHEMA_ETAT_LEADERS, "leaders": etat}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(chemin)


def _paginer_en_avant(poster: Poster, vault_id: str, debut_ms: int, fin_ms: int, *, limiteur: CF.Limiteur,
                      max_pages: int, cap: int = VB.CAP_USERFILLS) -> tuple[list[Any], dict[str, Any]]:
    """Toutes les pages de ``[debut_ms, fin_ms]``, de la plus ancienne à la plus récente.

    ``etat`` : ``COMPLET`` (dernière page non pleine), ``QUOTA_EPUISE`` (encore pleine après
    ``max_pages``), ``ECHEC`` (panne ou réponse illisible) ou ``BLOQUE_MEME_INSTANT`` (une page pleine
    d'un seul instant : impossible d'avancer sans risquer un trou)."""
    cadence = float(getattr(limiteur, "intervalle_s", 0.0) or 0.0)
    lignes: list[Any] = []
    curseur, pages, etat = int(debut_ms), 0, "COMPLET"
    while True:
        if pages >= max_pages:
            etat = "QUOTA_EPUISE"
            break
        CF.ceder_au_direct()                                 # un collecteur en direct vient d'être refusé : on attend
        CF.prendre_la_pause(limiteur)
        try:
            try:
                page = poster(vault_id, curseur, int(fin_ms))
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or not cadence > 0:
                    raise
                time.sleep(ATTENTE_REFUS_DEBIT_S)            # refus de débit : une attente, un seul nouvel essai
                page = poster(vault_id, curseur, int(fin_ms))
        except (urllib.error.URLError, OSError, ValueError, TypeError, TimeoutError):
            etat = "ECHEC"
            break
        pages += 1
        if not isinstance(page, list):
            etat = "ECHEC"
            break
        lignes.extend(page)
        if cadence > 0:
            time.sleep(CF.pause_pour_poids(len(page) / 20.0))  # une page pleine pèse six fois une page vide
        if len(page) < cap:
            break
        instants = [f["time"] for f in page if isinstance(f, dict) and type(f.get("time")) is int]
        dernier = max(instants, default=curseur)
        if dernier <= curseur:
            etat = "BLOQUE_MEME_INSTANT"
            break
        curseur = int(dernier)
    return lignes, {"pages": pages, "etat": etat, "curseur": curseur}


def backfill_un_vault_au_curseur_avec_audit(
    root: Path, vault: str, *, lookback_j: int, limiteur: CF.Limiteur, poster: Poster = _post_userfills,
    max_pages: int = MAX_PAGES_PAR_LEADER, now_ms: int | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    """Fills d'un vault sur ``lookback_j`` jours, paginés AU CURSEUR ; même reçu d'audit que la version à fenêtres.

    ``backfill_un_vault_avec_audit`` demande une fenêtre par jour : 90 requêtes au moins par vault, soit
    six heures par passage pour une vingtaine de vaults une fois la cadence réellement respectée. L'API
    rend les fills par instant croissant et une page pleine contient les plus anciens de la fenêtre
    (vérifié le 2026-11-11) : on repart donc du dernier instant reçu, une requête par 2 000 fills.

    Reste fail-closed : ``complete`` exige une dernière page non pleine, aucune panne, aucune ligne
    invalide, et moins de fills que la rétention publique (au-delà, le début de la période est censuré).
    """
    del root
    fin = int(time.time() * 1000) if now_ms is None else int(now_ms)
    debut = fin - int(lookback_j) * 24 * VB.MS_PAR_HEURE
    vault_id = VB.normaliser_vault(vault)
    brut, pagination = _paginer_en_avant(poster, vault_id, debut, fin, limiteur=limiteur, max_pages=int(max_pages),
                                         cap=VB.CAP_USERFILLS)
    parsed, fill_parse_audit = VB.parser_fills_with_audit(
        [ligne for ligne in brut if isinstance(ligne, dict)], vault=vault_id)
    invalid_fill_count = fill_parse_audit["rejected_count"] + sum(1 for ligne in brut if not isinstance(ligne, dict))
    fills = VB.dedupliquer(parsed)
    etat = str(pagination["etat"])
    historical_censored = len(fills) >= VB.RETENTION_USERFILLS
    complete = etat == "COMPLET" and not historical_censored and not invalid_fill_count
    partial_reasons = [raison for raison, vrai in (
        ("MAX_PAGES_REACHED", etat == "QUOTA_EPUISE"), ("PAGINATION_ERROR", etat == "ECHEC"),
        ("CAP_AT_SINGLE_INSTANT", etat == "BLOQUE_MEME_INSTANT"),
        ("PUBLIC_RETENTION_LIMIT_REACHED", historical_censored), ("INVALID_FILL_ROWS", bool(invalid_fill_count)),
    ) if vrai]
    reste = [] if etat == "COMPLET" else [{"start_ms": int(pagination["curseur"]), "end_ms": fin}]
    fill_times = [int(f["ts_ms"]) for f in fills if type(f.get("ts_ms")) is int and int(f["ts_ms"]) > 0]
    audit = {
        "vault": vault_id, "kind": "userFillsByTime", "pagination": "CURSEUR_CROISSANT",
        "requested_start_ms": debut, "requested_end_ms": fin, "cap": VB.CAP_USERFILLS,
        "base_window_ms": fin - debut, "minimum_window_ms": 0, "max_requests": int(max_pages),
        "requested_windows": int(pagination["pages"]),
        "accepted_windows": int(pagination["pages"]) if etat != "ECHEC" else max(0, int(pagination["pages"])),
        "split_windows": 0, "capped_responses": 1 if etat == "BLOQUE_MEME_INSTANT" else 0,
        "failed_windows": reste if etat == "ECHEC" else [],
        "cap_blocked_windows": reste if etat == "BLOQUE_MEME_INSTANT" else [],
        "api_response_cap": VB.CAP_USERFILLS, "window_attempts": [],
        "received_count": len(brut), "fill_parse_audit": fill_parse_audit,
        "last_observed_boundary_ms": int(pagination["curseur"]),
        "pending_windows": len(reste), "pending_window_ranges": reste,
        "request_budget_exhausted": etat == "QUOTA_EPUISE",
        "api_history_limit": VB.RETENTION_USERFILLS, "historical_censored": historical_censored,
        "censoring_reason": "PUBLIC_RETENTION_LIMIT_REACHED" if historical_censored else None,
        "coverage_status": "COMPLETE_FOR_REQUESTED_RANGE" if complete else "CENSORED_OR_PARTIAL",
        "status": "COMPLETE" if complete else "PARTIAL", "partial_reasons": partial_reasons,
        "usable_horizon": {"start_ms": min(fill_times) if fill_times else None,
                           "end_ms": max(fill_times) if fill_times else None,
                           "basis": "observed_historical_rest_fills_only"},
        "prospective_capture_separate": True, "n_fills": len(fills), "complete": bool(complete),
        "paper_read_only": True, "real_execution": False,
    }
    return fills, audit


def backfill_leaders_lents(
    root: Path, *, limiteur: CF.Limiteur, leaders: list[str] | None = None, now_ms: int | None = None,
    budget_s: float = BUDGET_LEADERS_S, max_leaders: int | None = None, poster: Poster = _post_userfills,
    horloge: Callable[[], float] = time.monotonic, lookback_j: int = LOOKBACK_LEADERS_J,
    max_pages_par_leader: int = MAX_PAGES_PAR_LEADER,
) -> dict[str, Any]:
    """Historique de fills des leaders lents, incrémental et borné en durée.

    Premier passage d'un leader : toute la profondeur (``lookback_j``). Passages suivants : seulement
    depuis son dernier fill connu. Les fills sont AJOUTÉS au ruban ; le curseur n'avance que si la
    pagination est allée au bout sans panne — sinon la même période est redemandée (jamais de trou
    silencieux). Un leader qui épuise son quota de pages est marqué trop actif : rien n'est écrit pour
    lui, et il n'est plus redemandé tant que le quota n'est pas relevé.
    Les leaders les moins récemment traités passent d'abord : un passage interrompu n'affame personne."""
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    leaders = _leaders_lents(root) if leaders is None else list(leaders)
    etat = _etat_leaders(root)
    bilan: dict[str, Any] = {"leaders": len(leaders), "traites": 0, "complets": 0, "fills_ajoutes": 0,
                             "incomplets": [], "trop_actifs": 0, "pages": 0, "arret": None}
    chemin = root / OUT_FILLS_LEADERS
    chemin.parent.mkdir(parents=True, exist_ok=True)
    debut = horloge()
    ordre = sorted(leaders, key=lambda v: int((etat.get(VB.normaliser_vault(v)) or {}).get("maj_ms") or 0))
    for vault in ordre[:max_leaders]:
        if horloge() - debut > budget_s:
            bilan["arret"] = "BUDGET_DE_TEMPS"
            break
        vault_id = VB.normaliser_vault(vault)
        connu = etat.get(vault_id) or {}
        if connu.get("trop_actif") and int(connu.get("quota_pages") or 0) >= int(max_pages_par_leader):
            bilan["trop_actifs"] += 1
            continue
        curseur = int(connu.get("dernier_ts_ms") or 0)
        plancher = now_ms - int(lookback_j) * 24 * VB.MS_PAR_HEURE
        brut, pagination = _paginer_en_avant(poster, vault_id, max(plancher, curseur - FRONTIERE_MS), now_ms,
                                             limiteur=limiteur, max_pages=int(max_pages_par_leader))
        bilan["traites"] += 1
        bilan["pages"] += pagination["pages"]
        suivant = dict(connu, maj_ms=now_ms, quota_pages=int(max_pages_par_leader), pages=pagination["pages"],
                       pagination=pagination["etat"], trop_actif=pagination["etat"] == "QUOTA_EPUISE")
        if suivant["trop_actif"]:
            bilan["trop_actifs"] += 1
            etat[vault_id] = dict(suivant, complet=False)
            _sauver_etat_leaders(root, etat)
            continue
        analyses, audit_lecture = VB.parser_fills_with_audit(brut, vault=vault_id)
        fills = VB.dedupliquer(analyses)
        deja = set(connu.get("ids_frontiere") or ())
        nouveaux = [f for f in fills if int(f["ts_ms"]) > curseur - FRONTIERE_MS and VB.canonical_fill_id(f) not in deja]
        if nouveaux:
            with chemin.open("a", encoding="utf-8") as ruban:
                for f in nouveaux:
                    ruban.write(json.dumps({**f, "groupe": "LEADER_LENT", "backfill_recv_ms": now_ms},
                                           ensure_ascii=False) + "\n")
            bilan["fills_ajoutes"] += len(nouveaux)
        couvert = pagination["etat"] == "COMPLET" and not audit_lecture.get("rejected_count")
        suivant["complet"] = couvert
        if couvert:
            # le curseur n'avance qu'après une pagination menée au bout ; il garde l'identité des fills de la jointure
            dernier = max([curseur, *(int(f["ts_ms"]) for f in fills)])
            suivant.update(dernier_ts_ms=dernier, ids_frontiere=sorted(
                {VB.canonical_fill_id(f) for f in fills if int(f["ts_ms"]) >= dernier - FRONTIERE_MS} | (
                    deja if dernier == curseur else set())))
            bilan["complets"] += 1
        else:
            bilan["incomplets"].append(vault_id)
        etat[vault_id] = suivant
        _sauver_etat_leaders(root, etat)
    return bilan


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
    p.add_argument("--sans-leaders", action="store_true", help="ne pas tenir l'historique des leaders lents")
    p.add_argument("--leaders-seulement", action="store_true",
                   help="ne faire que l'historique des leaders lents (sans les vaults retenus)")
    p.add_argument("--budget-leaders-s", type=float, default=BUDGET_LEADERS_S)
    p.add_argument("--max-leaders", type=int, default=None)
    a = p.parse_args(argv)
    root = Path(a.root)
    # Une requête coûte au moins 20 unités d'un budget de 1 200 par minute : à 0,2 s d'intervalle (et sans
    # pause réelle) plus de la moitié des fenêtres étaient refusées. La cadence tient maintenant dans le
    # demi-budget laissé aux rattrapages.
    limiteur = CF.Limiteur(CF.pause_pour_poids(CF.POIDS_REQUETE_INFO))
    code = 0 if a.leaders_seulement else _backfill_retenus(root, a, limiteur)
    if not a.sans_leaders:
        bilan = backfill_leaders_lents(root, limiteur=limiteur, budget_s=a.budget_leaders_s, max_leaders=a.max_leaders)
        print(f"[backfill-fills] leaders lents : {bilan['traites']}/{bilan['leaders']} traités en {bilan['pages']} "
              f"pages, {bilan['complets']} complets, {bilan['fills_ajoutes']} fills ajoutés, {bilan['trop_actifs']} trop "
              f"actifs (laissés au suivi en direct) -> {OUT_FILLS_LEADERS}"
              + (f" | incomplets : {len(bilan['incomplets'])}" if bilan["incomplets"] else "")
              + (f" | interrompu ({bilan['arret']}) : reprise au prochain passage" if bilan["arret"] else ""),
              flush=True)
    return code


def _backfill_retenus(root: Path, a: argparse.Namespace, limiteur: CF.Limiteur) -> int:
    """Rattrapage des vaults RETENUS et du groupe témoin (fills, dépôts/retraits, épisodes)."""
    retenus, temoin = vaults_cibles(root)
    if not retenus:
        print("[backfill-fills] aucun vault retenu (deny-by-default) — rien a backfiller", flush=True)
        return 0

    tous_fills: list[dict] = []
    tous_ledger: list[dict] = []
    fill_audits: list[dict[str, Any]] = []
    ledger_audits: list[dict[str, Any]] = []

    for grp, vaults in (("RETENU", retenus), ("TEMOIN", temoin)):
        for v in vaults:
            fills, fill_audit = backfill_un_vault_au_curseur_avec_audit(
                root, v, lookback_j=a.lookback_j, limiteur=limiteur,
                max_pages=min(int(a.max_requests), MAX_PAGES_PAR_LEADER),
            )
            ledger, ledger_audit = backfill_ledger_un_vault_avec_audit(
                root, v, lookback_j=a.lookback_j, limiteur=limiteur,
                fenetre_ms=int(a.lookback_j) * 24 * VB.MS_PAR_HEURE,
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
