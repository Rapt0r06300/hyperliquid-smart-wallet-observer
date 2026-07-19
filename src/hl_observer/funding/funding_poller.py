"""V26 L1 — Poller funding public Hyperliquid (opt-in, read-only).

Interroge périodiquement l'endpoint PUBLIC ``/info`` (``metaAndAssetCtxs``) et pousse
les taux de funding par coin dans ``funding_runtime_cache``. C'est de la collecte
publique en lecture seule (aucune clé, aucune signature, aucun ordre, aucun endpoint
privé) — le carburant des vetos V26, jamais une action de trading.

Opt-in strict : ``HYPERSMART_V26_FUNDING_POLLER=1`` sinon ``ensure_started`` est un no-op
(aucun thread, aucun réseau). Intervalle : ``HYPERSMART_V26_FUNDING_POLL_INTERVAL_S``
(défaut 300 s — le funding HL bouge lentement, inutile de marteler l'API).
Échec réseau/parse ⇒ on ne pousse RIEN (état vide honnête), jamais de donnée fabriquée.
"""

from __future__ import annotations

import json
import os
import threading
import time
from hl_observer.ops.echec_silencieux import noter as _noter_echec

DEFAULT_INFO_URL = "https://api.hyperliquid.xyz/info"
POLLER_FLAG = "HYPERSMART_V26_FUNDING_POLLER"
INTERVAL_ENV = "HYPERSMART_V26_FUNDING_POLL_INTERVAL_S"
URL_ENV = "HYPERSMART_V26_FUNDING_INFO_URL"

_started_lock = threading.Lock()
_started = False


def _flag_on(env: dict | None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get(POLLER_FLAG, "0")).strip().lower() in ("1", "true", "yes", "on")


def parse_meta_and_asset_ctxs(payload: object) -> list[tuple[str, float]]:
    """Extrait [(coin, funding_rate)] du retour public ``metaAndAssetCtxs``.

    Forme attendue : ``[{"universe": [{"name": ...}, ...]}, [{"funding": "..."}, ...]]``.
    Toute forme inattendue ⇒ liste vide (jamais de donnée devinée).
    """
    try:
        meta, ctxs = payload[0], payload[1]  # type: ignore[index]
        universe = meta.get("universe") or []  # type: ignore[union-attr]
        out: list[tuple[str, float]] = []
        for asset, ctx in zip(universe, ctxs):
            name = str((asset or {}).get("name") or "").strip().upper()
            raw = (ctx or {}).get("funding")
            if not name or raw is None:
                continue
            try:
                rate = float(raw)
            except (TypeError, ValueError):
                continue
            if rate != rate or rate in (float("inf"), float("-inf")):
                continue
            out.append((name, rate))
        return out
    except Exception:
        return []


def poll_once(*, url: str | None = None, timeout_s: float = 10.0, opener=None) -> int:
    """Un cycle de poll : fetch public → parse → push cache. Retourne le nb de coins poussés.

    ``opener`` (tests) : callable(url, data, timeout) -> bytes, pour mocker sans réseau.
    Ne lève jamais : tout échec ⇒ 0 push (état vide honnête).
    """
    try:
        target = url or os.environ.get(URL_ENV) or DEFAULT_INFO_URL
        body = json.dumps({"type": "metaAndAssetCtxs"}).encode("utf-8")
        if opener is not None:
            raw = opener(target, body, timeout_s)
        else:  # pragma: no cover — réseau réel, exercé seulement en runtime opt-in
            import urllib.request

            req = urllib.request.Request(
                target, data=body, headers={"Content-Type": "application/json"}, method="POST"
            )
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                raw = resp.read()
        payload = json.loads(raw.decode("utf-8"))
        # ENREGISTREMENT (audit PnL 2026-07-11, opt-in HYPERSMART_RECORD_MICROSTRUCTURE=1).
        # Ce poller recuperait DEJA le funding de TOUS les marches et n'en gardait que le taux
        # courant, en memoire, sans historique. Or l'historique de funding est la seule donnee
        # qui permette de tester la strategie delta-neutre -- une des rares dont l'esperance ne
        # repose sur AUCUNE prediction (le copy-trading, lui, est mesure sans edge : meme a cout
        # zero il perd). On persiste donc ce qu'on tient deja, sans appel reseau supplementaire.
        try:
            from hl_observer.collection import microstructure_recorder as _mr

            if _mr.enabled():
                _base = str(os.environ.get("HYPERSMART_V26_RECORD_PATH", "") or "runtime/replay")
                _mr.record_funding_snapshot(_base, payload)
        except Exception:
            _noter_echec("hl_observer/funding/funding_poller.py:95")
        pairs = parse_meta_and_asset_ctxs(payload)
        if not pairs:
            return 0
        from hl_observer.funding.funding_runtime_cache import push

        now = time.time()
        for coin, rate in pairs:
            push(coin, rate, ts=now)
        return len(pairs)
    except Exception:
        return 0


def _loop(interval_s: float) -> None:  # pragma: no cover — boucle démon runtime
    while True:
        poll_once()
        time.sleep(max(30.0, interval_s))


def ensure_started(env: dict | None = None) -> bool:
    """Démarre le thread démon UNE fois si le flag poller est actif. Sinon no-op.

    Retourne True si le poller tourne (déjà démarré ou démarré maintenant).
    """
    global _started
    if not _flag_on(env):
        return False
    with _started_lock:
        if _started:
            return True
        e = env if env is not None else os.environ
        try:
            interval = float(e.get(INTERVAL_ENV, 300.0) or 300.0)
        except (TypeError, ValueError):
            interval = 300.0
        t = threading.Thread(target=_loop, args=(interval,), daemon=True, name="v26-funding-poller")
        t.start()
        _started = True
        return True


__all__ = [
    "DEFAULT_INFO_URL",
    "POLLER_FLAG",
    "INTERVAL_ENV",
    "URL_ENV",
    "parse_meta_and_asset_ctxs",
    "poll_once",
    "ensure_started",
]
