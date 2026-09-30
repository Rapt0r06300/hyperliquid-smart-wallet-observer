"""Runtime SL/TP exit pass — disciplined scalping exits at the REAL mark (V9).

Closes a paper position the moment its unrealised PnL (mark-to-market on the real
current price) hits a tight take-profit, a stop-loss, or a trailing stop —
independently of when the leader exits. The goal is the honest "many small wins"
distribution: lock a small gain fast, cut a loss fast.

This is NOT fabrication: the realised PnL is computed at the real current mid
price, exactly the value the engine already shows as unrealised — i.e. what a
real TP/SL order would have captured. It mirrors the engine's own unrealised-PnL
formula so the books stay consistent.

The caller passes the live `positions` dict and `ledger_events` list; this pass
pops closed positions and appends LOCAL_REPLAY exit events (which the engine's
realised-PnL sum and the winning-trades counter then pick up automatically).
SAFETY: read-only / paper-only. No order, no signature, nothing sent anywhere.
"""

from __future__ import annotations
from hl_observer.strategies.strategy_mode import mode_of_position

import os
from typing import Any

from hl_observer.paper_trading.sl_tp import SLTPConfig, evaluate_sl_tp, SLTPDecision, signed_pnl_bps
from hl_observer.simulation.accounting_truth import (
    round_trip_net_pnl_usdc,
    separate_entry_cost_usdc,
)


def _f(name: str, default: float) -> float:
    try:
        v = os.environ.get(name)
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _i(name: str, default: int) -> int:
    try:
        v = os.environ.get(name)
        return int(float(v)) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def sltp_config_from_env() -> SLTPConfig | None:
    """Tight-scalping SL/TP config from env. Returns None when disabled.

    The visible launcher enables a calibrated protective profile. Direct library
    calls remain disabled unless the environment explicitly opts in.
    """
    if str(os.environ.get("HYPERSMART_SLTP_ENABLED", "0")).lower() not in ("1", "true", "yes"):
        return None
    trailing_raw = os.environ.get("HYPERSMART_SLTP_TRAILING_BPS")
    trailing = None if trailing_raw in (None, "", "0") else _f("HYPERSMART_SLTP_TRAILING_BPS", 0.0)
    activation_raw = os.environ.get("HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS")
    activation = None if activation_raw in (None, "", "0") else _f("HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS", 0.0)
    # 🔴 2026-07-13 — LE DEFAUT DU CODE ETAIT UNE PERTE GARANTIE.
    #
    #   AVANT : TP=30, SL=40, cout=12  ->  breakeven = (40+12)/(30+40) = 52/70  = 74 %
    #   APRES : TP=110, SL=60, cout=12 ->  breakeven = (60+12)/(110+60) = 72/170 = 42 %
    #
    # Un winrate d'equilibre de 74 % est hors d'atteinte : ce reglage PERD, par arithmetique.
    # La production n'etait sauvee que parce que le LANCEUR ecrase ces valeurs (110/60). Mais
    # « le lanceur corrige le code » est exactement le motif qui nous a deja coute le poller L2
    # et le funding : le jour ou le flag disparait, on retombe en silence sur une config perdante.
    #
    # C'est le garde-fou breakeven (T3c) qui a rendu la chose VISIBLE : il refusait 100 % des
    # entrees des que l'env n'etait pas pose -- et deux tests UI le criaient depuis la suite
    # complete. Le garde-fou avait raison ; c'est le DEFAUT qu'il fallait corriger, pas lui.
    #
    # La production ne change PAS (le lanceur posait deja 110/60). Seul le defaut devient honnete.
    return SLTPConfig(
        take_profit_bps=_f("HYPERSMART_SLTP_TAKE_PROFIT_BPS", 110.0),  # +1.10%  (= lanceur)
        stop_loss_bps=_f("HYPERSMART_SLTP_STOP_LOSS_BPS", 60.0),       # -0.60%  (= lanceur)
        trailing_stop_bps=trailing,
        trailing_activation_bps=activation,
        breakeven_buffer_bps=_f("HYPERSMART_SLTP_BREAKEVEN_BUFFER_BPS", 8.0),
    )


