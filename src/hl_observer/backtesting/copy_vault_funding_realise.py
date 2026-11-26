"""Measure post-trade hourly carry from verified funding-history rows.

The reader rejects unbounded or non-admissible shards, verifies selected shard hashes, and
requires a rate in every hourly settlement bucket crossed by a position. Missing rates and exact
fill/settlement timestamp ambiguity remain ``UNMEASURABLE``; absent data is never treated as zero.

Rows marked ``LOCAL_CERTIFIED`` support exploratory diagnostics only. They cannot support
economic proof. Even a ``SAFE`` rate shard is not enough: proof also requires the follower's
point-in-time settlement quantity and oracle price. Until those are joined, rate x entry notional
is estimate-only and crossed settlements are refused by the execution gate. REST funding history
is post-trade evidence, never a signal or execution input; provenance remains visible on receipts.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

from hl_observer.economics.numeric import decimal_sum, decimal_value, float_not_above
from hl_observer.funding.funding_times import next_funding_time_ms

#: La famille du coffre qui porte les taux de funding regles.
FAMILLE_FUNDING = "funding_history"

#: L'intervalle de reglement d'Hyperliquid. Le coffre le porte ligne par ligne (`interval`), et on
#: REFUSE toute ligne qui annonce autre chose plutot que de supposer : un intervalle different
#: changerait le nombre de reglements traverses, donc le cout.
INTERVALLE_ATTENDU = "1h"
INTERVALLE_MS = 3_600_000

#: Ce que vaut la provenance des taux, dit une fois pour toutes.
PROVENANCE_RECONSTITUEE = "REST_FUNDING_HISTORY_RECONSTITUEE"


class _ValidatedFundingSeries(Sequence[tuple[int, Decimal]]):
    """Compact immutable view of one sorted, finite funding series.

    Validation happens once when the coffre is read. Re-validating tens of
    thousands of rates for every trade would erase the benefit of binary search.
    """

    __slots__ = ("_rows",)

    def __init__(self, rows: Iterable[tuple[int, Decimal]]) -> None:
        normalized: list[tuple[int, Decimal]] = []
        previous = -1
        for point in rows:
            if not isinstance(point, (tuple, list)) or len(point) != 2:
                raise ValueError("invalid funding point")
            instant, value = point
            if isinstance(instant, bool) or not isinstance(instant, int) or instant <= previous:
                raise ValueError("funding timestamps must be non-negative and strictly increasing")
            if isinstance(value, bool) or value is None:
                raise ValueError("invalid funding rate")
            try:
                rate = Decimal(str(value))
            except (TypeError, ValueError, ArithmeticError) as exc:
                raise ValueError("invalid funding rate") from exc
            if not rate.is_finite():
                raise ValueError("funding rate must be finite")
            normalized.append((instant, rate))
            previous = instant
        if not normalized:
            raise ValueError("funding series must not be empty")
        self._rows = tuple(normalized)

    def __getitem__(self, index):
        return self._rows[index]

    def __len__(self) -> int:
        return len(self._rows)


def _validated_funding_series(
    rows: Sequence[tuple[int, Decimal]],
) -> _ValidatedFundingSeries | None:
    if isinstance(rows, _ValidatedFundingSeries):
        return rows
    try:
        return _ValidatedFundingSeries(rows)
    except (TypeError, ValueError, ArithmeticError):
        return None


def taux_du_coffre(
    racine: str | Path,
    *,
    coins: Sequence[str] | None,
    debut_ms: int,
    fin_ms: int,
) -> tuple[dict[str, Sequence[tuple[int, Decimal]]], dict[str, Any]]:
    """Les reglements de funding du coffre, par coin, tries par instant.

    Rend aussi un audit : sans le couple « lu / garde », un dictionnaire vide ne se distingue pas
    d'une lecture qui n'a rien trouve a lire.
    """
    import json

    from hl_observer.backtesting import coffre_tranches

    racine = Path(racine)
    index = racine / "runtime/coffre_certifie/LOCAL_INDEX.json"
    if not index.exists():
        return {}, {"status": "COFFRE_ABSENT", "chemin": str(index)}

    brut = json.loads(index.read_text(encoding="utf-8"))
    tous = brut.get("shards") or brut.get("entrees") or []
    if isinstance(tous, dict):
        tous = list(tous.values())
    choix = coffre_tranches.selectionner(
        tous, famille=FAMILLE_FUNDING,
        coins=list(coins) if coins else None,
        debut_ms=int(debut_ms), fin_ms=int(fin_ms))
    sans_bornes = choix.get("sans_bornes") or []
    if sans_bornes:
        # A shard without time bounds may overlap the requested interval. Ignoring it could
        # omit a settlement while leaving the remaining hourly rates looking complete.
        return {}, {
            "status": "SHARDS_SANS_BORNES",
            "shards": len(choix.get("shards") or choix.get("retenus") or []),
            "shards_sans_bornes": len(sans_bornes),
            "economic_proof_allowed": False,
            "shards_non_verifiables": [
                str(shard.get("shard") or shard.get("path") or "UNKNOWN")
                for shard in sans_bornes
                if isinstance(shard, Mapping)
            ],
        }
    shards = choix.get("shards") or choix.get("retenus") or []
    if not shards:
        return {}, {
            "status": "AUCUN_SHARD_DE_FUNDING",
            "shards": 0,
            "economic_proof_allowed": False,
        }

    quality_counts: dict[str, int] = {}
    inadmissible = []
    safe_replay_admissible = True
    for shard in shards:
        quality = str(shard.get("quality_status") or "UNKNOWN").strip().upper()
        quality_counts[quality] = quality_counts.get(quality, 0) + 1
        if quality not in {"SAFE", "LOCAL_CERTIFIED"}:
            inadmissible.append(str(shard.get("shard") or "UNKNOWN"))
        if not (
            quality == "SAFE"
            and shard.get("replay_compatible") is True
            and shard.get("validation_allowed") is True
            and shard.get("asset_verified") is True
        ):
            safe_replay_admissible = False
    if inadmissible:
        return {}, {
            "status": "SHARDS_QUALITY_NOT_ADMISSIBLE",
            "shards": len(shards),
            "quality_status_counts": quality_counts,
            "economic_proof_allowed": False,
            "shards_refuses": inadmissible,
        }

    from hl_observer.datasets.coffre_certifie import ORIGINE_EXTERNE

    # 23/11/2026 -- UN SEUL RÈGLEMENT PAR COIN ET PAR HEURE. Le coffre dédoublonne ruban par ruban, pas entre
    # sources : le même règlement, publié par Alina ET par une source externe (Ironflow), y figure deux fois,
    # et les additionner doublerait le coût de portage sans que rien ne le dise. Alina est prioritaire ; un
    # doublon est compté, et un doublon de VALEUR différente l'est à part (deux sources qui se contredisent).
    par_heure: dict[str, dict[int, tuple[int, Decimal, bool]]] = {}
    doublons = doublons_contradictoires = externes_gardes = 0
    lus = gardes = intervalle_inattendu = taux_illisible = 0
    compteurs_flux: dict[str, Any] = {}
    for ligne in coffre_tranches.flux(
        racine, shards, famille=FAMILLE_FUNDING,
        coins=list(coins) if coins else None,
        debut_ms=int(debut_ms), fin_ms=int(fin_ms), verifier_sha=True,
        compteurs=compteurs_flux,
    ):
        lus += 1
        coin = str(ligne.get("coin") or ligne.get("symbole") or "")
        if not coin:
            continue
        if str(ligne.get("interval") or "").strip().lower() != INTERVALLE_ATTENDU:
            # On ne devine pas un intervalle : un reglement toutes les huit heures au lieu d'une
            # heure diviserait le cout par huit, silencieusement.
            intervalle_inattendu += 1
            continue
        valeur = ligne.get("funding")
        try:
            if isinstance(valeur, bool) or valeur is None:
                raise TypeError(valeur)
            taux = Decimal(str(valeur))
        except (TypeError, ValueError, ArithmeticError):
            taux_illisible += 1
            continue
        if not taux.is_finite():
            taux_illisible += 1
            continue
        instant = ligne.get("ts_ms")
        if isinstance(instant, bool):
            taux_illisible += 1
            continue
        if isinstance(instant, int):
            instant_ms = instant
        elif isinstance(instant, float) and math.isfinite(instant) and instant.is_integer():
            instant_ms = int(instant)
        else:
            taux_illisible += 1
            continue
        if instant_ms <= 0:
            taux_illisible += 1
            continue
        externe = ligne.get("data_origin") == ORIGINE_EXTERNE
        heure = (instant_ms + 1_800_000) // 3_600_000          # l'heure la plus proche : un règlement tombe à H + quelques ms
        deja = par_heure.setdefault(coin, {}).get(heure)
        if deja is not None:
            doublons += 1
            if deja[1] != taux:
                doublons_contradictoires += 1
            if not (deja[2] and not externe):
                continue                                          # garde l'existant, sauf externe remplacé par Alina
        par_heure[coin][heure] = (instant_ms, taux, externe)
    shards_refuses = list(compteurs_flux.get("shards_refuses") or [])
    if shards_refuses:
        # Une couverture partielle peut sous-estimer les règlements et donc embellir le PnL.
        # Ne garder aucun taux si un shard sélectionné manque, échoue à la lecture ou ne passe
        # pas son SHA : l'appelant recevra un état explicitement non mesurable.
        return {}, {
            "status": "SHARDS_REFUSES",
            "shards": len(shards),
            "shards_lus": compteurs_flux.get("shards_lus", 0),
            "shards_refuses": shards_refuses,
            "lignes_lues": lus,
            "provenance": PROVENANCE_RECONSTITUEE,
            "quality_status_counts": quality_counts,
            "economic_proof_allowed": False,
        }
    par_coin: dict[str, Sequence[tuple[int, Decimal]]] = {}
    for coin, heures in par_heure.items():
        rows = sorted(((instant, taux) for instant, taux, _ in heures.values()), key=lambda c: c[0])
        par_coin[coin] = _ValidatedFundingSeries(rows)
        externes_gardes += sum(1 for *_, ext in heures.values() if ext)
    gardes = sum(len(serie) for serie in par_coin.values())
    audit = {
        "status": "LU_DEPUIS_LE_COFFRE",
        "shards": len(shards),
        "lignes_lues": lus,
        "reglements_gardes": gardes,
        "coins": len(par_coin),
        "ecartes_intervalle_inattendu": intervalle_inattendu,
        "ecartes_taux_illisible": taux_illisible,
        "doublons_horaires_ecartes": doublons,
        "doublons_de_valeur_differente": doublons_contradictoires,
        "reglements_externes_gardes": externes_gardes,
        "provenance": PROVENANCE_RECONSTITUEE,
        "quality_status_counts": quality_counts,
        "evidence_admission": (
            "SAFE_REPLAY_ADMISSIBLE"
            if safe_replay_admissible
            else (
                "LOCAL_CERTIFIED_EXPLORATORY_ONLY"
                if set(quality_counts) == {"LOCAL_CERTIFIED"}
                else "NOT_FULLY_SAFE_EXPLORATORY_ONLY"
            )
        ),
        # This loader returns funding rates only. It does not join the follower's
        # point-in-time position quantity and oracle price at each settlement, so a
        # rate x entry-notional calculation cannot certify settlement PnL.
        "settlement_oracle_bound": False,
        "settlement_valuation_basis": "ENTRY_NOTIONAL_RATE_PROXY",
        "economic_proof_allowed": False,
        "economic_proof_block_reason": "SETTLEMENT_ORACLE_PRICE_NOT_JOINED",
    }
    return par_coin, audit


def _reglements_traverses(
    serie: Sequence[tuple[int, Decimal]], debut_ms: int, fin_ms: int
) -> list[tuple[int, Decimal]]:
    """Les reglements strictement APRES l'entree et au plus tard a la sortie.

    Un reglement a l'instant exact de l'entree n'est pas paye par une position ouverte juste
    apres ; un reglement a l'instant de la sortie l'est, puisqu'on detient encore. La borne
    choisie est donc `(debut, fin]`, et elle est verrouillee par un test -- une borne qui glisse
    d'un reglement, c'est un cout qui change sans que rien ne le dise.
    """
    # Search the sorted rows directly. Building a full timestamp list for every trade
    # made this O(series length) in both time and transient RAM before the binary search.
    premier = bisect.bisect_right(serie, int(debut_ms), key=lambda row: row[0])
    dernier = bisect.bisect_right(serie, int(fin_ms), key=lambda row: row[0])
    return list(serie[premier:dernier])


def funding_du_trade(
    trade: Mapping[str, Any],
    taux_par_coin: Mapping[str, Sequence[tuple[int, Decimal]]],
    *,
    couverture_ms: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """
