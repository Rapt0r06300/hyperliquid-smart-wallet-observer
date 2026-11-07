"""Collecteur causal par poll REST « forward » des fills de leaders.

Casse le plafond WebSocket (~10 userFills/IP de Hyperliquid) en suivant des
leaders SUPPLÉMENTAIRES via le endpoint REST ``info/userFillsByTime`` (non soumis
au cap WS), avec une discipline anti-look-ahead stricte (voir
``hl_observer.collection.forward_poll_fills``) :

- 1re observation d'un leader -> fixe le high-water, n'émet AUCUN fill causal
  (fills préexistants = snapshot) ;
- passes suivantes -> n'émet que les fills strictement nouveaux, estampillés à
  l'instant RÉEL du poll (``observed_at_ms``), source ``LIVE_POLL``.

LECTURE SEULE / PAPER : aucune clé, aucun ordre, aucune signature. Produit un
flux de fills causaux (``source_id = hyperliquid_public_userfills_poll``) que le
pipeline de shards SAFE ingère exactement comme les autres collecteurs ; la
matérialisation les classe ``LIVE_POLL`` (causal, à parité avec ``LIVE_WS``).
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

from hl_observer.collection.forward_poll_fills import (
    LIVE_POLL_SOURCE,
    RESPONSE_PAGE_CAP,
    LeaderWatermark,
    adaptive_interval_s,
    partition_forward_fills,
    shard_leaders,
)

URL_HL = "https://api.hyperliquid.xyz/info"
POLL_SOURCE_ID = "hyperliquid_public_userfills_poll"
RACINE = Path(__file__).resolve().parents[1]
OUT_FILLS = Path("runtime") / "data" / "vault_fills_poll.jsonl"
STATE_PATH = Path("runtime") / "data" / "userfills_poll_watermarks.json"
# Fenêtre d'amorçage à la 1re observation : assez pour fixer un high-water récent
# sans jamais émettre ces fills comme causaux.
BOOTSTRAP_LOOKBACK_MS = 3_600_000  # 1 h


def _post_userfills(vault: str, start_ms: int, end_ms: int, *, timeout_s: float = 10.0) -> Any:
    corps = json.dumps(
        {"type": "userFillsByTime", "user": vault,
         "startTime": int(start_ms), "endTime": int(end_ms)}
    ).encode("utf-8")
    req = urllib.request.Request(URL_HL, data=corps, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:  # noqa: S310 (URL constante)
        return json.loads(rep.read().decode("utf-8"))


def _load_state(path: Path) -> dict[str, LeaderWatermark]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(vault): LeaderWatermark.from_state(state)
        for vault, state in raw.items()
        if isinstance(state, dict)
    }


def _save_state(path: Path, state: dict[str, LeaderWatermark]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {vault: wm.to_state() for vault, wm in state.items()}
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _append_fills(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps({**row, "source_id": POLL_SOURCE_ID}, ensure_ascii=False) + "\n")


def poll_once(
    root: Path,
    leaders: list[str],
    state: dict[str, LeaderWatermark],
    *,
    poster=_post_userfills,
    now_ms: int | None = None,
) -> int:
    """Une passe de poll sur tous les leaders. Renvoie le nombre de fills causaux
    émis. Pur vis-à-vis de l'horloge/HTTP via ``poster``/``now_ms`` (testable)."""
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    emitted = 0
    for vault in leaders:
        wm = state.get(vault, LeaderWatermark())
        start_ms = wm.high_water_ms if wm.initialised else max(1, now_ms - BOOTSTRAP_LOOKBACK_MS)
        try:
            fills = _fetch_all_fills(poster, vault, start_ms, now_ms)
        except Exception as exc:  # noqa: BLE001 (collecteur résilient, fail-soft)
            print(f"[poll] {vault[:10]} erreur {type(exc).__name__}: {str(exc)[:80]}", flush=True)
            continue
        for fill in fills:
            if isinstance(fill, dict):
                fill.setdefault("vault", vault)
        causal, new_wm = partition_forward_fills(wm, fills, observed_at_ms=now_ms)
        state[vault] = new_wm
        _append_fills(root / OUT_FILLS, causal)
        _LAST_FILL_COUNT[vault] = len(causal)
        emitted += len(causal)
    return emitted


#: Nombre de fills causaux émis au dernier poll par leader (pour la cadence adaptative S2).
_LAST_FILL_COUNT: dict[str, int] = {}