def apply_sltp_exits(
    positions: dict[Any, dict[str, Any]],
    ledger_events: list[dict[str, Any]],
    mid_prices: dict[str, float] | None,
    *,
    cost_bps: float = 12.0,
    now_ms: int = 0,
    config: SLTPConfig | None = None,
    paper_mode: str = "PAPER_LOCAL_USDT_ONLY",
) -> list[dict[str, Any]]:
    """Close TP/SL/trailing-hit positions at the real mark. Mutates inputs."""
    if config is None or not positions:
        return []
    marks = mid_prices or {}
    stop_min_hold_ms = max(0, _i("HYPERSMART_SLTP_STOP_MIN_HOLD_MS", 0))
    catastrophic_stop_bps = abs(_f("HYPERSMART_SLTP_CATASTROPHIC_STOP_BPS", max(float(config.stop_loss_bps), 0.0)))
    # 0 = desactive (comportement historique). Le launcher pose 1 800 000 ms (30 min).
    position_timeout_ms = max(0, _i("HYPERSMART_SLTP_POSITION_TIMEOUT_MS", 0))
    closed: list[dict[str, Any]] = []
    for key in list(positions.keys()):
        position = positions.get(key)
        if not position:
            continue
        identity = _position_identity(key, position)
        if identity is None:
            continue
        wallet, coin, direction = identity
        raw_size = float(position.get("size") or 0.0)
        size = abs(raw_size)
        avg = float(position.get("avg_price") or 0.0)
        if size <= 0 or avg <= 0:
            continue
        mark_price = marks.get(coin)
        if mark_price is None or float(mark_price) <= 0:
            continue
        mark_price = float(mark_price)
        side = str(direction).upper()
        if side == "LONG":
            peak = max(float(position.get("highest_price") or avg), mark_price)
            position["highest_price"] = peak
            position["lowest_price"] = min(float(position.get("lowest_price") or avg), mark_price)
        else:
            peak = min(float(position.get("lowest_price") or avg), mark_price)
            position["lowest_price"] = peak
            position["highest_price"] = max(float(position.get("highest_price") or avg), mark_price)
        decision = evaluate_sl_tp(side=side, entry_price=avg, current_price=mark_price, peak_price=peak, config=config)

        # INCOHERENCE CORRIGEE (autopsie PnL 2026-07-11) — AUCUN TIMEOUT DE POSITION.
        # Le bot DECIDE sur un horizon de quelques minutes (take-profit a ~28 bps) mais TENAIT
        # ses positions 1,3 h en mediane, jusqu'a 8,4 h. Or l'edge du signal de copie est mesure
        # NUL des 5 minutes : au-dela, on n'a plus une position de copie, on a une exposition
        # nue au marche. C'est ce qui a tue les shorts (9 SL sur 10 etaient des shorts dans un
        # marche haussier). Un scalp qui dure 8 heures n'est plus un scalp.
        # Rejeu sur les 20 trades reels : sans timeout -39 $, avec timeout 30 min -23 $.
        # (cela ne CREE pas d'edge -- cela cesse d'exposer le capital a un actif qui n'en a pas)
        if position_timeout_ms > 0 and not decision.exit:
            _opened = int(float(position.get("opened_at_ms") or 0))
            if _opened > 0 and now_ms and (int(now_ms) - _opened) >= position_timeout_ms:
                _pnl_now = signed_pnl_bps(side, avg, mark_price)
                decision = SLTPDecision(True, "TIMEOUT", round(_pnl_now, 6),
                                        round(decision.favorable_excursion_bps, 6))

        # BUG CORRIGE (autopsie PnL 2026-07-11) — LE STOP CATASTROPHIQUE NE FERMAIT RIEN.
        # `catastrophic_stop_bps` n'etait utilise que pour CONTOURNER le delai minimum de detention
        # (voir plus bas). Il ne declenchait AUCUNE sortie. Resultat mesure : quand la volatilite
        # gonflait le SL a 315 bps, la perte courait jusqu'a -323 bps alors que le "stop
        # catastrophique" affichait 180. Les 2 trades concernes (ARB, ZEC) pesent 46 % de TOUTE
        # la perte du run. C'est maintenant un VRAI plafond de perte, absolu, non redimensionne
        # par la volatilite : au-dela, on ferme, point.
        if catastrophic_stop_bps > 0 and not decision.exit:
            _pnl_now = signed_pnl_bps(side, avg, mark_price)
            if _pnl_now <= -catastrophic_stop_bps:
                decision = SLTPDecision(True, "CATASTROPHIC_STOP", round(_pnl_now, 6), round(decision.favorable_excursion_bps, 6))

        if decision.hold:
            continue
        opened_at_ms = int(float(position.get("opened_at_ms") or 0))
        age_ms = max(0, int(now_ms or 0) - opened_at_ms) if opened_at_ms > 0 and now_ms else 0
        if (
            decision.reason == "STOP_LOSS"          # jamais CATASTROPHIC_STOP : lui passe toujours
            and stop_min_hold_ms > 0
            and age_ms < stop_min_hold_ms
            and abs(float(decision.pnl_bps)) < catastrophic_stop_bps
        ):
            position["last_sltp_hold_reason"] = "STOP_LOSS_MIN_HOLD_NOT_REACHED"
            position["last_sltp_pnl_bps"] = round(decision.pnl_bps, 6)
            position["last_sltp_age_ms"] = age_ms
            continue
        position_notional = abs(size * mark_price)
        gross = (mark_price - avg) * size if side == "LONG" else (avg - mark_price) * size
        exit_cost = position_notional * cost_bps / 10_000.0

        # COUT MANQUANT (autopsie PnL 2026-07-11) — LE FUNDING N'ETAIT JAMAIS FACTURE.
        # Sur Hyperliquid le financement se paie CHAQUE HEURE. Le run a cumule 42,6 heures de
        # positions ouvertes (une seule tenue 8,4 h) sans qu'un seul centime de funding ne soit
        # deduit du PnL. Un LONG paie quand le funding est positif ; un SHORT recoit.
        # Sans donnee de funding fraiche pour ce coin -> on ne facture RIEN (jamais de chiffre
        # invente), et on le DIT dans l'evenement (`funding_cost_usdc: None`).
        funding_cost = None
        try:
            from hl_observer.funding.funding_runtime_cache import recent_rates as _recent

            _rates = _recent(coin, window_s=6 * 3600.0)      # taux HORAIRES signes, recents
            if _rates:
                _rate = sum(_rates) / len(_rates)            # taux moyen sur la vie de la position
                _hours = max(0.0, age_ms / 3_600_000.0)
                _sign = 1.0 if side == "LONG" else -1.0      # le LONG paie un funding positif
                funding_cost = position_notional * float(_rate) * _hours * _sign
        except Exception:
            funding_cost = None

        entry_cost = separate_entry_cost_usdc(position)
        net = round_trip_net_pnl_usdc(
            gross_pnl_usdc=gross,
            entry_cost_usdc=entry_cost,
            exit_cost_usdc=exit_cost,
            # Funding is reported separately when it is unavailable. The
            # strict entry/exit accounting remains measurable, while the
            # completeness flag below prevents calling it fully cost-complete.
            funding_cost_usdc=funding_cost if funding_cost is not None else 0.0,
        )
        if net is None:
            # The protective exit still removes paper exposure, but an
            # unmeasurable round trip is never inserted into realized PnL.
            net_status = "ENTRY_COST_UNMEASURABLE"
        elif funding_cost is None:
            net_status = "ENTRY_EXIT_COSTS_KNOWN_FUNDING_UNMEASURABLE"
        else:
            net_status = "STRICT_ALL_COSTS_KNOWN"
        matched_position_key = f"{wallet}|{coin}|{side}"
        instance_id = _paper_position_instance_id(
            matched_position_key=matched_position_key,
            position=position,
            avg_price=avg,
            size=size,
        )
        if _already_has_full_close(
            ledger_events,
            matched_position_key=matched_position_key,
            instance_id=instance_id,
            source_delta_key=position.get("source_delta_key"),
            avg_price=avg,
            size=size,
        ):
            positions.pop(key, None)
            closed.append(
                {
                    "coin": coin,
                    "side": side,
                    "reason": "DUPLICATE_SLTP_CLOSE_ALREADY_RECORDED",
                    "net_pnl_usdc": 0.0,
                    "matched_position_key": matched_position_key,
                    "source_delta_key": position.get("source_delta_key"),
                    "paper_position_instance_id": instance_id,
                    "duplicate_close_ignored": True,
                }
            )
            continue
        ledger_events.append(
            {
                "coin": coin,
                "leader_side": side,
                "matched_position_key": matched_position_key,
                "paper_position_instance_id": instance_id,
                "source_delta_key": position.get("source_delta_key"),
                "opened_at_ms": opened_at_ms,
                "status": "LOCAL_REPLAY",
                "bot_replay_action": "PAPER_CLOSE_REPLAYED",
                # la sortie HERITE du moteur de l'entree -- on ne reclasse jamais sur le motif
                "strategy_mode": mode_of_position(position),
                "paper_action_type": "CLOSE",
                "exit_method": "SLTP_" + decision.reason,
                "reason": "SLTP_" + decision.reason + "_LOCAL_REPLAY_NOT_AN_ORDER",
                "estimated_net_pnl_usdc": round(net, 6) if net is not None else None,
                "gross_pnl_usdc": round(gross, 6),
                "fee_cost_usdc": round(exit_cost, 6),
                "entry_cost_carried_usdc": round(entry_cost, 8) if entry_cost is not None else None,
                "total_round_trip_cost_usdc": (
                    round(entry_cost + exit_cost, 8) if entry_cost is not None else None
                ),
                "pnl_accounting_status": net_status,
                "pnl_strict": net_status == "STRICT_ALL_COSTS_KNOWN",
                "fee_already_embedded_in_entry_price": bool(
                    position.get("fee_already_embedded_in_entry_price") is True
                ),
                "fee_already_embedded_in_exit_price": False,
                # None = pas de donnee de funding pour ce coin (on n'invente pas un chiffre)
                "funding_cost_usdc": (round(funding_cost, 8) if funding_cost is not None else None),
                "funding_hours": round(age_ms / 3_600_000.0, 4),
                "average_entry_price": round(avg, 8),
                "exit_price": round(mark_price, 8),
                "notional_closed_usdt": round(position_notional, 6),
                "sltp_pnl_bps": round(decision.pnl_bps, 6),
                "sltp_favorable_excursion_bps": round(decision.favorable_excursion_bps, 6),
                "sltp_take_profit_bps": round(float(config.take_profit_bps), 6),
                "sltp_stop_loss_bps": round(float(config.stop_loss_bps), 6),
                "sltp_trailing_stop_bps": (
                    round(float(config.trailing_stop_bps), 6)
                    if config.trailing_stop_bps is not None
                    else None
                ),
                "sltp_trailing_activation_bps": (
                    round(float(config.trailing_activation_bps), 6)
                    if config.trailing_activation_bps is not None
                    else None
                ),
                "sltp_breakeven_buffer_bps": round(float(config.breakeven_buffer_bps), 6),
                "sltp_position_age_ms": age_ms,
                "sltp_stop_min_hold_ms": stop_min_hold_ms,
                "sltp_catastrophic_stop_bps": round(catastrophic_stop_bps, 6),
                "bot_position_size_after": 0.0,
                "size_before": round(size, 10),
                "size_closed": round(size, 10),
                "size_after": 0.0,
                "reduce_fraction": 1.0,
                "research_only": True,
                "paper_mode": paper_mode,
                "observed_at_ms": int(now_ms),
            }
        )
        positions.pop(key, None)
        closed.append(
            {
                "coin": coin,
                "side": side,
                "reason": decision.reason,
                "net_pnl_usdc": round(net, 6) if net is not None else None,
                "matched_position_key": matched_position_key,
                "source_delta_key": position.get("source_delta_key"),
                "paper_position_instance_id": instance_id,
            }
        )
    return closed