Estimate the funding cashflow from entry notional and observed settlement rates.

This is diagnostic only: exact settlement PnL requires the point-in-time follower position quantity and oracle price at every settlement. Crossed settlements therefore return ESTIMATED and never populate the certified carry fields. Positive rates make longs pay and shorts receive; invalid or incomplete evidence remains UNMEASURABLE.
    """
    coin = str(trade.get("coin") or "")
    entree = trade.get("entry_ts_ms")
    sortie = trade.get("exit_ts_ms")
    notionnel = trade.get("notional_usd", trade.get("entry_notional_usd"))
    direction = trade.get("direction")
    manque = (
        isinstance(entree, bool) or not isinstance(entree, int) or entree <= 0
        or isinstance(sortie, bool) or not isinstance(sortie, int) or sortie <= entree
    )
    if manque:
        return _inconnu("FUNDING_TRADE_TIMESTAMPS_UNMEASURABLE", coin)
    if couverture_ms is not None and (
        not isinstance(couverture_ms, (tuple, list))
        or len(couverture_ms) != 2
        or any(isinstance(value, bool) or not isinstance(value, int) for value in couverture_ms)
        or couverture_ms[0] < 0
        or couverture_ms[1] < couverture_ms[0]
    ):
        return _inconnu("FUNDING_COVERAGE_UNMEASURABLE", coin)
    if couverture_ms is not None and (entree < couverture_ms[0] or sortie > couverture_ms[1]):
        return _inconnu("FUNDING_RATES_DO_NOT_COVER_EPISODE", coin)

    # Exact boundary timestamps do not establish whether the paper position was open at
    # settlement. Match the executable gate: reject either ambiguous edge rather than
    # accidentally turning an unpriced settlement into zero carry.
    try:
        first_possible = next_funding_time_ms(entree - 1, interval_hours=1)
        last_possible = next_funding_time_ms(sortie - 1, interval_hours=1)
    except (TypeError, ValueError, ArithmeticError):
        return _inconnu("FUNDING_SETTLEMENT_RULE_UNMEASURABLE", coin)
    if first_possible == entree or last_possible == sortie:
        return _inconnu("FUNDING_BOUNDARY_UNPRICED", coin)

    expected_settlements: list[int] = []
    settlement_ms = next_funding_time_ms(entree, interval_hours=1)
    while settlement_ms <= sortie:
        expected_settlements.append(settlement_ms)
        settlement_ms += INTERVALLE_MS

    # No settlement crossed is a measured zero from the known hourly schedule; it does not
    # require a rate series for a coin that had no funding event during this position.
    if not expected_settlements:
        return {
            "status": "MEASURED",
            "coin": coin,
            "carry_pnl_usd": 0.0,
            "carry_pnl_usd_exact_decimal": "0",
            "settlement_crossing_count": 0,
            "settlement_interval_hours": 1,
            "provenance": PROVENANCE_RECONSTITUEE,
            "reason": "NO_SETTLEMENT_CROSSED",
        }

    if isinstance(notionnel, bool) or not isinstance(notionnel, (int, float)):
        return _inconnu("FUNDING_NOTIONAL_UNMEASURABLE", coin)
    try:
        notionnel_float = float(notionnel)
    except (OverflowError, TypeError, ValueError):
        return _inconnu("FUNDING_NOTIONAL_UNMEASURABLE", coin)
    if not math.isfinite(notionnel_float) or notionnel_float <= 0:
        return _inconnu("FUNDING_NOTIONAL_UNMEASURABLE", coin)
    if isinstance(direction, bool) or direction not in (1, -1):
        return _inconnu("FUNDING_DIRECTION_UNMEASURABLE", coin)

    serie_brute = taux_par_coin.get(coin)
    if not serie_brute:
        return _inconnu("FUNDING_RATES_MISSING_FOR_COIN", coin)
    serie = _validated_funding_series(serie_brute)
    if serie is None:
        return _inconnu("FUNDING_RATE_SERIES_UNMEASURABLE", coin)

    # Search only the trade interval (O(log n + crossed settlements)); scanning an entire
    # multi-week tape once per trade would turn a correct gap check into an avoidable slowdown.
    traverses = _reglements_traverses(serie, entree, sortie)
    observed_by_hour: dict[int, Decimal] = {}
    for instant_ms, rate in traverses:
        hour = (instant_ms + INTERVALLE_MS // 2) // INTERVALLE_MS
        if hour in observed_by_hour:
            return _inconnu("FUNDING_DUPLICATE_SETTLEMENT_BUCKET", coin)
        observed_by_hour[hour] = rate
    expected_hours = {instant // INTERVALLE_MS for instant in expected_settlements}
    observed_hours = set(observed_by_hour)
    unexpected_hours = observed_hours - expected_hours
    if unexpected_hours:
        return _inconnu("FUNDING_SETTLEMENT_SCHEDULE_MISMATCH", coin)
    rates: list[Decimal] = []
    missing_settlements: list[int] = []
    for expected_ms in expected_settlements:
        rate = observed_by_hour.get(expected_ms // INTERVALLE_MS)
        if rate is None:
            missing_settlements.append(expected_ms)
        else:
            rates.append(rate)
    if missing_settlements:
        return {
            **_inconnu("FUNDING_SETTLEMENT_RATE_MISSING", coin),
            "missing_settlement_timestamps_ms": missing_settlements,
            "expected_settlement_count": len(expected_settlements),
            "observed_settlement_count": len(rates),
        }

    porte = Decimal(str(notionnel_float)) * Decimal(int(direction))
    try:
        cout = decimal_sum(taux * porte for taux in rates)
        pnl_exact = cout.copy_negate() if cout is not None else None
        pnl_float = float_not_above(pnl_exact) if pnl_exact is not None else None
    except (ArithmeticError, ValueError):
        return _inconnu("FUNDING_RATE_SERIES_UNMEASURABLE", coin)
    if pnl_exact is None or pnl_float is None:
        return _inconnu("FUNDING_RATE_SERIES_UNMEASURABLE", coin)
    return {
        # Rates are observed, but the notional is frozen at entry. Without the
        # settlement-time oracle and position quantity this is a diagnostic estimate,
        # never an exact funding cashflow or an economic-proof input.
        "status": "ESTIMATED",
        "coin": coin,
        "carry_pnl_usd": None,
        "carry_pnl_usd_exact_decimal": None,
        "estimated_carry_pnl_usd": pnl_float,
        "estimated_carry_pnl_usd_exact_decimal": format(pnl_exact, "f"),
        "settlement_crossing_count": len(expected_settlements),
        "settlement_interval_hours": 1,
        "provenance": PROVENANCE_RECONSTITUEE,
        "settlement_valuation_basis": "ENTRY_NOTIONAL_RATE_PROXY",
        "settlement_oracle_bound": False,
        "reason": "SETTLEMENT_ORACLE_PRICE_NOT_JOINED",
    }


def _inconnu(raison: str, coin: str) -> dict[str, Any]:
    return {
        "status": "UNMEASURABLE",
        "coin": coin,
        "carry_pnl_usd": None,
        "carry_pnl_usd_exact_decimal": None,
        "estimated_carry_pnl_usd": None,
        "estimated_carry_pnl_usd_exact_decimal": None,
        "settlement_crossing_count": None,
        "settlement_interval_hours": 1,
        "provenance": PROVENANCE_RECONSTITUEE,
        "reason": raison,
    }


def funding_des_trades(
    trades: Iterable[Mapping[str, Any]],
    taux_par_coin: Mapping[str, Sequence[tuple[int, Decimal]]],
    *,
    couverture_ms: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Le funding de TOUS les episodes, et un seul verdict : une inconnue suffit a l'emporter.

    Un total calcule sur les seuls episodes lisibles flatterait le resultat d'autant qu'il en
    manque. Si un seul reste inconnu, le total l'est aussi -- on dit combien, et pourquoi.
    """
    trade_rows = list(trades)
    recus = [
        funding_du_trade(trade, taux_par_coin, couverture_ms=couverture_ms)
        for trade in trade_rows
    ]
    inconnus = [r for r in recus if r["status"] == "UNMEASURABLE"]
    mesures = [r for r in recus if r["status"] == "MEASURED"]
    estimations = [r for r in recus if r["status"] == "ESTIMATED"]
    raisons: dict[str, int] = {}
    for recu in inconnus:
        raison = str(recu.get("reason") or "UNKNOWN")
        raisons[raison] = raisons.get(raison, 0) + 1
    if inconnus:
        return {
            "status": "UNMEASURABLE",
            "trade_count": len(recus),
            "measured_count": len(mesures),
            "estimated_count": len(estimations),
            "carry_pnl_usd": None,
            "estimated_carry_pnl_usd": None,
            "reasons": raisons,
            "trade_receipts": [
                {
                    **recu,
                    "trade_index": index,
                    "trade_id": trade.get("trade_id")
                    if isinstance(trade, Mapping)
                    else None,
                }
                for index, (trade, recu) in enumerate(zip(trade_rows, recus, strict=True))
            ],
            "provenance": PROVENANCE_RECONSTITUEE,
        }
    if estimations:
        estimate_total = decimal_sum(
            recu.get("estimated_carry_pnl_usd_exact_decimal", "0")
            if recu["status"] == "ESTIMATED"
            else recu.get("carry_pnl_usd_exact_decimal", "0")
            for recu in recus
        )
        if estimate_total is None:
            return {
                "status": "UNMEASURABLE",
                "trade_count": len(recus),
                "measured_count": len(mesures),
                "estimated_count": len(estimations),
                "carry_pnl_usd": None,
                "estimated_carry_pnl_usd": None,
                "reasons": {"FUNDING_TOTAL_NUMERIC_INVALID": len(recus) or 1},
                "trade_receipts": [
                    {
                        **recu,
                        "trade_index": index,
                        "trade_id": trade.get("trade_id")
                        if isinstance(trade, Mapping)
                        else None,
                    }
                    for index, (trade, recu) in enumerate(zip(trade_rows, recus, strict=True))
                ],
                "provenance": PROVENANCE_RECONSTITUEE,
            }
        estimate_float = float_not_above(estimate_total)
        if estimate_float is None:
            return {
                "status": "UNMEASURABLE",
                "trade_count": len(recus),
                "measured_count": len(mesures),
                "estimated_count": len(estimations),
                "carry_pnl_usd": None,
                "estimated_carry_pnl_usd": None,
                "reasons": {"FUNDING_TOTAL_NUMERIC_INVALID": len(recus) or 1},
                "provenance": PROVENANCE_RECONSTITUEE,
            }
        return {
            "status": "ESTIMATED",
            "trade_count": len(recus),
            "measured_count": len(mesures),
            "estimated_count": len(estimations),
            "carry_pnl_usd": None,
            "carry_pnl_usd_exact_decimal": None,
            "estimated_carry_pnl_usd": estimate_float,
            "estimated_carry_pnl_usd_exact_decimal": format(estimate_total, "f"),
            "settlement_crossing_count": sum(
                int(recu.get("settlement_crossing_count") or 0) for recu in recus
            ),
            "settlement_valuation_basis": "ENTRY_NOTIONAL_RATE_PROXY",
            "settlement_oracle_bound": False,
            "reason": "SETTLEMENT_ORACLE_PRICE_NOT_JOINED",
            "reasons": {"SETTLEMENT_ORACLE_PRICE_NOT_JOINED": len(estimations)},
            "trade_receipts": [
                {
                    **recu,
                    "trade_index": index,
                    "trade_id": trade.get("trade_id")
                    if isinstance(trade, Mapping)
                    else None,
                }
                for index, (trade, recu) in enumerate(zip(trade_rows, recus, strict=True))
            ],
            "provenance": PROVENANCE_RECONSTITUEE,
        }

    total = decimal_sum(r["carry_pnl_usd_exact_decimal"] for r in recus)
    if total is None:
        return {
            "status": "UNMEASURABLE",
            "trade_count": len(recus),
            "measured_count": len(recus),
            "carry_pnl_usd": None,
            "estimated_carry_pnl_usd": None,
            "reasons": {"FUNDING_TOTAL_NUMERIC_INVALID": len(recus) or 1},
            "trade_receipts": [
                {
                    **recu,
                    "trade_index": index,
                    "trade_id": trade.get("trade_id")
                    if isinstance(trade, Mapping)
                    else None,
                }
                for index, (trade, recu) in enumerate(zip(trade_rows, recus, strict=True))
            ],
            "provenance": PROVENANCE_RECONSTITUEE,
        }
    total_float = float_not_above(total)
    if total_float is None:
        return {
            "status": "UNMEASURABLE",
            "trade_count": len(recus),
            "measured_count": len(recus),
            "estimated_count": 0,
            "carry_pnl_usd": None,
            "reasons": {"FUNDING_TOTAL_NUMERIC_INVALID": len(recus) or 1},
            "provenance": PROVENANCE_RECONSTITUEE,
        }
    return {
        "status": "MEASURED",
        "trade_count": len(recus),
        "measured_count": len(recus),
        "estimated_count": 0,
        "carry_pnl_usd": total_float,
        "carry_pnl_usd_exact_decimal": format(total, "f"),
        "settlement_crossing_count": sum(r["settlement_crossing_count"] for r in recus),
        "reasons": {},
        "trade_receipts": [
            {
                **recu,
                "trade_index": index,
                "trade_id": trade.get("trade_id")
                if isinstance(trade, Mapping)
                else None,
            }
            for index, (trade, recu) in enumerate(zip(trade_rows, recus, strict=True))
        ],
        "provenance": PROVENANCE_RECONSTITUEE,
    }


