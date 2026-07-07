"""V9 — Couche d'admission des fills live (la "porte d'entrée" propre).

Décide, pour un fill/delta de leader entrant, s'il doit être ADMIS comme signal
de copy-trading frais, et de quel type (ENTRÉE / SORTIE), ou ignoré (et si oui,
faut-il l'écrire au ledger ou le sauter silencieusement).

Consolide en UN seul point testable les corrections des logs réels :
  - T2  marchés exotiques (HIP-3/RWA/builder/spot) -> skip silencieux
  - T3  backfill rejoué (fill trop vieux) -> skip silencieux (pas un signal live)
  - T4  doublons (fill déjà traité) -> skip silencieux  (le caller fournit le set "vu")
  - T5  REDUCE/CLOSE sans position paper -> skip silencieux (supprime ~50% du bruit)
  - T8  classification ENTRÉE vs SORTIE + respect de allow_add_as_entry

C'est une décision de recherche locale. Ce n'est PAS un ordre, ni une recommandation,
ni une promesse de PnL. read-only / paper-only. Aucune donnée inventée.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from hl_observer.markets.universe import is_exotic_market


ENTRY_ACTIONS = {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"}
EXIT_ACTIONS = {"REDUCE", "CLOSE_LONG", "CLOSE_SHORT"}

# kinds
KIND_ENTRY = "ENTRY"
KIND_EXIT = "EXIT"
KIND_SKIP = "SKIP"

# reasons
R_FRESH_ENTRY = "FRESH_ENTRY"
R_FRESH_EXIT = "FRESH_EXIT"
R_STALE_BACKFILL = "STALE_BACKFILL"
R_DUPLICATE = "DUPLICATE_FILL"
R_NO_POSITION_FOR_EXIT = "NO_PAPER_POSITION_FOR_EXIT"
R_EXOTIC_MARKET = "EXOTIC_MARKET"
R_ADD_NOT_ENTRY = "ADD_NOT_ENTRY"
R_UNKNOWN_DELTA = "UNKNOWN_DELTA"
R_TIMESTAMP_FUTURE = "TIMESTAMP_IN_FUTURE"
R_PRICE_INVALID = "PRICE_INVALID"
R_STALE_SIGNAL = "STALE_SIGNAL"


@dataclass(frozen=True, slots=True)
class FillAdmissionConfig:
    max_signal_age_ms: int = 15_000
    # au-delà de ce cap dur, c'est de l'historique (backfill), pas un signal live.
    hard_backfill_age_ms: int = 30_000
    allow_add_as_entry: bool = True
    allow_exotic_markets: bool = False
    # tolérance d'horloge (un fill peut sembler légèrement dans le futur)
    future_tolerance_ms: int = 2_000

    read_only: bool = True
    execution: str = "forbidden"


@dataclass(frozen=True, slots=True)
class FillAdmission:
    admit: bool
    kind: str          # ENTRY | EXIT | SKIP
    reason: str
    age_ms: int
    log_decision: bool  # faut-il écrire cette décision au ledger ?
    is_fresh: bool
    read_only: bool = True
    execution: str = "forbidden"


def fill_identity(
    *,
    wallet_address: str,
    coin: str,
    side: str,
    action_type: str,
    price: float,
    size: float,
    ts_ms: int,
) -> str:
    """Identité stable d'un fill (pour la déduplication persistante, T4)."""
    raw = "|".join(
        [
            str(wallet_address or "").lower(),
            str(coin or "").upper(),
            str(side or "").upper(),
            str(action_type or "").upper(),
            f"{float(price or 0):.8f}",
            f"{float(size or 0):.8f}",
            str(int(ts_ms or 0)),
        ]
    )
    return sha256(raw.encode("utf-8")).hexdigest()[:24]


def admit_live_fill(
    *,
    action_type: str,
    coin: str,
    fill_ts_ms: int,
    now_ms: int,
    already_seen: bool,
    has_matching_paper_position: bool,
    leader_price: float | None = None,
    config: FillAdmissionConfig | None = None,
) -> FillAdmission:
    """Porte d'entrée : admettre / classer / ignorer un fill live.

    Le caller maintient le set des identités déjà vues (T4) et l'état des positions
    paper ouvertes (T5). Les "skip" silencieux (log_decision=False) NE doivent PAS
    être écrits au ledger : c'est ce qui supprime le bruit (backfill, doublons,
    exotiques, sorties sans position).
    """

    cfg = config or FillAdmissionConfig()
    action = str(action_type or "").upper()
    age = int(now_ms) - int(fill_ts_ms)

    def skip(reason: str, *, log: bool = False) -> FillAdmission:
        return FillAdmission(
            admit=False,
            kind=KIND_SKIP,
            reason=reason,
            age_ms=max(0, age),
            log_decision=log,
            is_fresh=False,
        )

    # garde d'horloge : fill "dans le futur" au-delà de la tolérance -> on ignore
    if age < -abs(cfg.future_tolerance_ms):
        return skip(R_TIMESTAMP_FUTURE)
    age = max(0, age)

    # T4 — déjà traité -> doublon, skip silencieux
    if already_seen:
        return skip(R_DUPLICATE)

    # T2 — marché exotique (HIP-3/RWA/builder/spot) -> skip silencieux
    if not cfg.allow_exotic_markets and is_exotic_market(coin):
        return skip(R_EXOTIC_MARKET)

    # T3 — backfill (trop vieux pour être un signal live) -> skip silencieux
    if age > max(0, int(cfg.hard_backfill_age_ms)):
        return skip(R_STALE_BACKFILL)

    # ENTRÉE potentielle
    if action in ENTRY_ACTIONS:
        if leader_price is not None and float(leader_price) <= 0:
            return skip(R_PRICE_INVALID, log=True)
        if age > max(0, int(cfg.max_signal_age_ms)):
            return skip(R_STALE_SIGNAL, log=True)
        if action in {"ADD", "INCREASE"} and not cfg.allow_add_as_entry and not has_matching_paper_position:
            # ADD interdit comme entrée et on ne détient rien -> skip silencieux
            return skip(R_ADD_NOT_ENTRY)
        fresh = age <= max(0, int(cfg.max_signal_age_ms))
        return FillAdmission(
            admit=True,
            kind=KIND_ENTRY,
            reason=R_FRESH_ENTRY,
            age_ms=age,
            log_decision=True,
            is_fresh=fresh,
        )

    # SORTIE potentielle
    if action in EXIT_ACTIONS:
        if not has_matching_paper_position:
            # T5 — sortie d'un leader sur une position qu'on n'a pas -> skip silencieux
            return skip(R_NO_POSITION_FOR_EXIT)
        return FillAdmission(
            admit=True,
            kind=KIND_EXIT,
            reason=R_FRESH_EXIT,
            age_ms=age,
            log_decision=True,
            is_fresh=age <= max(0, int(cfg.max_signal_age_ms)),
        )

    # action non reconnue
    return skip(R_UNKNOWN_DELTA)


__all__ = [
    "ENTRY_ACTIONS",
    "EXIT_ACTIONS",
    "KIND_ENTRY",
    "KIND_EXIT",
    "KIND_SKIP",
    "R_FRESH_ENTRY",
    "R_FRESH_EXIT",
    "R_STALE_BACKFILL",
    "R_DUPLICATE",
    "R_NO_POSITION_FOR_EXIT",
    "R_EXOTIC_MARKET",
    "R_ADD_NOT_ENTRY",
    "R_UNKNOWN_DELTA",
    "R_STALE_SIGNAL",
    "FillAdmissionConfig",
    "FillAdmission",
    "fill_identity",
    "admit_live_fill",
]