def _position_identity(key: object, position: dict[str, Any]) -> tuple[str, str, str] | None:
    """Resolve tuple keys and the newer ``wallet|coin|side`` string keys.

    The original replay path used tuple keys. The fast live simulation stores
    positions with string keys, so TP/SL silently skipped them before this
    helper. Keeping both forms avoids a migration and preserves old tests.
    """

    if isinstance(key, tuple) and len(key) == 3:
        wallet, coin, direction = key
        return str(wallet), str(coin).upper(), str(direction).upper()
    if isinstance(key, str):
        parts = key.split("|")
        if len(parts) >= 3:
            wallet, coin, direction = parts[0], parts[1], parts[2]
            return str(wallet), str(coin).upper(), str(direction).upper()
    coin = str(position.get("coin") or "").upper()
    direction = str(position.get("side") or position.get("direction") or "").upper()
    wallet = str(position.get("wallet_address") or position.get("leader_wallet") or "")
    if coin and direction in {"LONG", "SHORT"}:
        return wallet, coin, direction
    return None


def _paper_position_instance_id(
    *,
    matched_position_key: str,
    position: dict[str, Any],
    avg_price: float,
    size: float,
) -> str:
    """Stable identity for one local paper position lifetime.

    The live status endpoint can be called every second and may receive a stale
    copy of a just-closed position from another path. Without a stable identity,
    the same paper position can be closed twice and inflate PnL. The preferred
    key is the source delta; otherwise we fall back to open time plus entry/size,
    then to entry/size only for older in-memory positions.
    """

    source = str(
        position.get("source_delta_key")
        or position.get("last_paper_ref")
        or position.get("last_evidence_hash")
        or ""
    ).strip()
    if source:
        return f"{matched_position_key}|src:{source}"
    opened_at_ms = _safe_int(
        position.get("opened_at_ms")
        or position.get("created_at_ms")
        or position.get("observed_at_ms")
        or position.get("entry_observed_at_ms")
    )
    if opened_at_ms:
        return f"{matched_position_key}|opened:{opened_at_ms}|entry:{avg_price:.12g}|size:{size:.12g}"
    return f"{matched_position_key}|entry:{avg_price:.12g}|size:{size:.12g}"