def porte_de_funding(
    *, coin: str, entree_ms: int, sortie_ms: int, notionnel_usd: float, direction: int,
    taux_funding: Mapping[str, Sequence[tuple[int, Decimal]]] | None,
    couverture_ms: tuple[int, int] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """
Return a measured carry or a fail-closed execution refusal for one episode.

A position crossing an hourly settlement is accepted only if settlement cashflow can be valued exactly. The currently available rate x entry-notional proxy is ESTIMATED and is refused here. Exact boundary timestamps remain ambiguous; missing rates or coverage also refuse. An episode with no settlement crossing has a measured zero carry.
    """
    premiere = next_funding_time_ms(entree_ms - 1, interval_hours=1)
    if premiere > sortie_ms:
        return None, None
    ambigue = (premiere == entree_ms
               or next_funding_time_ms(sortie_ms - 1, interval_hours=1) == sortie_ms)
    if ambigue or taux_funding is None:
        return None, "FUNDING_BOUNDARY_UNPRICED"
    portage = funding_du_trade(
        {"coin": coin, "entry_ts_ms": entree_ms, "exit_ts_ms": sortie_ms,
         "notional_usd": notionnel_usd, "direction": direction},
        taux_funding, couverture_ms=couverture_ms,
    )
    if str(portage.get("status")) == "ESTIMATED":
        return None, "FUNDING_SETTLEMENT_VALUATION_UNAVAILABLE"
    if str(portage.get("status")) != "MEASURED":
        return None, "FUNDING_BOUNDARY_RATE_UNOBSERVED"
    return portage, None


def resume_funding_reel_leaders(rows: Iterable[object]) -> dict[str, Any]:
    """Summarize actual leader funding payments; never treat them as follower PnL."""
    schema = "hypersmart.copy_vault_funding.v1"
    comptes: dict[str, dict[str, Any]] = {}
    vus: dict[tuple[Any, ...], tuple[Decimal, Decimal, Decimal]] = {}
    evenements = doublons = conflits = rejetes = snapshots_vides = 0
    with localcontext() as context:
        context.prec = 50
        highest_adjusted = 0
        lowest_exponent = 0
        for row in rows:
            if not isinstance(row, Mapping):
                rejetes += 1
                continue
            if row.get("schema_version") == "hypersmart.copy_vault_funding.empty_snapshot.v1":
                snapshots_vides += 1
                continue
            if (
                row.get("schema_version") != schema
                or row.get("data_origin") != "REAL_OBSERVED_SAFE_CONTEXT"
                or row.get("paper_read_only") is not True
                or row.get("proof_of_pnl_allowed") is not False
                or row.get("forward_evidence_allowed") is not False
                or type(row.get("is_snapshot")) is not bool
                or type(row.get("historical_only")) is not bool
            ):
                rejetes += 1
                continue

            vault, coin, timestamp, event = (
                row.get("vault"), row.get("coin"), row.get("exchange_ts_ms"),
                row.get("event_raw"),
            )
            if (
                not isinstance(vault, str) or not vault.strip()
                or not isinstance(coin, str) or not coin.strip()
                or type(timestamp) is not int or timestamp <= 0
                or not isinstance(event, Mapping)
            ):
                rejetes += 1
                continue
            detail = event.get("delta") if isinstance(event.get("delta"), Mapping) else event
            if (
                not isinstance(detail, Mapping)
                or event.get("time") != timestamp
                or str(detail.get("coin") or "").strip() != coin
                or (detail.get("type") is not None and detail.get("type") != "funding")
            ):
                rejetes += 1
                continue
            usdc, size, rate = (
                decimal_value(detail.get("usdc")),
                decimal_value(detail.get("szi")),
                decimal_value(detail.get("fundingRate")),
            )
            if usdc is None or size is None or rate is None:
                rejetes += 1
                continue
            if usdc:
                highest_adjusted = max(highest_adjusted, usdc.adjusted())
                lowest_exponent = min(lowest_exponent, usdc.as_tuple().exponent)
                context.prec = max(
                    context.prec,
                    highest_adjusted - lowest_exponent + len(str(evenements + 1)) + 3,
                )

            raw_hash = event.get("hash")
            identity = (
                (vault, coin, timestamp, raw_hash.strip())
                if isinstance(raw_hash, str) and raw_hash.strip()
                else (vault, coin, timestamp, usdc, size, rate)
            )
            fingerprint = (usdc, size, rate)
            prior = vus.get(identity)
            if prior is not None:
                if prior == fingerprint:
                    doublons += 1
                else:
                    conflits += 1
                    rejetes += 1
                continue
            vus[identity] = fingerprint
            account = comptes.setdefault(vault, {
                "event_count": 0,
                "snapshot_event_count": 0,
                "historical_backfill_event_count": 0,
                "net": Decimal(0),
                "received": Decimal(0),
                "paid": Decimal(0),
                "first": timestamp,
                "last": timestamp,
            })
            account["event_count"] += 1
            account["snapshot_event_count"] += int(row["is_snapshot"])
            account["historical_backfill_event_count"] += int(row["historical_only"])
            account["net"] += usdc
            if usdc > 0:
                account["received"] += usdc
            elif usdc < 0:
                account["paid"] += usdc.copy_negate()
            account["first"] = min(account["first"], timestamp)
            account["last"] = max(account["last"], timestamp)
            evenements += 1

    by_vault = [
        {
            "vault": vault,
            "event_count": account["event_count"],
            "snapshot_event_count": account["snapshot_event_count"],
            "historical_backfill_event_count": account["historical_backfill_event_count"],
            "first_event_ts_ms": account["first"],
            "last_event_ts_ms": account["last"],
            "net_funding_usdc_exact_decimal": format(account["net"], "f"),
            "payments_received_usdc_exact_decimal": format(account["received"], "f"),
            "payments_paid_usdc_exact_decimal": format(account["paid"], "f"),
        }
        for vault, account in sorted(comptes.items())
    ]
    return {
        "status": "OBSERVED_ONLY" if evenements else "UNMEASURABLE",
        "scope": "LEADER_REALIZED_FUNDING_COMPONENT_ONLY",
        "coverage_status": "OBSERVED_EVENTS_ONLY_NOT_PROVEN_COMPLETE",
        "event_count": evenements,
        "vault_count": len(by_vault),
        "duplicate_event_count": doublons,
        "conflicting_event_count": conflits,
        "rejected_event_count": rejetes,
        "empty_snapshot_count": snapshots_vides,
        "by_vault": by_vault,
        "copy_vault_follower_pnl_input": False,
        "complete_leader_pnl_proven": False,
        "proof_of_pnl_allowed": False,
        "zero_cashflow_proven": False,
    }


def champs_de_portage(net: float, portage: Mapping[str, Any] | None) -> dict[str, Any]:
    """
Return separate fields for settled carry or an explicitly labelled diagnostic estimate.

The execution net is never rewritten. For ESTIMATED funding, certified carry and net-after-carry remain null; only estimate-specific fields are populated.
    """
    if portage is None:
        return {
            "carry_pnl_usd": 0.0,
            "carry_status": "MEASURED_ZERO_NO_SETTLEMENT_CROSSED",
            "carry_provenance": None,
            "settlement_crossing_count": 0,
            "net_after_carry_usd": net,
        }
    if portage.get("status") == "ESTIMATED":
        estimate = float(portage["estimated_carry_pnl_usd"])
        return {
            "carry_pnl_usd": None,
            "carry_status": "ESTIMATED",
            "carry_provenance": portage.get("provenance"),
            "settlement_crossing_count": int(portage["settlement_crossing_count"]),
            "settlement_valuation_basis": "ENTRY_NOTIONAL_RATE_PROXY",
            "net_after_carry_usd": None,
            "estimated_carry_pnl_usd": estimate,
            "net_after_carry_estimate_usd": net + estimate,
        }
    cout = float(portage["carry_pnl_usd"])
    return {
        "carry_pnl_usd": cout,
        "carry_status": str(portage["status"]),
        "carry_provenance": portage.get("provenance"),
        "settlement_crossing_count": int(portage["settlement_crossing_count"]),
        "net_after_carry_usd": net + cout,
    }
