"""Étude de copiabilité — entrées : configuration, fills normalisés, panneaux de prix causaux,
taux de funding, grappes d'adresses clones et statistiques de base.

Calcul pur : aucun réseau, aucun ordre. Voir ``copy_vault_copiability`` (façade).
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from hl_observer.fees.hyperliquid_fees import TAKER_PERP_BPS


SCHEMA_VERSION = "hypersmart.copy_vault_copiability.v1"
MECHANISM = "copy_vault_copiability_decay_attribution_v1"
EVIDENCE_TIER_LOCAL = "LOCAL_TRAIN_EXPLORATORY"

#: libellés ``dir`` des perps directionnels ; tout le reste (spot, règlement...) est écarté.
DIRECTIONAL_LABELS = frozenset(
    {"Open Long", "Open Short", "Close Long", "Close Short", "Long > Short", "Short > Long"}
)
FILL_COLUMNS = (
    "vault", "coin", "time", "obs", "px", "sz", "signe", "dir", "start_pos",
    "closed_pnl", "crossed", "fee", "tid", "oid", "snap",
)
IDENTITY_COLUMNS = ("vault", "coin", "time", "tid", "oid", "px", "sz", "signe")
DAY_MS = 86_400_000

H_NAIVE_MIRROR = "copy_vault_naive_mirror_taker"
H_FAST_FOLLOW = "copy_vault_fast_follow_taker_fills"
H_SLOW_REPLICATION = "copy_vault_slow_inventory_replication"


@dataclass(frozen=True, slots=True)
class CopiabilityConfig:
    """Hypothèses explicites de l'étude ; toutes entrent dans l'identité de l'expérience."""

    stale_price_ms: int = 10_000
    reaction_delay_ms: int = 2_000
    clock_skew_tolerance_ms: int = 1_000
    taker_fee_bps: float = TAKER_PERP_BPS
    horizons_s: tuple[int, ...] = (5, 15, 30, 60, 120, 300, 900, 1_800, 3_600, 7_200, 14_400)
    #: au-delà, la dérive relève de l'inventaire (hypothèse lente), pas du suivi rapide
    fast_horizon_max_s: int = 300
    #: nombre minimal de fenêtres temporelles disjointes pour qu'un horizon soit concluant
    min_independent_windows: int = 30
    #: en deçà, l'observation est « rapide » (WebSocket) ; au-delà elle est « lente » (relevé REST)
    fast_observation_ms: int = 2_000
    rebalance_minutes: tuple[int, ...] = (1, 5, 15, 60)
    min_fills_per_unit: int = 200
    min_episodes_per_unit: int = 20
    min_exposure_usd: float = 1_000.0
    min_day_coverage_hours: float = 6.0
    min_independent_days: int = 20
    min_train_days: int = 3
    sybil_jaccard: float = 0.25
    sybil_min_events: int = 200
    bootstrap_draws: int = 2_000
    seed: int = 20_261_111

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_fill_row(
    row: Mapping[str, Any], *, assumed_lag_ms: int | None = None
) -> tuple[tuple[Any, ...] | None, str | None]:
    """Convertit un enregistrement brut en tuple ``FILL_COLUMNS`` ou donne la raison du rejet.

    Aucune valeur n'est inventée : un champ illisible devient ``NaN`` et le contrôle de
    cohérence (``prepare_fills``) décide ensuite du rejet, compté par raison.

    ``assumed_lag_ms`` ne sert QU'AUX études rétrospectives sur des fills récupérés après
    coup (backfill REST, sans instant d'observation) : l'observation est alors **supposée**
    à ``événement + retard``. Ces fills n'étaient pas disponibles en temps réel ; l'étude qui
    les emploie doit porter le statut « reconstruit rétrospectivement », jamais « causal ».
    Un fill qui possède un vrai instant d'observation le conserve toujours.
    """

    time = row.get("time", row.get("ts_ms"))
    obs = row.get("observed_at_ms", row.get("received_at_ms"))
    if type(time) is not int or time <= 0:
        return None, "horodatage_invalide"
    if type(obs) is not int or obs <= 0:
        if assumed_lag_ms is None or obs is not None:
            return None, "horodatage_invalide"
        obs = time + int(assumed_lag_ms)
    side = row.get("side", row.get("side_raw"))
    signe = 1 if side == "B" else -1 if side == "A" else 0
    if signe == 0:
        # les fills WebSocket normalisés par le collecteur portent directement le sens signé
        declared = row.get("signe", row.get("fill_sign"))
        if type(declared) is int and declared in (-1, 1):
            signe = declared
    crossed = row.get("crossed")
    tid, oid = row.get("tid"), row.get("oid")
    start = row.get("startPosition", row.get("start_position", row.get("pos_avant")))
    return (
        str(row.get("vault") or "").lower(),
        str(row.get("coin") or ""),
        time,
        obs,
        _to_float(row.get("px")),
        _to_float(row.get("sz")),
        signe,
        str(row.get("dir") or ""),
        _to_float(start),
        _to_float(row.get("closedPnl", row.get("closed_pnl"))),
        float("nan") if crossed is None else float(bool(crossed)),
        _to_float(row.get("fee")),
        tid if type(tid) is int else -1,
        oid if type(oid) is int else -1,
        bool(row.get("isSnapshot") or row.get("is_snapshot")),
    ), None