def _already_has_full_close(
    ledger_events: list[dict[str, Any]],
    *,
    matched_position_key: str,
    instance_id: str,
    source_delta_key: object,
    avg_price: float,
    size: float,
) -> bool:
    source = str(source_delta_key or "").strip()
    fallback_identity = f"{matched_position_key}|entry:{avg_price:.12g}|size:{size:.12g}"
    for row in ledger_events:
        if not isinstance(row, dict):
            continue
        action_blob = f"{row.get('paper_action_type') or ''} {row.get('bot_replay_action') or ''}".upper()
        if "CLOSE" not in action_blob and "TAKE_PROFIT" not in action_blob and "STOP_LOSS" not in action_blob:
            continue
        if str(row.get("matched_position_key") or "") != matched_position_key:
            continue
        existing_instance = str(row.get("paper_position_instance_id") or "").strip()
        if existing_instance and existing_instance == instance_id:
            return True
        existing_source = str(row.get("source_delta_key") or row.get("delta_key") or "").strip()
        if source and existing_source == source:
            return True
        if not source and not existing_instance:
            existing_entry = _safe_float(row.get("entry_price") or row.get("average_entry_price"))
            existing_size = _safe_float(row.get("size_closed") or row.get("size_before"))
            if existing_entry is None:
                existing_entry = avg_price
            if existing_size is None:
                existing_size = size
            existing_fallback = f"{matched_position_key}|entry:{existing_entry:.12g}|size:{abs(existing_size):.12g}"
            if existing_fallback == fallback_identity:
                return True
    return False


def _safe_int(value: object) -> int | None:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _safe_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["sltp_config_from_env", "apply_sltp_exits"]
