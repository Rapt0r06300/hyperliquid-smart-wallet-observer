"""Certification des flux de contexte : prix allMids, contexte d'actif (funding, OI),
liquidations, overshoots, carnets et dispersion cross-venue.
"""
from __future__ import annotations

from typing import Any

from hl_observer.datasets.coffre_socle import (
    PASS,
    QUARANTAINE,
    REPARE,
    _FUTUR_TOLERANCE_MS,
    _canonical_coin,
    _entier_positif,
    _nombre_fini,
)


def certifier_allmids(record: Any, *, source: str, now_ms: int,
                      ) -> tuple[dict[str, Any] | None, str, str]:
    """Snapshot de prix allMids {ts_ms, mids:{coin:px}}. Replayable si ts causal et au
    moins un mid fini > 0. On garde les mids valides (répare en écartant les non finis)."""
    if not isinstance(record, dict):
        return None, QUARANTAINE, "non_objet"
    ts = _entier_positif(record.get("ts_ms"))
    if ts is None:
        return None, QUARANTAINE, "timestamp_absent"
    if ts > now_ms + _FUTUR_TOLERANCE_MS:
        return None, QUARANTAINE, "timestamp_futur"
    brut = record.get("mids")
    if not isinstance(brut, dict) or not brut:
        return None, QUARANTAINE, "mids_absent"
    mids: dict[str, float] = {}
    for c, v in brut.items():
        px = _nombre_fini(v)
        if px is not None and px > 0:
            mids[str(c)] = px
    if not mids:
        return None, QUARANTAINE, "aucun_mid_valide"
    repare = len(mids) != len(brut)
    out = {"ts_ms": ts, "n": len(mids), "mids": mids,
           "source": str(record.get("source") or source)}
    return out, (REPARE if repare else PASS), ""


def certifier_asset_ctx(record: Any, *, source: str, now_ms: int,
                        ) -> tuple[dict[str, Any] | None, str, str]:
    """Contexte marché (OI/funding/mark/oracle/premium). Replayable si coin, ts causal,
    et au moins mark OU oracle > 0."""
    if not isinstance(record, dict):
        return None, QUARANTAINE, "non_objet"
    out = dict(record)
    coin = _canonical_coin(record.get("coin"))
    if not coin:
        return None, QUARANTAINE, "coin_absent"
    out["coin"] = coin
    ts = _entier_positif(record.get("ts_ms"))
    if ts is None:
        return None, QUARANTAINE, "timestamp_absent"
    if ts > now_ms + _FUTUR_TOLERANCE_MS:
        return None, QUARANTAINE, "timestamp_futur"
    mark = _nombre_fini(record.get("mark"))
    oracle = _nombre_fini(record.get("oracle"))
    if (mark is None or mark <= 0) and (oracle is None or oracle <= 0):
        return None, QUARANTAINE, "ni_mark_ni_oracle"
    out["ts_ms"] = ts
    out["source"] = str(record.get("source") or source)
    return out, PASS, ""


def certifier_liquidation(record: Any, *, source: str, now_ms: int,
                          ) -> tuple[dict[str, Any] | None, str, str]:
    """Liquidation confirmée (événement réel). Replayable si coin, px>0, sz>0, ts causal."""
    if not isinstance(record, dict):
        return None, QUARANTAINE, "non_objet"
    out = dict(record)
    coin = _canonical_coin(record.get("coin"))
    if not coin:
        return None, QUARANTAINE, "coin_absent"
    out["coin"] = coin
    px = _nombre_fini(record.get("px"))
    if px is None or px <= 0:
        return None, QUARANTAINE, "px_invalide"
    sz = _nombre_fini(record.get("sz"))
    if sz is None or sz <= 0:
        return None, QUARANTAINE, "sz_invalide"
    out["px"], out["sz"] = px, sz
    ts = _entier_positif(record.get("ts_ms")) or _entier_positif(record.get("observed_at_ms"))
    if ts is None:
        return None, QUARANTAINE, "timestamp_absent"
    if ts > now_ms + _FUTUR_TOLERANCE_MS:
        return None, QUARANTAINE, "timestamp_futur"
    out["ts_ms"] = ts
    out["source"] = str(record.get("source") or source)
    return out, PASS, ""