def _to_float(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        return float("nan")
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return float("nan")
    return out if math.isfinite(out) else float("nan")


def fills_frame_from_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[pd.DataFrame, dict[str, int]]:
    """Construit la table de fills brute ; renvoie aussi le décompte des lignes illisibles."""

    parsed: list[tuple[Any, ...]] = []
    rejects: dict[str, int] = {}
    for row in rows:
        record, reason = parse_fill_row(row)
        if record is None:
            rejects[str(reason)] = rejects.get(str(reason), 0) + 1
        else:
            parsed.append(record)
    return pd.DataFrame(parsed, columns=list(FILL_COLUMNS)), rejects


def prepare_fills(
    frame: pd.DataFrame, config: CopiabilityConfig | None = None
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Valide, déduplique et ordonne les fills. Chaque rejet est compté par raison.

    La déduplication conserve la **première** observation d'une même identité native : c'est
    le premier instant où l'information était disponible.
    """

    cfg = config or CopiabilityConfig()
    missing = [name for name in FILL_COLUMNS if name not in frame.columns]
    if missing:
        raise ValueError(f"colonnes de fills manquantes: {missing}")
    df = frame.loc[:, list(FILL_COLUMNS)].copy()
    for name in ("vault", "coin", "dir"):
        df[name] = df[name].astype(str)
    rejects: dict[str, int] = {}

    def drop(mask: pd.Series, reason: str) -> None:
        nonlocal df
        count = int(mask.sum())
        if count:
            rejects[reason] = rejects.get(reason, 0) + count
            df = df.loc[~mask]

    drop(df["snap"].astype(bool), "snapshot_non_causal")
    drop(~df["dir"].isin(DIRECTIONAL_LABELS), "direction_non_directionnelle")
    drop((df["vault"] == "") | (df["coin"] == ""), "identite_incomplete")
    drop(~(df["px"] > 0) | ~(df["sz"] > 0), "prix_ou_taille_invalide")
    drop(~df["signe"].isin((-1, 1)), "sens_inconnu")
    drop(df["start_pos"].isna(), "position_depart_inconnue")
    drop(df["obs"] < df["time"] - cfg.clock_skew_tolerance_ms, "observation_avant_evenement")
    df = df.sort_values("obs", kind="stable")
    duplicated = df.duplicated(list(IDENTITY_COLUMNS), keep="first")
    drop(duplicated, "doublon_identite")
    df = df.sort_values(["vault", "coin", "time", "tid"], kind="stable").reset_index(drop=True)
    df["notional"] = df["px"] * df["sz"]
    df["after"] = df["start_pos"] + df["signe"] * df["sz"]
    df["is_open"] = df["dir"].str.startswith("Open") | df["dir"].str.contains(">", regex=False)
    return df, rejects


@dataclass(frozen=True)
class PricePanel:
    """Série de prix causale : ``at(t)`` ne lit qu'un prix daté ``<= t`` et encore frais."""

    ts: np.ndarray
    px: np.ndarray
    coins: tuple[str, ...]
    provenance: str
    stale_ms: int
    _index: dict[str, int] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.ts.ndim != 1 or self.px.ndim != 2 or self.px.shape != (len(self.ts), len(self.coins)):
            raise ValueError("panel de prix incohérent")
        if len(self.ts) > 1 and not bool(np.all(np.diff(self.ts) > 0)):
            raise ValueError("les horodatages du panel doivent être strictement croissants")
        object.__setattr__(self, "_index", {coin: i for i, coin in enumerate(self.coins)})

    def column(self, coin: str) -> int | None:
        return self._index.get(coin)

    def at(self, t: np.ndarray, col: np.ndarray | int) -> np.ndarray:
        """Dernier prix connu à ``t`` ; ``NaN`` si aucun prix ou prix plus vieux que ``stale_ms``."""

        t = np.asarray(t, dtype=np.int64)
        if len(self.ts) == 0:
            return np.full(t.shape, np.nan)
        idx = np.searchsorted(self.ts, t, side="right") - 1
        known = idx >= 0
        idx = np.clip(idx, 0, len(self.ts) - 1)
        out = np.array(self.px[idx, col], dtype=np.float64)
        out[~known | ((t - self.ts[idx]) > self.stale_ms)] = np.nan
        return out

    def valid_intervals(self) -> np.ndarray:
        """Intervalles ``[i, i+1]`` dont la durée respecte la fraîcheur (sinon PnL inconnu)."""

        return np.diff(self.ts) <= self.stale_ms

    def market_hours(self) -> float:
        dt = np.diff(self.ts)
        return float(dt[dt <= self.stale_ms].sum() / 3_600_000.0)

    def gaps(self, threshold_ms: int = 60_000) -> list[dict[str, int]]:
        dt = np.diff(self.ts)
        return [
            {"start_ms": int(self.ts[i]), "end_ms": int(self.ts[i + 1]), "duration_ms": int(dt[i])}
            for i in np.flatnonzero(dt > threshold_ms)
        ]


def build_mid_panel(
    snapshots: Iterable[tuple[int, Mapping[str, Any]]], *, stale_ms: int = 10_000
) -> PricePanel:
    """Panel de mids depuis des instantanés ``(ts_ms, {coin: mid})`` (flux ``allMids``).

    Deux instantanés de même horodatage : le premier lu est conservé (pas de moyenne).
    """

    by_ts: dict[int, Mapping[str, Any]] = {}
    for ts, mids in snapshots:
        if type(ts) is int and ts > 0 and ts not in by_ts:
            by_ts[ts] = mids
    order = sorted(by_ts)
    coins: dict[str, int] = {}
    for ts in order:
        for coin in by_ts[ts]:
            if coin not in coins:
                coins[coin] = len(coins)
    px = np.full((len(order), len(coins)), np.nan, dtype=np.float64)
    for i, ts in enumerate(order):
        for coin, value in by_ts[ts].items():
            price = _to_float(value)
            if price > 0:
                px[i, coins[coin]] = price
    return PricePanel(
        ts=np.array(order, dtype=np.int64), px=px, coins=tuple(coins),
        provenance="HYPERLIQUID_ALLMIDS_OBSERVED", stale_ms=stale_ms,
    )


def build_candle_panel(
    candles: Iterable[tuple[str, int, Any]], *, interval_ms: int, tolerance_ms: int = 60_000
) -> PricePanel:
    """Panel de prix depuis des bougies ``(coin, ouverture_ms, clôture)`` d'intervalle fixe.

    Le prix de clôture n'est publié qu'à la **fin** de la bougie (``ouverture + intervalle``) :
    le lire plus tôt serait une avance d'information. Fraîcheur = un intervalle + tolérance ;
    une bougie manquante laisse donc le prix inconnu (aucune interpolation).
    Ces bougies sont récupérées après coup : provenance « rétrospective », non causale.
    """

    by_ts: dict[int, dict[str, float]] = {}
    coins: dict[str, int] = {}
    for coin, open_ms, close in candles:
        price = _to_float(close)
        if type(open_ms) is not int or open_ms <= 0 or not price > 0 or not coin:
            continue
        coins.setdefault(str(coin), len(coins))
        by_ts.setdefault(open_ms + interval_ms, {}).setdefault(str(coin), price)
    order = sorted(by_ts)
    px = np.full((len(order), len(coins)), np.nan, dtype=np.float64)
    for i, ts in enumerate(order):
        for coin, price in by_ts[ts].items():
            px[i, coins[coin]] = price
    return PricePanel(
        ts=np.array(order, dtype=np.int64), px=px, coins=tuple(coins),
        provenance="HYPERLIQUID_CANDLE_CLOSE_RETROSPECTIVE", stale_ms=interval_ms + tolerance_ms,
    )


def build_funding_rates(
    observations: Iterable[tuple[str, int, Any]], panel: PricePanel, *, stale_ms: int = 7_200_000
) -> dict[str, np.ndarray]:
    """Taux de funding HORAIRE par coin, aligné sur la grille de prix (``NaN`` = inconnu).

    Entrée : ``(coin, ts_ms, taux_horaire)`` observés (flux ``asset_ctx``). À chaque instant de
    la grille on retient le dernier taux observé avant lui, s'il date de moins de ``stale_ms``
    (le taux bouge lentement ; au-delà de deux heures on ne le suppose plus). Un coin ou une
    période sans observation reste inconnu : le funding n'est jamais mis à zéro par défaut.
    """

    per_coin: dict[str, list[tuple[int, float]]] = {}
    for coin, ts, rate in observations:
        value = _to_float(rate)
        if coin and type(ts) is int and ts > 0 and math.isfinite(value):
            per_coin.setdefault(str(coin), []).append((ts, value))
    rates: dict[str, np.ndarray] = {}
    for coin, rows in per_coin.items():
        if panel.column(coin) is None:
            continue
        rows.sort()
        times = np.array([r[0] for r in rows], dtype=np.int64)
        values = np.array([r[1] for r in rows], dtype=np.float64)
        idx = np.searchsorted(times, panel.ts, side="right") - 1
        known = idx >= 0
        idx = np.clip(idx, 0, len(times) - 1)
        aligned = values[idx].copy()
        aligned[~known | ((panel.ts - times[idx]) > stale_ms)] = np.nan
        rates[coin] = aligned
    return rates


def alias_legacy_symbols(panel: PricePanel, native_coins: Iterable[str]) -> tuple[PricePanel, dict[str, str]]:
    """Répare les anciens rubans dont les symboles ont été mis en majuscules à l'écriture.

    Un symbole du panel absent des fills est renommé vers le symbole natif **unique** qui lui
    est identique à la casse près (``KPEPE`` -> ``kPEPE``). Ambigu ou déjà présent : inchangé.
    Renvoie le panel corrigé et la table ``ancien -> natif`` (tracée dans le rapport).
    """

    native = set(native_coins)
    by_upper: dict[str, list[str]] = {}
    for coin in native:
        by_upper.setdefault(coin.upper(), []).append(coin)
    aliases: dict[str, str] = {}
    present = set(panel.coins)
    for coin in panel.coins:
        if coin in native:
            continue
        matches = by_upper.get(coin.upper(), [])
        if len(matches) == 1 and matches[0] not in present:
            aliases[coin] = matches[0]
    if not aliases:
        return panel, {}
    coins = tuple(aliases.get(coin, coin) for coin in panel.coins)
    return PricePanel(panel.ts, panel.px, coins, panel.provenance, panel.stale_ms), dict(sorted(aliases.items()))


def build_print_panel(
    fills: pd.DataFrame, *, grid_ms: int = 5_000, stale_ms: int = 60_000, min_prints: int = 500
) -> PricePanel:
    """Panel de repli depuis les prix de transactions observés (dernier print par pas).

    Un print d'instant ``tau`` n'est publié qu'à la **fin** de son pas (``>= tau``) : aucune
    lecture en avance. Biais connu : rebond bid/ask (au plus un demi-spread), acceptable pour
    un PnL d'inventaire, inadapté à la mesure de l'exécution contre le mid.
    """

    counts = fills["coin"].value_counts()
    coins = tuple(sorted(counts[counts >= min_prints].index))
    if not coins or fills.empty:
        return PricePanel(np.zeros(0, np.int64), np.zeros((0, len(coins))), coins, "TRADE_PRINT_LAST", stale_ms)
    sub = fills.loc[fills["coin"].isin(coins), ["coin", "time", "px"]].sort_values("time", kind="stable")
    bucket = (sub["time"].to_numpy() // grid_ms) + 1
    first, last = int(bucket.min()), int(bucket.max())
    col = sub["coin"].map({coin: i for i, coin in enumerate(coins)}).to_numpy()
    px = np.full((last - first + 1, len(coins)), np.nan, dtype=np.float64)
    px[bucket - first, col] = sub["px"].to_numpy()  # tri par temps => le dernier print gagne
    limit = max(int(stale_ms // grid_ms), 1)
    filled = pd.DataFrame(px).ffill(limit=limit).to_numpy()
    ts = (np.arange(first, last + 1, dtype=np.int64)) * grid_ms
    return PricePanel(ts=ts, px=filled, coins=coins, provenance="TRADE_PRINT_LAST", stale_ms=grid_ms)


def detect_sybil_clusters(fills: pd.DataFrame, config: CopiabilityConfig | None = None) -> dict[str, str]:
    """Regroupe les adresses au comportement quasi identique (même opérateur probable).

    Signature d'une adresse : ensemble des événements ``(coin, minute, sens)``. Deux adresses
    dont les signatures ont un indice de Jaccard ``>= sybil_jaccard`` sont fusionnées
    (union-find). Renvoie ``adresse -> représentant`` (plus petite adresse du groupe).
    Sans cela, huit portefeuilles d'un même robot compteraient pour huit signaux indépendants.
    """

    cfg = config or CopiabilityConfig()
    if fills.empty:
        return {}
    coin_code = pd.factorize(fills["coin"], sort=True)[0].astype(np.int64)
    key = (coin_code << 34) | ((fills["time"].to_numpy() // 60_000) << 1) | (fills["signe"].to_numpy() > 0)
    # hachage multiplicatif : sert uniquement à sous-échantillonner les grandes signatures de
    # façon identique pour toutes les adresses (estimation sans biais du Jaccard).
    mixed = (key.astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15)) >> np.uint64(40)
    signatures: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for vault, idx in fills.groupby("vault", sort=True).indices.items():
        unique, first = np.unique(key[idx], return_index=True)
        if len(unique) >= cfg.sybil_min_events:
            signatures[str(vault)] = (unique, mixed[idx][first])
    parent = {str(vault): str(vault) for vault in fills["vault"].unique()}
    sampled: dict[tuple[str, int], np.ndarray] = {}

    def sample(name: str, level: int) -> np.ndarray:
        if (name, level) not in sampled:
            unique, mix = signatures[name]
            sampled[(name, level)] = unique if level == 0 else unique[(mix & np.uint64((1 << level) - 1)) == 0]
        return sampled[(name, level)]

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    names = sorted(signatures)
    for i, a in enumerate(names):
        len_a = len(signatures[a][0])
        for b in names[i + 1:]:
            len_b = len(signatures[b][0])
            small, large = min(len_a, len_b), max(len_a, len_b)
            if small < cfg.sybil_jaccard * large:  # borne supérieure du Jaccard
                continue
            level = max(int(math.log2(small / 4_096)), 0) if small > 4_096 else 0
            sa, sb = sample(a, level), sample(b, level)
            inter = len(np.intersect1d(sa, sb, assume_unique=True))
            union = len(sa) + len(sb) - inter
            if union and inter / union >= cfg.sybil_jaccard:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
    return {vault: find(vault) for vault in parent}


def _bootstrap_mean_ci(values: np.ndarray, config: CopiabilityConfig) -> tuple[float, float]:
    """IC 95 % (percentile) de la moyenne entre unités ; ``NaN`` si moins de 3 unités."""

    x = values[np.isfinite(values)]
    if len(x) < 3:
        return float("nan"), float("nan")
    rng = np.random.default_rng(config.seed)
    draws = x[rng.integers(0, len(x), size=(config.bootstrap_draws, len(x)))].mean(axis=1)
    low, high = np.quantile(draws, [0.025, 0.975])
    return float(low), float(high)


def _row_nanmean(matrix: np.ndarray) -> np.ndarray:
    """Moyenne par ligne en ignorant les ``NaN`` ; ligne entièrement inconnue => ``NaN``."""

    if matrix.ndim != 2 or matrix.shape[0] == 0:
        return np.zeros(0)
    finite = np.isfinite(matrix)
    count = finite.sum(axis=1)
    total = np.where(finite, matrix, 0.0).sum(axis=1)
    return np.where(count > 0, total / np.where(count > 0, count, 1), np.nan)


def _stat(values: np.ndarray, config: CopiabilityConfig) -> dict[str, Any]:
    x = values[np.isfinite(values)]
    if len(x) == 0:
        return {"units": 0, "mean": None, "median": None, "ci95": [None, None], "share_positive": None}
    low, high = _bootstrap_mean_ci(values, config)
    return {
        "units": int(len(x)),
        "mean": float(x.mean()),
        "median": float(np.median(x)),
        "ci95": [None if math.isnan(low) else low, None if math.isnan(high) else high],
        "share_positive": float((x > 0).mean()),
    }