def _fetch_all_fills(poster, vault: str, start_ms: int, now_ms: int, *, max_pages: int = 8) -> list[dict[str, Any]]:
    """Solution #1 — pagination complète : si une page atteint le cap de réponse,
    on continue à paginer jusqu'à capturer TOUS les nouveaux fills (aucun perdu).
    La déduplication finale est assurée par le high-water de ``partition_forward_fills``."""
    collected: list[dict[str, Any]] = []
    cursor = int(start_ms)
    for _ in range(max_pages):
        page = poster(vault, cursor, now_ms)
        if not isinstance(page, list) or not page:
            break
        collected.extend(f for f in page if isinstance(f, dict))
        if len(page) < RESPONSE_PAGE_CAP:
            break  # page non pleine -> tout est capturé
        times = [int(f["time"]) for f in page if isinstance(f.get("time"), int) and not isinstance(f.get("time"), bool)]
        if not times:
            break
        nxt = max(times)
        if nxt <= cursor:
            break  # pas de progrès -> on s'arrête (anti-boucle)
        cursor = nxt
    return collected


DEFAULT_LEADERS_FILE = "runtime/data/copy_whitelist.json"


def _extract_vaults(data: Any) -> list[str]:
    """Extrait des adresses de leaders depuis divers formats (robuste, fail-soft)."""
    if isinstance(data, dict):
        for key in ("vaults", "whitelist", "adresses", "addresses", "retenus", "leaders"):
            if key in data:
                return _extract_vaults(data[key])
        # dict {adresse: ...} -> les clés qui ressemblent à une adresse
        return [str(k).strip() for k in data if str(k).strip().lower().startswith("0x")]
    if isinstance(data, list):
        out: list[str] = []
        for item in data:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict):
                for key in ("address", "adresse", "vault", "user", "leader"):
                    val = item.get(key)
                    if isinstance(val, str) and val.strip():
                        out.append(val.strip())
                        break
        return out
    return []


#: Solution #5 — couverture maximale : à défaut de liste explicite, le poll
#: fusionne toutes les sources de leaders disponibles (whitelist prédictive +
#: vaults scorés + vaults suivis) pour suivre le plus de leaders candidats.
_DEFAULT_LEADER_SOURCES = (
    DEFAULT_LEADERS_FILE,
    "runtime/data/vaults_scores.json",
    "runtime/data/vaults_suivis.json",
)


def _lire_fichier_leaders(chemin: Path) -> list[str]:
    try:
        return _extract_vaults(json.loads(chemin.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return []


def _lire_leaders(args: argparse.Namespace, root: Path) -> list[str]:
    if args.leaders:
        vaults = [v.strip() for v in args.leaders.split(",") if v.strip()]
    elif args.leaders_file:
        vaults = _lire_fichier_leaders(root / args.leaders_file)
    else:
        vaults = []
        for src in _DEFAULT_LEADER_SOURCES:
            vaults += _lire_fichier_leaders(root / src)
    # Déduplique en conservant l'ordre, ne garde que des adresses plausibles.
    vus: dict[str, None] = {}
    for v in vaults:
        if v.lower().startswith("0x") and len(v) >= 10:
            vus.setdefault(v, None)
    return list(vus)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Poll causal userFillsByTime (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--leaders", default="", help="liste de vaults séparés par des virgules")
    p.add_argument("--leaders-file", default="", help="JSON {\"vaults\": [...]} relatif à root")
    p.add_argument("--intervalle", type=float, default=5.0, help="cadence de poll de base (s)")
    p.add_argument("--shard-count", type=int, default=1, help="nb de lanes (IP) distinctes")
    p.add_argument("--shard-index", type=int, default=0, help="index de cette lane [0, count)")
    p.add_argument("--une-fois", action="store_true")
    args = p.parse_args(argv)
    root = Path(args.root)
    # S3 : cette lane ne suit qu'une tranche disjointe des leaders.
    leaders = shard_leaders(_lire_leaders(args, root), args.shard_count, args.shard_index)
    if not leaders:
        print("[poll] aucun leader à suivre (voir --leaders / --leaders-file / --shard-*)", flush=True)
        return 0
    state = _load_state(root / STATE_PATH)
    base = max(2.0, float(args.intervalle))
    due_ms: dict[str, float] = {v: 0.0 for v in leaders}
    while True:
        now = time.time() * 1000.0
        # S2 : ne poll que les leaders « dus » ; cadence adaptative à l'activité.
        a_poller = [v for v in leaders if due_ms.get(v, 0.0) <= now]
        emitted = poll_once(root, a_poller, state, now_ms=int(now)) if a_poller else 0
        for v in a_poller:
            interval = adaptive_interval_s(base, _LAST_FILL_COUNT.get(v, 0))
            due_ms[v] = now + interval * 1000.0
        _save_state(root / STATE_PATH, state)
        print(
            f"[poll] {time.strftime('%H:%M:%S')} leaders={len(leaders)} pollés={len(a_poller)} "
            f"fills_causaux_emis={emitted} shard={args.shard_index}/{args.shard_count} source={LIVE_POLL_SOURCE}",
            flush=True,
        )
        if args.une_fois:
            return 0
        time.sleep(min(base, 5.0))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
