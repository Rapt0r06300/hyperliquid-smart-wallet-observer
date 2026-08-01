"""[LANCEUR item 2/5] Collecteur dYdX LIVE — auto-démarré par le profil HARVEST.

Relie le WebSocket dYdX v4 (indexer.dydx.trade) à la persistance : markets + trades + orderbooks +
subaccounts sont vraiment écrits en SQLite (via DydxIndexer.process_ws_message), avec dédup, gap
recovery REST, heartbeat et reprise après crash (PiloteFluxDydx). Le marché est injecté depuis l'id du
canal. Respecte le budget WS (nombre de marchés borné).

dYdX v4 LEGACY réel — RIEN à voir avec la simulation Hyperliquid : LECTURE SEULE, 0 ordre, 0 clé, 0
signature. Le cœur (souscription, boucle bornée) est INJECTABLE → prouvé sans réseau ; la connexion
réelle tourne sur la machine de Flo.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Callable, Sequence

RACINE = Path(__file__).resolve().parents[1]
for _p in (RACINE / "src", RACINE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

NOM = "dydx-live"
MAX_MARCHES_DEFAUT = 5          # borne le budget WS (trades + orderbook par marché)


def plan_souscription(ws: Any, *, marches: Sequence[str], subaccounts: Sequence[tuple[str, int]],
                      max_marches: int = MAX_MARCHES_DEFAUT) -> dict[str, int]:
    """Souscrit markets + (trades, orderbook) des N premiers marchés + subaccounts. Rend le compte réel
    (borné) pour respecter le quota WS."""
    ws.subscribe_markets()
    retenus = list(marches)[:max(0, int(max_marches))]
    for m in retenus:
        ws.subscribe_trades(m)
        ws.subscribe_orderbook(m)
    for adresse, num in subaccounts:
        ws.subscribe_subaccount(adresse, num)
    return {"markets": 1, "marches_trades_book": len(retenus), "subaccounts": len(subaccounts)}


def executer(*, pilote: Any, ws: Any, marches: Sequence[str], subaccounts: Sequence[tuple[str, int]],
             duree_s: float, max_marches: int = MAX_MARCHES_DEFAUT, reprendre: bool = True,
             horloge: Callable[[], float] = time.monotonic,
             dormir: Callable[[float], None] = time.sleep,
             heartbeat_intervalle_s: float = 10.0) -> dict[str, Any]:
    """Session bornée : reprise (backfill) -> souscriptions -> start WS -> boucle (heartbeat de liveness)
    -> stop. Tout est injectable (ws, pilote, horloge, dormir) → testable sans réseau."""
    reprise = pilote.reprendre() if reprendre else {}
    souscrit = plan_souscription(ws, marches=marches, subaccounts=subaccounts, max_marches=max_marches)
    ws.start()
    t0 = horloge()
    dernier_hb = t0
    pilote.battre(0, None)                          # 1er battement : le process vit
    try:
        while horloge() - t0 < duree_s:
            dormir(1.0)
            if horloge() - dernier_hb >= heartbeat_intervalle_s:
                pilote.battre(0, None)              # liveness même si le flux est calme
                dernier_hb = horloge()
    finally:
        ws.stop()
    return {"reprise": reprise, "souscriptions": souscrit,
            "messages": getattr(pilote.stats, "messages", 0),
            "elements_persistes": getattr(pilote.stats, "elements_persistes", 0),
            "gaps": getattr(pilote.stats, "gaps", 0)}


def construire(root: str | Path, *, subaccounts: Sequence[tuple[str, int]]):
    """Construit (config, storage, pilote, ws) réels — LECTURE SEULE. Imports paresseux : le module
    s'importe même sans la lib websocket."""
    from hyper_smart_observer.dydx_v4.config import load_config_from_env
    from hyper_smart_observer.dydx_v4.flux_live import PiloteFluxDydx
    from hyper_smart_observer.dydx_v4.indexer import DydxIndexer
    from hyper_smart_observer.dydx_v4.rest_client import DydxIndexerRestClient
    from hyper_smart_observer.dydx_v4.storage import DydxStorage
    from hyper_smart_observer.dydx_v4.ws_client import DydxIndexerWsClient

    config = load_config_from_env()
    storage = DydxStorage(config.db_path, config.network.value)
    rest = DydxIndexerRestClient(base_url=config.indexer_rest_url)
    indexer = DydxIndexer(config=config, rest_client=rest, storage=storage)
    pilote = PiloteFluxDydx(indexer, network=config.network.value, subaccounts=list(subaccounts),
                            root=str(root), nom=NOM)
    on_message, on_gap = pilote.callbacks()
    ws = DydxIndexerWsClient(config.indexer_ws_url, on_message=on_message, on_gap_detected=on_gap)
    return config, storage, pilote, ws, rest


def _marches_actifs(rest: Any, limite: int) -> list[str]:
    try:
        resp = rest.get_markets()
        marches = list((resp.get("markets", {}) or {}).keys())
        return marches[:limite]
    except Exception:  # noqa: BLE001 — pas de marché = on souscrit au moins le canal markets
        return []


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Collecteur dYdX live (read-only, paper).")
    p.add_argument("--duree-s", type=float, default=290.0)
    p.add_argument("--max-marches", type=int, default=MAX_MARCHES_DEFAUT)
    p.add_argument("--subaccount", action="append", default=[],
                   help="adresse:numero (répétable) — subaccounts à suivre")
    p.add_argument("--racine", default=str(RACINE))
    args = p.parse_args(argv)

    subaccounts: list[tuple[str, int]] = []
    for s in args.subaccount:
        adresse, _, num = str(s).partition(":")
        if adresse:
            subaccounts.append((adresse, int(num or 0)))

    try:
        _config, _storage, pilote, ws, rest = construire(args.racine, subaccounts=subaccounts)
    except Exception as exc:  # noqa: BLE001 — dépendance/endpoint absent : on le DIT (jamais muet)
        print("[dydx-live] indisponible: %s" % exc, flush=True)
        return 0
    marches = _marches_actifs(rest, args.max_marches)
    resume = executer(pilote=pilote, ws=ws, marches=marches, subaccounts=subaccounts,
                      duree_s=args.duree_s, max_marches=args.max_marches)
    print("[dydx-live] session terminee: %s" % resume, flush=True)
    return 0


__all__ = ["NOM", "MAX_MARCHES_DEFAUT", "plan_souscription", "executer", "construire", "main"]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