def certifier_overshoot(record: Any, *, source: str, now_ms: int,
                        ) -> tuple[dict[str, Any] | None, str, str]:
    """Overshoot de liquidation (mesure oracle↔mid + réversion). Replayable si coin,
    overshoot_bps fini, ts causal. ``ts0`` est en SECONDES -> normalisé en ms."""
    if not isinstance(record, dict):
        return None, QUARANTAINE, "non_objet"
    out = dict(record)
    coin = _canonical_coin(record.get("coin"))
    if not coin:
        return None, QUARANTAINE, "coin_absent"
    out["coin"] = coin
    ov = _nombre_fini(record.get("overshoot_bps"))
    if ov is None:
        return None, QUARANTAINE, "overshoot_bps_absent"
    ts = _entier_positif(record.get("ts_ms"))
    if ts is None:
        ts0 = _nombre_fini(record.get("ts0"))
        ts = int(ts0 * 1000) if (ts0 and ts0 > 0) else None
    if ts is None:
        return None, QUARANTAINE, "timestamp_absent"
    if ts > now_ms + _FUTUR_TOLERANCE_MS:
        return None, QUARANTAINE, "timestamp_futur"
    out["ts_ms"] = ts
    out["overshoot_bps"] = ov
    out["source"] = str(record.get("source") or source)
    return out, PASS, ""


def certifier_venue(record: Any, *, source: str, now_ms: int,
                    ) -> tuple[dict[str, Any] | None, str, str]:
    """Carnet cross-venue (HL vs Binance, top-of-book). Replayable si coin, ts causal,
    et un top-of-book positif d'au moins une venue."""
    if not isinstance(record, dict):
        return None, QUARANTAINE, "non_objet"
    out = dict(record)
    coin = _canonical_coin(record.get("coin"))
    if not coin:
        return None, QUARANTAINE, "coin_absent"
    out["coin"] = coin
    hl = (_nombre_fini(record.get("hl_bid")), _nombre_fini(record.get("hl_ask")))
    bn = (_nombre_fini(record.get("bin_bid")), _nombre_fini(record.get("bin_ask")))
    ok_hl = all(x is not None and x > 0 for x in hl)
    ok_bn = all(x is not None and x > 0 for x in bn)
    if not (ok_hl or ok_bn):
        return None, QUARANTAINE, "aucun_top_of_book_valide"
    ts = _entier_positif(record.get("snapshot_ts_ms")) or _entier_positif(record.get("hl_received_at_ms"))
    if ts is None:
        return None, QUARANTAINE, "timestamp_absent"
    if ts > now_ms + _FUTUR_TOLERANCE_MS:
        return None, QUARANTAINE, "timestamp_futur"
    out["snapshot_ts_ms"] = ts
    out["source"] = str(record.get("source") or source)
    return out, PASS, ""


def certifier_dispersion(record: Any, *, source: str, now_ms: int,
                         ) -> tuple[dict[str, Any] | None, str, str]:
    """Dispersion cross-venue (bps). Replayable si coin, dispersion_bps_h fini, ts causal.
    ``ts`` est en SECONDES -> normalisé en ms."""
    if not isinstance(record, dict):
        return None, QUARANTAINE, "non_objet"
    out = dict(record)
    coin = _canonical_coin(record.get("coin"))
    if not coin:
        return None, QUARANTAINE, "coin_absent"
    out["coin"] = coin
    disp = _nombre_fini(record.get("dispersion_bps_h"))
    if disp is None:
        return None, QUARANTAINE, "dispersion_absente"
    out["dispersion_bps_h"] = disp
    ts = _entier_positif(record.get("ts_ms"))
    if ts is None:
        tss = _nombre_fini(record.get("ts"))
        ts = int(tss * 1000) if (tss and tss > 0) else None
    if ts is None:
        return None, QUARANTAINE, "timestamp_absent"
    if ts > now_ms + _FUTUR_TOLERANCE_MS:
        return None, QUARANTAINE, "timestamp_futur"
    out["ts_ms"] = ts
    out["source"] = str(record.get("source") or source)
    return out, PASS, ""
