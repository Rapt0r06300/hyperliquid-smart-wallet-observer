"""PROMOTION DES CANDIDATS OBSERVÉS (rectif Flo 23/07) — augmenter les occasions sans contaminer ALPHA.

Les 6 vaults CANDIDAT_OBSERVE reçoivent leurs fills en WS mais ne TRADENT pas. Ce module les note depuis
le journal de fills (`fills_journal.jsonl`) : FRÉQUENCE (OPEN/h), COPYABILITÉ (part de leurs OPEN sur des
coins de la table PROBE) et RÉSULTAT SHADOW (rendement forward moyen de leurs OPEN, mesuré sur la tape de
prix — sans trader). On PROMEUT les 2 meilleurs qui passent les gates minimums en **mini-PROBE (5-10 $)**.

PUR (lecture de journaux + tape). Écrit `candidats_promus.json`. Aucun ordre, aucune exécution.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from hl_observer.backtesting.copy_vault_protocol import MAX_TARGET_LAG_MS

JOURNAL = Path("runtime") / "data" / "fills_journal.jsonl"
FILLS_LIVE = Path("runtime") / "data" / "vault_fills_live.jsonl"
PROMUS = Path("runtime") / "data" / "candidats_promus.json"
MIN_OPEN = 5                      # au moins 5 OPEN observés pour juger
MIN_COPYABILITE = 0.5            # au moins 50 % des OPEN sur des coins PROBE (pricables)
MIN_SHADOW_NET_BPS = 0.0        # rendement shadow net > 0 pour promouvoir
NOTIONAL_MINI_USD = 7.5         # mini-PROBE : 5-10 $
N_PROMUS = 2
_FULL_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _direction_open(direction: object) -> int | None:
    """Return the signed direction of an explicit leader OPEN."""

    value = str(direction or "").strip().lower()
    if value == "open long":
        return 1
    if value == "open short":
        return -1
    return None


def _fill_key(fill: dict[str, Any]) -> tuple:
    """Stable key preventing one leader fill from being counted once per cohort."""

    return (
        str(fill.get("vault") or ""),
        fill.get("tid"),
        fill.get("hash"),
        fill.get("oid"),
        fill.get("fill_ts_ms") or fill.get("ts_ms") or fill.get("time"),
        str(fill.get("coin") or "").upper(),
        str(fill.get("dir") or ""),
        str(fill.get("sz") or ""),
        str(fill.get("px") or ""),
    )


def _as_ms(value: object) -> int | None:
    try:
        converted = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None
    return converted if converted > 0 else None


def _fill_ts_ms(fill: dict[str, Any]) -> int | None:
    return _as_ms(fill.get("fill_ts_ms") or fill.get("ts_ms") or fill.get("time"))


def _received_at_ms(fill: dict[str, Any]) -> int | None:
    return _as_ms(
        fill.get("received_at_ms") or fill.get("recv_wall_ms") or fill.get("recu_ms")
    )


def _causal_fill_reason(fill: dict[str, Any]) -> str | None:
    """Explain why a fill cannot represent an executable forward observation."""

    if not _FULL_ADDRESS.fullmatch(str(fill.get("vault") or "")):
        return "INVALID_VAULT_ADDRESS"
    if fill.get("source") != "LIVE_WS":
        return "SOURCE_NON_LIVE"
    if fill.get("isSnapshot") is not False:
        return "SNAPSHOT_OR_UNKNOWN"
    event_ms = _fill_ts_ms(fill)
    received_ms = _received_at_ms(fill)
    if event_ms is None or received_ms is None or received_ms < event_ms:
        return "INVALID_CAUSAL_CLOCK"
    if received_ms - event_ms > MAX_TARGET_LAG_MS:
        return "RECEIVE_LAG_TOO_HIGH"
    return None


def _charger_fills_uniques(root: Path) -> list[dict[str, Any]]:
    """Load the causal single-write fill tape, with a compatible journal fallback.

    ``vault_fills_live.jsonl`` is written before cohort fan-out and therefore
    carries one full vault identity per observed fill.  Older journal rows were
    truncated and cohort-multiplied; they remain auditable but are not suitable
    for candidate attribution.
    """

    source = root / FILLS_LIVE
    if not source.exists():
        source = root / JOURNAL
    try:
        lines = source.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    unique: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for line in lines:
        try:
            fill = json.loads(line)
        except ValueError:
            continue
        vault = str(fill.get("vault") or "")
        if not vault:
            continue
        key = _fill_key(fill)
        if key in seen:
            continue
        seen.add(key)
        unique.append(fill)
    return unique


def cibles_prix_shadow(root: str | Path, *, max_evenements: int = 2_500) -> dict[str, list[int]]:
    """Horodatages des OPEN causaux à apparier à la tape de prix réelle.

    Le tri global garde les événements les plus récents lorsque le journal est
    volumineux. Les snapshots, sources non live et fills reçus trop tard ne
    deviennent jamais des cibles économiques.
    """

    events: list[tuple[int, str]] = []
    for fill in _charger_fills_uniques(Path(root)):
        if _direction_open(fill.get("dir")) is None or _causal_fill_reason(fill) is not None:
            continue
        timestamp = _fill_ts_ms(fill)
        coin = str(fill.get("coin") or "").strip().upper()
        if timestamp is not None and coin:
            events.append((timestamp, coin))
    events.sort(reverse=True)
    targets: dict[str, list[int]] = {}
    for timestamp, coin in events[:max(1, int(max_evenements))]:
        targets.setdefault(coin, []).append(timestamp)
    return {coin: sorted(set(values)) for coin, values in targets.items()}


def scorer_candidats(root: str | Path, *, coins_probe: set[str], tape: dict | None = None,
                     candidats_observes: set[str], frais_bps: float = 12.0) -> list[dict]:
    """Note chaque vault CANDIDAT_OBSERVE depuis le journal : n_open, fréquence, copyabilité, shadow net.
    `tape` = {coin: [(ts,px)]} pour le shadow (optionnel). Rend la liste triée par score décroissant."""
    from hl_observer.experimental.copy_edge_forward import rendement_forward
    root = Path(root)
    par: dict[str, dict] = {}
    for d in _charger_fills_uniques(root):
        v = d.get("vault")
        direction = _direction_open(d.get("dir"))
        if not v or v not in candidats_observes or direction is None:
            continue
        e = par.setdefault(
            v,
            {
                "vault": v,
                "n_open_observed": 0,
                "n_open": 0,
                "n_copyables": 0,
                "shadow": [],
                "t0": None,
                "t1": None,
                "causal_rejections": Counter(),
            },
        )
        e["n_open_observed"] += 1
        reason = _causal_fill_reason(d)
        if reason is not None:
            e["causal_rejections"][reason] += 1
            continue
        e["n_open"] += 1
        coin = str(d.get("coin") or "").upper()
        if coin in coins_probe:
            e["n_copyables"] += 1
            serie = (tape or {}).get(coin)
            if serie:
                r = rendement_forward(
                    {
                        "ts_ms": d.get("fill_ts_ms") or d.get("ts_ms") or 0,
                        "direction": direction,
                    },
                    serie,
                    3_600_000.0,
                )
                if r is not None:
                    e["shadow"].append(r - frais_bps)
        ts = _fill_ts_ms(d)
        if ts:
            e["t0"] = ts if e["t0"] is None else min(e["t0"], ts)
            e["t1"] = ts if e["t1"] is None else max(e["t1"], ts)
    out = []
    for e in par.values():
        span_h = ((e["t1"] or 0) - (e["t0"] or 0)) / 3_600_000.0
        copy = e["n_copyables"] / e["n_open"] if e["n_open"] else 0.0
        shadow = sum(e["shadow"]) / len(e["shadow"]) if e["shadow"] else None
        freq = e["n_open"] / span_h if e["n_open"] >= 2 and span_h > 0 else 0.0
        out.append({"vault": e["vault"], "n_open_observed": e["n_open_observed"],
                    "n_open": e["n_open"], "n_shadow": len(e["shadow"]),
                    "causal_rejections": dict(sorted(e["causal_rejections"].items())),
                    "frequence_open_par_h": round(freq, 3), "copyabilite": round(copy, 3),
                    "shadow_net_bps": round(shadow, 2) if shadow is not None else None,
                    "score": round(freq * copy, 4)})
    out.sort(key=lambda x: -x["score"])
    return out


def promouvoir(candidats_scores: list[dict], *, n: int = N_PROMUS) -> dict[str, dict]:
    """Sélectionne les n meilleurs qui passent les gates min (n_open, copyabilité, shadow>0 si mesuré).
    Rend {vault: {notional_usd, raison}} — mini-PROBE. Un candidat sans shadow mesuré n'est PAS promu
    (deny-by-default : on ne promeut que ce qui montre un rendement shadow positif)."""
    promus: dict[str, dict] = {}
    for c in candidats_scores:
        if len(promus) >= n:
            break
        if (c["n_open"] >= MIN_OPEN and c["copyabilite"] >= MIN_COPYABILITE
                and c["shadow_net_bps"] is not None and c["shadow_net_bps"] > MIN_SHADOW_NET_BPS):
            promus[c["vault"]] = {"notional_usd": NOTIONAL_MINI_USD, "shadow_net_bps": c["shadow_net_bps"],
                                  "frequence_open_par_h": c["frequence_open_par_h"], "copyabilite": c["copyabilite"],
                                  "raison": "promu mini-PROBE : fréquence+copyabilité+shadow net>0"}
    return promus


def construire(root: str | Path, *, coins_probe: set[str], tape: dict, candidats_observes: set[str]) -> dict:
    scores = scorer_candidats(root, coins_probe=coins_probe, tape=tape, candidats_observes=candidats_observes)
    promus = promouvoir(scores)
    payload = {"n_candidats": len(scores), "n_promus": len(promus), "promus": promus, "classement": scores}
    (Path(root) / PROMUS).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return payload


PAIRES = Path("runtime") / "data" / "paires_shadow.json"


def scorer_paires(root: str | Path, *, tape: dict, frais_bps: float = 12.0) -> dict[str, dict]:
    """SHADOW PAR PAIRE vault+coin (rectif Flo 23/07), depuis le journal de fills — MÊME hors table.
    Pour chaque OPEN candidat, rendement forward 1 h net de coûts. Une paire au shadow net>0 devient
    éligible à la promotion RAW_PROBE → PROBE. Écrit `paires_shadow.json`."""
    from hl_observer.experimental.copy_edge_forward import rendement_forward
    root = Path(root)
    par: dict[str, dict] = {}
    for d in _charger_fills_uniques(root):
        direction = _direction_open(d.get("dir"))
        if direction is None:
            continue
        vault, coin = d.get("vault"), str(d.get("coin") or "").upper()
        if not vault or not coin:
            continue
        cle = "%s|%s" % (vault, coin)
        e = par.setdefault(
            cle,
            {"paire": cle, "vault": vault, "coin": coin, "n_open_observed": 0,
             "n_open": 0, "shadow": [], "causal_rejections": Counter()},
        )
        e["n_open_observed"] += 1
        reason = _causal_fill_reason(d)
        if reason is not None:
            e["causal_rejections"][reason] += 1
            continue
        e["n_open"] += 1
        serie = (tape or {}).get(coin)
        if serie:
            r = rendement_forward(
                {"ts_ms": d.get("fill_ts_ms") or d.get("ts_ms") or 0, "direction": direction},
                serie,
                3_600_000.0,
            )
            if r is not None:
                e["shadow"].append(r - frais_bps)
    out = {}
    for cle, e in par.items():
        sh = e["shadow"]
        out[cle] = {"paire": cle, "vault": e["vault"], "coin": e["coin"],
                    "n_open_observed": e["n_open_observed"], "n_open": e["n_open"],
                    "causal_rejections": dict(sorted(e["causal_rejections"].items())),
                    "n_shadow": len(sh), "shadow_net_bps": round(sum(sh) / len(sh), 2) if sh else None,
                    "positive": bool(sh and sum(sh) / len(sh) > 0)}
    (root / PAIRES).write_text(json.dumps({"n_paires": len(out), "paires": out}, ensure_ascii=False, indent=1),
                               encoding="utf-8")
    return out


def charger_promus(root: str | Path) -> dict[str, dict]:
    try:
        d = json.loads((Path(root) / PROMUS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): v for k, v in (d.get("promus") or {}).items()}


__all__ = [
    "scorer_candidats",
    "promouvoir",
    "construire",
    "charger_promus",
    "cibles_prix_shadow",
    "NOTIONAL_MINI_USD",
]
