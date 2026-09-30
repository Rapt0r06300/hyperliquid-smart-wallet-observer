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
import json
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any, Callable

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import collecte_fiable as CF  # noqa: E402
from hl_observer.collection import vault_fills_backfill as VB  # noqa: E402
from hl_observer.collection import vault_ledger as VL  # noqa: E402

URL_HL = "https://api.hyperliquid.xyz/info"
OUT_LEDGER = Path("runtime") / "data" / "vault_ledger.jsonl"
SCORES = Path("runtime") / "data" / "vaults_scores.json"
SUIVIS = Path("runtime") / "data" / "vaults_suivis.json"
OUT_FILLS = Path("runtime") / "data" / "vault_fills.jsonl"
OUT_EPISODES = Path("runtime") / "data" / "vault_episodes.jsonl"
OUT_COUVERTURE = Path("runtime") / "data" / "vault_fills_couverture.json"
LOOKBACK_J_DEFAUT = 14
MIN_PAGINATION_WINDOW_MS = 60_000

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
    if cap <= 0:
        raise ValueError("cap doit etre > 0")
    fenetre_ms = int(fenetre_ms)
    min_fenetre_ms = max(1, int(min_fenetre_ms))
    fin = int(time.time() * 1000)
    debut = fin - int(lookback_j) * 24 * VB.MS_PAR_HEURE
    vault_id = VB.normaliser_vault(vault)
    pending = deque(VB.plan_de_requetes(debut, fin, fenetre_ms=fenetre_ms))
    brut: list[dict] = []
    failed_windows: list[dict[str, Any]] = []
    cap_blocked_windows: list[dict[str, Any]] = []
    requested_windows = 0
    split_windows = 0
    capped_responses = 0
    accepted_windows = 0

    while pending:
        a, b = pending.popleft()
        requested_windows += 1
        limiteur.attente()
        try:
            rep = poster(vault_id, a, b)
        except (urllib.error.URLError, OSError, ValueError, TypeError, TimeoutError) as exc:
            failed_windows.append(_window_failure(a, b, exc))
            continue
        if not isinstance(rep, list):
            failed_windows.append({
                "start_ms": int(a), "end_ms": int(b),
                "error_type": "INVALID_RESPONSE_TYPE",
                "error": type(rep).__name__,
            })
            continue
        parsed = VB.parser_fills(rep, vault=vault_id)
        if len(rep) >= cap:
            capped_responses += 1
            span = int(b) - int(a)
            if span <= min_fenetre_ms:
                cap_blocked_windows.append({
                    "start_ms": int(a), "end_ms": int(b),
                    "response_rows": len(rep), "cap": cap,
                    "reason": "CAP_REACHED_AT_MINIMUM_WINDOW",
                })
                # On conserve les données observées pour diagnostic, mais elles
                # ne peuvent jamais rendre la couverture complète.
                brut.extend(parsed)
                continue
            mid = int(a) + max(1, span // 2)
            if mid >= int(b):
                cap_blocked_windows.append({
                    "start_ms": int(a), "end_ms": int(b),
                    "response_rows": len(rep), "cap": cap,
                    "reason": "UNSPLITTABLE_CAPPED_WINDOW",
                })
                brut.extend(parsed)
                continue
            # Le parent capped n'est PAS accepté ; seuls ses enfants peuvent
            # certifier la couverture de cet intervalle.
            pending.appendleft((mid, int(b)))
            pending.appendleft((int(a), mid))
            split_windows += 1
            continue
        brut.extend(parsed)
        accepted_windows += 1

    fills = VB.dedupliquer(brut)
    complete = not failed_windows and not cap_blocked_windows
    audit = {
        "vault": vault_id,
        "kind": "userFillsByTime",
        "requested_start_ms": debut,
        "requested_end_ms": fin,
        "cap": cap,
        "base_window_ms": fenetre_ms,
        "minimum_window_ms": min_fenetre_ms,
        "requested_windows": requested_windows,
        "accepted_windows": accepted_windows,
        "split_windows": split_windows,
        "capped_responses": capped_responses,
        "failed_windows": failed_windows,
        "cap_blocked_windows": cap_blocked_windows,
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
                root, v, lookback_j=a.lookback_j, limiteur=limiteur
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
                "[backfill-fills] %s %s : %d fills (complete=%s), ledger=%d (complete=%s)"
                % (grp, VB.normaliser_vault(v)[:10], len(fills), fill_audit["complete"],
                   len(ledger), ledger_audit["complete"]),
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
        "[backfill-fills] couverture: %d fills, %.1f h, %d coins, %d episodes, %d entrees alpha "
        "(retraits ledger=%d heur=%d) complete=%s"
        % (cov["n_fills"], cov["span_h"], len(cov["coins"]), cov["n_episodes"], cov["n_entrees_alpha"],
           cov["n_retraits_ledger"], cov["n_retraits_heuristique"], cov["backfill_complete"]),
        flush=True,
    )
    # Les données partielles restent disponibles pour diagnostic, mais une
    # couverture incomplète ne peut pas être certifiée par un exit code vert.
    return 0 if cov["backfill_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
