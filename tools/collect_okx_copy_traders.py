#!/usr/bin/env python3
"""Discover and observe OKX public copy-trading leaders (GET/read-only only).

Examples:
  python tools/collect_okx_copy_traders.py --network-read --top 15
  python tools/collect_okx_copy_traders.py --network-read --selection-file <frozen.json> --follow

This writes source snapshots to the configured local Alina database. It does not
send orders and its results are not SAFE economic proof or a certified replay.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.config.loader import load_settings  # noqa: E402
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db  # noqa: E402
from hl_observer.storage.repositories import CollectionRepository  # noqa: E402
from hl_observer.wallets.okx_copy_trading import (  # noqa: E402
    OKX_LEADER_ID_RE,
    OkxPublicCopyTradingClient,
    score_okx_leader,
)

REPORT_ROOT = ROOT / "runtime" / "reports" / "okx_copy_vault"
SELECTION_SCHEMA = "alina.okx_copy_trader_selection.v1"


def _now_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _write_immutable_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def discover_and_freeze(
    client: OkxPublicCopyTradingClient,
    *,
    top: int,
    max_pages: int,
) -> tuple[dict[str, Any], Path]:
    raw_rows, coverage = client.discover_leaders(max_pages_per_sort=max_pages)
    ranked: list[dict[str, Any]] = []
    for candidate in raw_rows:
        score, reasons = score_okx_leader(candidate)
        leader = candidate.get("leader") if isinstance(candidate.get("leader"), dict) else {}
        ranked.append({
            "venue": "okx",
            "network": "okx",
            "identity_kind": "public_leader_id",
            "native_account_id": candidate["uniqueCode"],
            "identity": f"okx:okx:{candidate['uniqueCode']}",
            "nickname": str(leader.get("nickName") or ""),
            "pnl_90d_usdt": leader.get("pnl"),
            "pnl_ratio_90d": leader.get("pnlRatio"),
            "win_ratio": leader.get("winRatio"),
            "aum_usdt": leader.get("aum"),
            "lead_days": leader.get("leadDays"),
            "instruments": leader.get("traderInsts") if isinstance(leader.get("traderInsts"), list) else [],
            "rank_observations": candidate.get("rank_observations") or {},
            "shortlist_score_only": score,
            "decision": "ELIGIBLE_FOR_FORWARD_OBSERVATION" if score is not None else "OBSERVE_ONLY",
            "reasons": list(reasons),
            "raw_leader": leader,
        })
    eligible = [item for item in ranked if item["shortlist_score_only"] is not None]
    eligible.sort(key=lambda item: (-float(item["shortlist_score_only"]), item["native_account_id"]))
    # Never freeze a partial leaderboard as a complete opportunity universe.
    selected = eligible[: max(1, min(50, int(top)))] if coverage.get("complete") else []
    for rank, item in enumerate(selected, start=1):
        item["frozen_tracking_rank"] = rank
        item["frozen_reason"] = "highest venue-local OKX shortlist score among measured positive 90d profiles"
    receipt = {
        "schema_version": SELECTION_SCHEMA,
        "selection_id": _now_id(),
        "venue": "okx",
        "network": "okx",
        "read_only": True,
        "economic_proof": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "https://www.okx.com/api/v5/copytrading/public-lead-traders",
        "source_coverage": coverage,
        "candidate_count": len(ranked),
        "eligible_count": len(eligible),
        "tracked_count": len(selected),
        "selection_complete": bool(coverage.get("complete")),
        "tracked": selected,
        "ranked_candidates": ranked,
        "limitations": [
            "rankings are scored only within OKX; scores are not comparable across venues",
            "leaderboard PnL/ROI are screening metrics, not independently reconciled account PnL",
            "this freeze selects accounts for forward observation, not strategy promotion",
            "OKX position history lacks complete fees, funding, deposits/withdrawals and follower execution evidence",
            "incomplete pages remain explicitly incomplete and do not imply universe coverage",
        ],
    }
    selection_path = REPORT_ROOT / "selections" / f"selection-{receipt['selection_id']}.json"
    _write_immutable_json(selection_path, receipt)
    return receipt, selection_path


def load_selection(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SELECTION_SCHEMA or payload.get("venue") != "okx":
        raise ValueError("selection file is not a frozen OKX candidate receipt")
    if payload.get("selection_complete") is not True or not (payload.get("source_coverage") or {}).get("complete"):
        raise ValueError("selection receipt has incomplete leaderboard coverage and cannot be tracked")
    tracked = payload.get("tracked")
    if not isinstance(tracked, list) or len(tracked) > 50:
        raise ValueError("selection receipt has invalid or excessive tracked set")
    seen: set[str] = set()
    for item in tracked:
        code = str(item.get("native_account_id") or "")
        if not OKX_LEADER_ID_RE.fullmatch(code) or code in seen:
            raise ValueError("selection receipt contains an invalid or duplicate OKX leader id")
        seen.add(code)
    return payload


def collect_cycle(
    client: OkxPublicCopyTradingClient,
    selection: dict[str, Any],
    *,
    history_limit: int,
    settings: Any,
    output_dir: Path,
    cycle_id: str,
) -> dict[str, Any]:
    init_db(settings.database_url)
    engine = create_sqlite_engine(settings.database_url)
    sessions = create_session_factory(engine)
    failures: list[dict[str, str]] = []
    observed: list[dict[str, Any]] = []
    raw_assets: list[dict[str, Any]] = []
    raw_dir = output_dir / "responses"
    raw_dir.mkdir(parents=True, exist_ok=True)
    tracked = selection["tracked"]
    with sessions() as session:
        repo = CollectionRepository(session)
        run = repo.create_collection_run(
            mode="okx-public-copy-trading-read-only",
            wallets_count=len(tracked),
            coins_count=0,
            notes=(
                f"selection_id={selection['selection_id']}; research-only; "
                "no order path; not SAFE replay evidence"
            ),
        )
        if settings.collection.store_raw_events:
            repo.store_raw_event(
                source="okx_public_copytrading",
                endpoint="/api/v5/copytrading/public-lead-traders",
                request_type="frozen_selection_receipt",
                request_payload={"selection_id": selection["selection_id"]},
                response_payload={
                    "schema_version": selection["schema_version"],
                    "source_coverage": selection["source_coverage"],
                    "tracked": selection["tracked"],
                    "created_at_utc": selection["created_at_utc"],
                },
                success=True,
            )
        for leader in tracked:
            code = str(leader["native_account_id"])
            identity = f"okx:{code}"
            try:
                result = client.observe_leader(code, limit=history_limit)
                endpoint_status: dict[str, Any] = {}
                successful_endpoints = 0
                for name in ("current_positions", "position_history"):
                    response = result[name]
                    endpoint = str(response["request"]["path"])
                    if response["error"]:
                        message = str(response["error"])[:500]
                        failures.append({"identity": identity, "endpoint": name, "error": message})
                        endpoint_status[name] = {"status": "ERROR", "row_count": None}
                        repo.store_raw_event(
                            source="okx_public_copytrading",
                            endpoint=endpoint,
                            request_type=f"{name}_failed",
                            request_payload={**response["request"]["params"], "selection_id": selection["selection_id"]},
                            response_payload={},
                            wallet_address=identity,
                            success=False,
                            error_message=message,
                        )
                        repo.update_source_health(
                            f"okx_public_copytrading:{name}",
                            is_success=False,
                            is_consistent=True,
                            error_message=message,
                        )
                        continue
                    if response["possibly_truncated_at_api_limit"]:
                        message = f"{name} reached the API limit ({history_limit}); response is incomplete"
                        failures.append({"identity": identity, "endpoint": name, "error": message})
                        endpoint_status[name] = {
                            "status": "INCOMPLETE_TRUNCATED",
                            "row_count": response["row_count"],
                            "possibly_truncated": True,
                        }
                    else:
                        endpoint_status[name] = {
                            "status": "OBSERVED_COMPLETE_WITHIN_ENDPOINT_SCOPE",
                            "row_count": response["row_count"],
                            "possibly_truncated": False,
                        }
                    successful_endpoints += 1
                    request = response["request"]
                    raw_path = raw_dir / f"{code}-{name}.json"
                    _write_immutable_json(raw_path, response["response"])
                    raw_assets.append({
                        "identity": identity,
                        "endpoint": name,
                        "path": str(raw_path.relative_to(output_dir)),
                        "response_sha256": str(response["response_sha256"]),
                        "file_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                        "row_count": response["row_count"],
                        "possibly_truncated": bool(response["possibly_truncated_at_api_limit"]),
                    })
                    repo.store_raw_event(
                        source="okx_public_copytrading",
                        endpoint=endpoint,
                        request_type=name,
                        request_payload={**request["params"], "selection_id": selection["selection_id"]},
                        response_payload=response["response"],
                        wallet_address=identity,
                        success=True,
                    )
                    repo.update_source_health(
                        f"okx_public_copytrading:{name}",
                        is_success=True,
                        event_timestamp_ms=int(result["observed_at_ms"]),
                    )
                observed.append({
                    "identity": identity,
                    "endpoints": endpoint_status,
                    "successful_endpoint_count": successful_endpoints,
                    "economic_proof_ready": False,
                })
            except Exception as exc:  # surfaced in run receipt; keep other leaders collecting
                message = f"{type(exc).__name__}: {exc}"[:500]
                failures.append({"identity": identity, "error": message})
                repo.store_raw_event(
                    source="okx_public_copytrading",
                    endpoint="/api/v5/copytrading/public-current-subpositions",
                    request_type="leader_observation_failed",
                    request_payload={"uniqueCode": code, "selection_id": selection["selection_id"]},
                    response_payload={},
                    wallet_address=identity,
                    success=False,
                    error_message=message,
                )
                repo.update_source_health(
                    "okx_public_copytrading:leader_observation",
                    is_success=False,
                    is_consistent=True,
                    error_message=message,
                )
        repo.finish_collection_run(run, success=not failures, errors_count=len(failures))
        session.commit()
        run_id = run.id
    engine.dispose()
    return {
        "schema_version": "alina.okx_copy_trader_collection.v1",
        "cycle_id": cycle_id,
        "selection_id": selection["selection_id"],
        "collection_run_id": run_id,
        "venue": "okx",
        "tracked_count": len(tracked),
        "observed_count": len(observed),
        "cycle_complete": not failures and all(
            item["successful_endpoint_count"] == 2 for item in observed
        ),
        "failures": failures,
        "observations": observed,
        "raw_assets": raw_assets,
        "economic_proof_ready": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OKX public copy-trader discovery/collection (read-only)")
    parser.add_argument("--network-read", action="store_true", help="explicitly allow documented public GET requests")
    parser.add_argument("--selection-file", type=Path, help="reuse an immutable frozen selection instead of ranking again")
    parser.add_argument("--top", type=int, default=15, help="number of qualified leaders to freeze, maximum 50")
    parser.add_argument("--max-pages-per-sort", type=int, default=100, help="bounded pages per ranking sort; stops safely if the API reports more")
    parser.add_argument("--history-limit", type=int, default=100, help="OKX rows per public activity endpoint, 1..100")
    parser.add_argument("--follow", action="store_true", help="repeat collection for this frozen set until Ctrl+C")
    parser.add_argument("--interval-seconds", type=int, default=300, help="pause between follow cycles")
    parser.add_argument("--phase-state", type=Path, help="stop continuous collection when this canonical state leaves COLLECT")
    parser.add_argument("--base-url", default="https://www.okx.com", help="official OKX API hostname only")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not args.network_read:
        print("Refus : ajoutez --network-read pour autoriser les GET publics OKX.")
        return 2
    if not 1 <= args.top <= 50 or not 1 <= args.history_limit <= 100 or not 1 <= args.max_pages_per_sort <= 100:
        print("Refus : limites invalides.")
        return 2
    settings = load_settings()
    if not settings.collection.store_raw_events:
        print("Refus : collection brute désactivée dans config; aucune observation non persistée ne sera présentée comme collectée.")
        return 2
    if os.getenv("HYPERSMART_DISABLE_RAW_STORAGE", "0").strip().lower() in {"1", "true", "yes", "on"}:
        print("Refus : HYPERSMART_DISABLE_RAW_STORAGE empêche la persistance des réponses publiques.")
        return 2
    expected_phase_epoch: int | None = None
    if args.phase_state:
        try:
            phase = json.loads(args.phase_state.read_text(encoding="utf-8"))
            if phase.get("phase") != "COLLECT" or not isinstance(phase.get("epoch"), int):
                print("Refus : le control plane n'est pas en phase COLLECT.")
                return 2
            expected_phase_epoch = int(phase["epoch"])
        except (OSError, ValueError, AttributeError) as exc:
            print(f"Refus : état du control plane illisible ({type(exc).__name__}).")
            return 2
    client = OkxPublicCopyTradingClient(base_url=args.base_url, timeout_seconds=settings.collection.request_timeout_seconds)
    if args.selection_file:
        selection_path = args.selection_file.resolve()
        selection = load_selection(selection_path)
        print(f"Sélection gelée chargée : {selection['selection_id']} ({len(selection['tracked'])} leaders)")
    else:
        attempt = 0
        while True:
            attempt += 1
            print(f"[1/2] Recherche OKX {attempt} : classement complet sur PnL, ROI, réussite et AUM...")
            selection, selection_path = discover_and_freeze(
                client,
                top=args.top,
                max_pages=args.max_pages_per_sort,
            )
            if selection["selection_complete"] or (not args.follow and attempt >= 5):
                break
            delay = min(60, max(3, 2 ** min(attempt, 6)))
            print(f"Classement incomplet; aucune sélection ne sera utilisée. Nouvelle tentative dans {delay}s.")
            time.sleep(delay)
        print(
            f"Candidats {selection['candidate_count']} | admissibles {selection['eligible_count']} | "
            f"retenus {selection['tracked_count']} | couverture complète {selection['source_coverage']['complete']}"
        )
        print(f"Sélection immuable : {selection_path}")
    if not selection.get("tracked"):
        if not selection.get("selection_complete"):
            print("DONNÉES INCOMPLÈTES : classement partiel; aucun portefeuille n'est gelé ni évalué.")
        else:
            print("Aucun portefeuille OKX ne passe le filtre mesuré; aucun score ni PnL n'est inventé.")
        return 0
    cycles = 0
    try:
        while True:
            if args.phase_state:
                try:
                    phase = json.loads(args.phase_state.read_text(encoding="utf-8"))
                    if phase.get("phase") != "COLLECT" or phase.get("epoch") != expected_phase_epoch:
                        print("Phase/epoch modifiée : arrêt propre de la collecte continue.")
                        break
                except (OSError, ValueError, AttributeError) as exc:
                    print(f"État de phase invalide; arrêt fail-closed ({type(exc).__name__}).")
                    break
            cycles += 1
            print(f"[2/2] Collecte des positions ouvertes et clôturées — cycle {cycles}...")
            cycle_id = _now_id()
            report_dir = REPORT_ROOT / "collections" / cycle_id
            report = collect_cycle(
                client,
                selection,
                history_limit=args.history_limit,
                settings=settings,
                output_dir=report_dir,
                cycle_id=cycle_id,
            )
            report_path = report_dir / "RAPPORT.json"
            _write_immutable_json(report_path, report)
            print(
                f"Réponses reçues {report['observed_count']}/{report['tracked_count']} | "
                f"cycle complet {report['cycle_complete']} | erreurs/incomplétudes {len(report['failures'])} | "
                "preuve économique : NON"
            )
            print(f"Rapport : {report_path}")
            if not args.follow:
                break
            interval = max(30, min(86_400, int(args.interval_seconds)))
            print(f"Prochain cycle dans {interval}s. Ctrl+C arrête après sauvegarde du cycle terminé.")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Arrêt demandé; tous les cycles terminés et rapports restent conservés.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
