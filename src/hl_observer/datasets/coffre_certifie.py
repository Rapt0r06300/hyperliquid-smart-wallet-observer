"""Module de certification du « coffre-fort données certifiées » (tier LOCAL).

Portail UNIVERSEL : toute donnée locale candidate au coffre passe par ici. Le
module décide, enregistrement par enregistrement, si la donnée est
**replayable + backtestable** (utile pour les tests du labo). Il **répare** ce qui
est réparable, **salvage** la portion exploitable, et met en **quarantaine** (avec
raison) ce qui reste irréparable — jamais de suppression silencieuse, jamais de
« pass » muet.

Honnêteté (non négociable) :
- tier LOCAL : certifié ici, étiqueté ``tier="LOCAL"`` / ``LOCAL_UNRECONCILED`` —
  JAMAIS déguisé en SAFE, JAMAIS inséré dans l'audit SAFE du labo ;
- tier SAFE-cloud : ce module ne le MODIFIE jamais et ne le bloque jamais ; il le
  vérifie en lecture seule (verdict de replayabilité) ailleurs (voir
  ``verifier_corpus_safe``), le SAFE restant toujours admis.

Lecture seule / PAPER : aucune clé, aucun ordre. Le module ne fait AUCUN réseau.
Conçu pour un traitement en streaming (ligne par ligne) : il ne charge jamais un
flux entier en mémoire.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

# Interface historique conservee : tout ce qui a ete deplace dans les modules ``coffre_*``
# reste importable depuis ``coffre_certifie``.
from hl_observer.datasets.coffre_socle import (  # noqa: F401
    FAMILLE_ALLMIDS,
    FAMILLE_ASSET_CTX,
    FAMILLE_BBO,
    FAMILLE_BOOK_L2,
    FAMILLE_CANDLE,
    FAMILLE_DISPERSION,
    FAMILLE_EXPLORER_TX,
    FAMILLE_FILLS_BACKFILL,
    FAMILLE_FILLS_FORWARD,
    FAMILLE_LIQUIDATION,
    FAMILLE_MICRO_BBO,
    FAMILLE_MICRO_L2,
    FAMILLE_MICRO_TRADES,
    FAMILLE_OVERSHOOT,
    FAMILLE_POSITION,
    FAMILLE_SNAPSHOT,
    FAMILLE_TRADES,
    FAMILLE_VAULT_LEDGER,
    FAMILLE_VENUE,
    MAX_TARGET_LAG_MS,
    PASS,
    QUARANTAINE,
    REPARE,
    SOURCES_NON_CERTIFIABLES,
    _FUTUR_TOLERANCE_MS,
    _canonical_coin,
    _entier_positif,
    _niveaux,
    _nombre_fini,
    _signe_depuis_side,
    _source_certifiable,
)
from hl_observer.datasets.coffre_registre_fichiers import (  # noqa: F401
    FICHIERS_NON_CERTIFIES,
    VERSIONS_CERTIFICATEUR,
    motif_non_certifie,
    nouvellement_accepte,
    version_certificateur,
)
from hl_observer.datasets.coffre_familles_collecte import (  # noqa: F401
    SCHEMA_SNAPSHOT_VAULT,
    certifier_explorer_tx,
    certifier_micro_bbo,
    certifier_micro_l2,
    certifier_micro_trade,
    certifier_snapshot_vault,
    certifier_vault_ledger,
)
from hl_observer.datasets.coffre_familles_contexte import (  # noqa: F401
    certifier_allmids,
    certifier_asset_ctx,
    certifier_dispersion,
    certifier_liquidation,
    certifier_overshoot,
    certifier_venue,
)


# --------------------------------------------------------------------------- #
# Familles de données et décisions
# --------------------------------------------------------------------------- #


#: association nom de fichier -> (famille, étiquette de flux source)
_FICHIERS_CONNUS: dict[str, tuple[str, str]] = {
    "vault_fills_poll.jsonl": (FAMILLE_FILLS_FORWARD, "LIVE_POLL"),
    "vault_fills_live.jsonl": (FAMILLE_FILLS_FORWARD, "LIVE_WS"),
    "copy_vault_twap_lane.jsonl": (FAMILLE_FILLS_FORWARD, "LIVE_TWAP"),
    "vault_fills.jsonl": (FAMILLE_FILLS_BACKFILL, "REST_BACKFILL"),
    "node_fills_tape.jsonl": (FAMILLE_FILLS_BACKFILL, "NODE_FILLS"),
    "copy_vault_l2_tape.jsonl": (FAMILLE_BOOK_L2, "HYPERLIQUID_L2_WS"),
    "bbo_tape.jsonl": (FAMILLE_BBO, "BBO_TAPE"),
    "copy_vault_bbo_tape.jsonl": (FAMILLE_BBO, "BBO_TAPE"),
    "copy_vault_bbo_lane.jsonl": (FAMILLE_BBO, "BBO_TAPE"),
    "vault_snapshots.jsonl": (FAMILLE_SNAPSHOT, "SNAPSHOT"),
    "copy_vault_positions_lane.jsonl": (FAMILLE_POSITION, "CLEARINGHOUSE_WS"),
    "copy_vault_trades_lane.jsonl": (FAMILLE_TRADES, "HYPERLIQUID_TRADES_WS"),
    "copy_vault_candle_lane.jsonl": (FAMILLE_CANDLE, "HYPERLIQUID_CANDLE_WS"),
    "hl_allmids_tape.jsonl": (FAMILLE_ALLMIDS, "HYPERLIQUID_ALLMIDS"),
    "asset_ctx_tape.jsonl": (FAMILLE_ASSET_CTX, "HYPERLIQUID_ASSET_CTX"),
    "liquidations_confirmees.jsonl": (FAMILLE_LIQUIDATION, "LIQUIDATION_CONFIRMEE"),
    "overshoots_liquidation.jsonl": (FAMILLE_OVERSHOOT, "OVERSHOOT_MESURE"),
    "carnet_venues.jsonl": (FAMILLE_VENUE, "CROSS_VENUE_BOOK"),
    "dispersion_venues.jsonl": (FAMILLE_DISPERSION, "CROSS_VENUE_DISPERSION"),
    "explorer_tx_tape.jsonl": (FAMILLE_EXPLORER_TX, "EXPLORER_TX"),
    "vault_ledger.jsonl": (FAMILLE_VAULT_LEDGER, "VAULT_LEDGER"),
    "micro_bbo.jsonl": (FAMILLE_MICRO_BBO, "HL_WS_PUBLIC"),
    "micro_l2book.jsonl": (FAMILLE_MICRO_L2, "HL_WS_PUBLIC"),
    "micro_trades.jsonl": (FAMILLE_MICRO_TRADES, "HL_WS_PUBLIC"),
    "candles_5m.jsonl": (FAMILLE_CANDLE, "REST_BACKFILL_5M"),   # runtime/history (backfill_candles_vaults)
}


@dataclass
class StatsCertif:
    """Comptes d'une passe de certification (par flux ou agrégé)."""

    entrees: int = 0
    passes: int = 0
    repares: int = 0
    quarantaine: int = 0
    doublons: int = 0
    raisons: dict[str, int] = field(default_factory=dict)

    def _ajouter_raison(self, raison: str) -> None:
        self.raisons[raison] = self.raisons.get(raison, 0) + 1

    def fusionner(self, autre: "StatsCertif") -> None:
        self.entrees += autre.entrees
        self.passes += autre.passes
        self.repares += autre.repares
        self.quarantaine += autre.quarantaine
        self.doublons += autre.doublons
        for raison, n in autre.raisons.items():
            self.raisons[raison] = self.raisons.get(raison, 0) + n

    def deposes(self) -> int:
        return self.passes + self.repares

    def resume(self) -> dict[str, Any]:
        top = dict(sorted(self.raisons.items(), key=lambda kv: -kv[1])[:10])
        return {
            "entrees": self.entrees,
            "deposes": self.deposes(),
            "passes": self.passes,
            "repares": self.repares,
            "quarantaine": self.quarantaine,
            "doublons": self.doublons,
            "raisons_top": top,
        }


# --------------------------------------------------------------------------- #
# Helpers de réparation / validation (purs, testables)
# --------------------------------------------------------------------------- #


_ROTATION_HORODATEE = re.compile(r"^_\d{10,}\.jsonl(\.gz)?$")


def detecter_famille(nom_fichier: str) -> tuple[str, str] | None:
    """Renvoie (famille, source) depuis un nom de fichier, sinon None."""
    base = str(nom_fichier).replace("\\", "/").rsplit("/", 1)[-1]
    # tolère un suffixe .gz et des rotations ``name.N.jsonl`` / ``name.jsonl.1``
    for connu, info in _FICHIERS_CONNUS.items():
        tronc = connu[:-6]  # sans « .jsonl »
        if base == connu or base.startswith(tronc + ".") or base.startswith(connu + "."):
            return info
        if base.startswith(tronc + "_") and _ROTATION_HORODATEE.match(base[len(tronc):]):
            return info
    return None


def sniffer_famille(record: Any) -> tuple[str, str] | None:
    """Reconnaît la famille d'un enregistrement par son CONTENU (nom ignoré).

    Permet au scan ``--tout`` d'attraper toute donnée du dépôt quel que soit le
    nom du fichier. STRICT : ne classe que si la forme correspond clairement à une
    famille connue ; sinon None (le fichier est ignoré, pas mis en quarantaine).
    """
    if not isinstance(record, dict):
        return None
    # INTÉGRITÉ : une donnée estimée/inférée n'est JAMAIS certifiable comme SAFE.
    if not _source_certifiable(record):
        return None
    sv = record.get("schema_version")
    # Carnet L2 : schéma explicite OU niveaux bid/ask
    if sv == "hypersmart.copy_vault_l2.v1" or ("bids5" in record and "asks5" in record):
        return (FAMILLE_BOOK_L2, "HYPERLIQUID_L2_WS")
    # BBO : schéma dédié OU venue/px/side
    if sv == "hypersmart.copy_vault_bbo.v1" or ("venue" in record and "px" in record and "side" in record):
        return (FAMILLE_BBO, "BBO_TAPE")
    # Trades marché public
    if sv == "hypersmart.copy_vault_trades.v1":
        return (FAMILLE_TRADES, str(record.get("source") or "HYPERLIQUID_TRADES_WS"))
    # Bougies OHLCV
    if sv == "hypersmart.copy_vault_candle.v1":
        return (FAMILLE_CANDLE, str(record.get("source") or "HYPERLIQUID_CANDLE_WS"))
    # Positions leaders
    if sv == "hypersmart.copy_vault_positions.v1" or ("szi" in record and "coin" in record and "vault" in record):
        return (FAMILLE_POSITION, str(record.get("source") or "CLEARINGHOUSE_WS"))
    # Fill : vault + px + sz + un timestamp d'exchange
    a_ts = ("ts_ms" in record) or ("time" in record)
    if "vault" in record and "px" in record and "sz" in record and a_ts:
        src = str(record.get("source") or "")
        if record.get("observed_at_ms") is not None or "POLL" in src.upper() or "WS" in src.upper():
            return (FAMILLE_FILLS_FORWARD, src or "LIVE")
        return (FAMILLE_FILLS_BACKFILL, src or "REST_BACKFILL")
    return None


# --------------------------------------------------------------------------- #
# Certification par famille : (record) -> (record_norm | None, decision, raison)
# --------------------------------------------------------------------------- #

def certifier_fill(
    record: Any, *, source: str, famille: str, now_ms: int,
) -> tuple[dict[str, Any] | None, str, str]:
    """Certifie un fill (forward causal ou backfill). Répare px/sz/coin/signe.

    Replayable/backtestable si : vault+coin présents, px>0, sz>0 finis, timestamp
    d'exchange causal (``ts_ms``|``time`` > 0 et pas dans le futur). Les fills
    forward exigent ``observed_at_ms`` (preuve d'observation causale) ; les
    backfill sont acceptés mais étiquetés non-causaux.
    """
    if not isinstance(record, dict):
        return None, QUARANTAINE, "non_objet"
    repare = False
    out: dict[str, Any] = dict(record)

    vault = str(record.get("vault") or "").strip().lower()
    if not vault.startswith("0x") or len(vault) < 10:
        return None, QUARANTAINE, "vault_absent_ou_invalide"
    out["vault"] = vault

    # Normalisation « normale » (parsing du format brut) = PASS, pas une réparation.
    coin = _canonical_coin(record.get("coin"))
    if not coin:
        return None, QUARANTAINE, "coin_absent"
    out["coin"] = coin

    px = _nombre_fini(record.get("px"))
    if px is None or px <= 0:
        return None, QUARANTAINE, "px_invalide"
    out["px"] = px

    sz = _nombre_fini(record.get("sz"))
    if sz is None or sz <= 0:
        return None, QUARANTAINE, "sz_invalide"
    out["sz"] = sz

    # timestamp d'exchange : ``ts_ms`` (normalisé) ou ``time`` (brut HL)
    ts = _entier_positif(record.get("ts_ms")) or _entier_positif(record.get("time"))
    if ts is None:
        return None, QUARANTAINE, "timestamp_absent"
    if ts > now_ms + _FUTUR_TOLERANCE_MS:
        return None, QUARANTAINE, "timestamp_futur"
    out["ts_ms"] = ts

    # signe : présent ou lisible sur ``side``/``fill_side`` = normal (PASS). Reconstruit
    # depuis ``dir`` (champ secondaire) = véritable RÉPARATION.
    signe = record.get("signe")
    if signe not in (-1, 1):
        signe = _signe_depuis_side(record.get("side")) or _signe_depuis_side(record.get("fill_side"))
        if signe not in (-1, 1):
            signe = _signe_depuis_side(record.get("dir"))
            if signe not in (-1, 1):
                return None, QUARANTAINE, "signe_indeterminable"
            repare = True  # sauvetage : sens reconstruit depuis la direction
    out["signe"] = signe

    est_snapshot = bool(record.get("isSnapshot") or record.get("is_snapshot"))
    if famille == FAMILLE_FILLS_FORWARD and not est_snapshot:
        # un fill forward causal DOIT porter la preuve d'observation.
        obs = _entier_positif(record.get("observed_at_ms"))
        if obs is None:
            # Les fills WebSocket portent ``received_at_ms`` : l'instant RÉEL de réception du
            # message, mesuré par le collecteur. C'est exactement l'instant d'observation (le
            # labo l'accepte déjà ainsi). On le reporte, sans rien inventer ; l'absence des deux
            # champs reste un rejet.
            obs = _entier_positif(record.get("received_at_ms"))
            if obs is None:
                return None, QUARANTAINE, "forward_sans_observed_at_ms"
            out["observation_field"] = "received_at_ms"
            repare = True
        if obs > now_ms + _FUTUR_TOLERANCE_MS:
            return None, QUARANTAINE, "observed_at_ms_futur"
        out["observed_at_ms"] = obs
        out["causal_forward_eligible"] = True
    else:
        out["causal_forward_eligible"] = False
        out.setdefault("is_snapshot", est_snapshot)

    out["source"] = str(record.get("source") or source)
    return out, (REPARE if repare else PASS), ""


def certifier_book(
    record: Any, *, source: str, now_ms: int,
) -> tuple[dict[str, Any] | None, str, str]:
    """Certifie un carnet L2 (déjà au schéma ``hypersmart.copy_vault_l2.v1``).

    Replayable si : bid>0, ask>bid (non croisé), 5 niveaux ordonnés, exchange_ts>0,
    received>=exchange et lag<=MAX_TARGET_LAG_MS (fraîcheur causale).
    """
    if not isinstance(record, dict):
        return None, QUARANTAINE, "non_objet"
    repare = False
    out: dict[str, Any] = dict(record)

    coin = _canonical_coin(record.get("coin"))
    if not coin:
        return None, QUARANTAINE, "coin_absent"
    out["coin"] = coin

    exch = _entier_positif(record.get("exchange_ts_ms"))
    recv = _entier_positif(record.get("received_at_ms"))
    if exch is None or recv is None:
        return None, QUARANTAINE, "timestamp_absent"
    if exch > now_ms + _FUTUR_TOLERANCE_MS:
        return None, QUARANTAINE, "timestamp_futur"
    if recv < exch:
        return None, QUARANTAINE, "received_avant_exchange"
    if recv - exch > MAX_TARGET_LAG_MS:
        return None, QUARANTAINE, "lag_causal_depasse"

    bids = _niveaux(record.get("bids5"), descendant=True)
    asks = _niveaux(record.get("asks5"), descendant=False)
    if bids is None or asks is None:
        return None, QUARANTAINE, "niveaux_l2_invalides"
    if bids[0][0] >= asks[0][0]:
        return None, QUARANTAINE, "marche_croisee"

    # bid/ask de tête : recalcule si absents ou incohérents (réparation)
    bid, ask = bids[0][0], asks[0][0]
    if _nombre_fini(record.get("bid")) != bid or _nombre_fini(record.get("ask")) != ask:
        repare = True
    out["bid"], out["ask"] = bid, ask
    out["bids5"], out["asks5"] = bids, asks
    out["exchange_ts_ms"], out["received_at_ms"] = exch, recv
    out.setdefault("schema_version", "hypersmart.copy_vault_l2.v1")
    out["source"] = str(record.get("source") or source)
    out.setdefault("causal_observation", True)
    return out, (REPARE if repare else PASS), ""


def certifier_bbo(
    record: Any, *, source: str, now_ms: int,
) -> tuple[dict[str, Any] | None, str, str]:
    """Certifie une ligne BBO/trade de venue (repli de prix causal)."""
    if not isinstance(record, dict):
        return None, QUARANTAINE, "non_objet"
    out: dict[str, Any] = dict(record)
    coin = _canonical_coin(record.get("coin"))
    if not coin:
        return None, QUARANTAINE, "coin_absent"
    repare = coin != record.get("coin")
    out["coin"] = coin
    if record.get("px") is None and "bid" not in record and ("bid_px" in record or "ask_px" in record):
        # schéma des lanes GitHub (``hypersmart.copy_vault_bbo.v1``) : mêmes grandeurs, autres noms.
        # Les noms d'origine sont conservés (le labo les lit) ; on ajoute les noms communs.
        record = {**record, "bid": record.get("bid_px"), "ask": record.get("ask_px")}
        if record.get("recv_wall_ts_ms") is None and record.get("received_at_ms") is not None:
            record["recv_wall_ts_ms"] = record.get("received_at_ms")
            out["recv_wall_ts_ms"] = record["recv_wall_ts_ms"]
        if record.get("exchange_ts_ms") is not None:
            out.setdefault("ts_ex", record.get("exchange_ts_ms"))
        out.setdefault("venue", "HL")
    if record.get("px") is None and ("bid" in record or "ask" in record):
        # COTATION (meilleur bid / meilleur ask) : c'est le BBO proprement dit, la donnée qui
        # donne le spread réel. Elle était rejetée « px_invalide » car seule la forme
        # « transaction » (px/sz) était reconnue. Carnet croisé ou taille illisible : rejet.
        bid, ask = _nombre_fini(record.get("bid")), _nombre_fini(record.get("ask"))
        if bid is None or ask is None or bid <= 0 or ask <= 0:
            return None, QUARANTAINE, "bbo_cotation_invalide"
        if ask < bid:
            return None, QUARANTAINE, "bbo_croise"
        for champ in ("bid_sz", "ask_sz"):
            if record.get(champ) is not None:
                taille = _nombre_fini(record.get(champ))
                if taille is None or taille < 0:
                    return None, QUARANTAINE, "bbo_taille_invalide"
                out[champ] = taille
        out["bid"], out["ask"], out["type_ligne"] = bid, ask, "QUOTE"
    else:
        px = _nombre_fini(record.get("px"))
        if px is None or px <= 0:
            return None, QUARANTAINE, "px_invalide"
        sz = _nombre_fini(record.get("sz"))
        if sz is None or sz <= 0:
            return None, QUARANTAINE, "sz_invalide"
        out["px"], out["sz"], out["type_ligne"] = px, sz, "TRADE"
    ts = _entier_positif(record.get("recv_wall_ts_ms")) or _entier_positif(record.get("ts_wall_ms"))
    if ts is None:
        return None, QUARANTAINE, "timestamp_absent"
    if ts > now_ms + _FUTUR_TOLERANCE_MS:
        return None, QUARANTAINE, "timestamp_futur"
    out["recv_wall_ts_ms"] = ts
    out["source"] = str(record.get("source") or record.get("venue") or source)
    return out, (REPARE if repare else PASS), ""


def certifier_trade(record: Any, *, source: str, now_ms: int,
                    ) -> tuple[dict[str, Any] | None, str, str]:
    """Certifie un trade marché public. Replayable si coin, px>0, sz>0, ts causal."""
    if not isinstance(record, dict):
        return None, QUARANTAINE, "non_objet"
    out: dict[str, Any] = dict(record)
    coin = _canonical_coin(record.get("coin"))
    if not coin:
        return None, QUARANTAINE, "coin_absent"
    out["coin"] = coin
    px = _nombre_fini(record.get("price") if record.get("price") is not None else record.get("px"))
    if px is None or px <= 0:
        return None, QUARANTAINE, "px_invalide"
    sz = _nombre_fini(record.get("size") if record.get("size") is not None else record.get("sz"))
    if sz is None or sz <= 0:
        return None, QUARANTAINE, "sz_invalide"
    out["price"], out["size"] = px, sz
    ts = _entier_positif(record.get("exchange_ts_ms")) or _entier_positif(record.get("time"))
    if ts is None:
        return None, QUARANTAINE, "timestamp_absent"
    if ts > now_ms + _FUTUR_TOLERANCE_MS:
        return None, QUARANTAINE, "timestamp_futur"
    out["exchange_ts_ms"] = ts
    out["source"] = str(record.get("source") or source)
    return out, PASS, ""


def certifier_candle(record: Any, *, source: str, now_ms: int,
                     ) -> tuple[dict[str, Any] | None, str, str]:
    """Certifie une bougie OHLCV. Replayable si OHLC cohérents (>0) et ts d'ouverture causal."""
    if not isinstance(record, dict):
        return None, QUARANTAINE, "non_objet"
    out: dict[str, Any] = dict(record)
    coin = _canonical_coin(record.get("coin"))
    if not coin:
        return None, QUARANTAINE, "coin_absent"
    out["coin"] = coin
    repare = False
    if "open" not in record and "o" in record:
        # Format compact du backfill REST ({t_ms, o, h, l, c, v}) : mêmes valeurs, noms normalisés.
        # Ces bougies sont récupérées après coup : factuelles, mais jamais « observées en direct ».
        record = {**record, "open": record.get("o"), "high": record.get("h"), "low": record.get("l"),
                  "close": record.get("c"), "volume": record.get("v"), "open_ts_ms": record.get("t_ms")}
        out.update({"volume": _nombre_fini(record.get("volume")), "causal_forward_eligible": False})
        if not out.get("interval") and str(source).upper().endswith("_5M"):
            out["interval"] = "5m"
        repare = True
    o = _nombre_fini(record.get("open"))
    h = _nombre_fini(record.get("high"))
    l = _nombre_fini(record.get("low"))
    c = _nombre_fini(record.get("close"))
    if None in (o, h, l, c) or min(o, h, l, c) <= 0:
        return None, QUARANTAINE, "ohlc_invalide"
    if h < l or h < o or h < c or l > o or l > c:
        return None, QUARANTAINE, "ohlc_incoherent"
    ts = _entier_positif(record.get("open_ts_ms")) or _entier_positif(record.get("t"))
    if ts is None:
        return None, QUARANTAINE, "timestamp_absent"
    if ts > now_ms + _FUTUR_TOLERANCE_MS:
        return None, QUARANTAINE, "timestamp_futur"
    out["open"], out["high"], out["low"], out["close"] = o, h, l, c
    out["open_ts_ms"] = ts
    out["source"] = str(record.get("source") or source)
    return out, (REPARE if repare else PASS), ""


def certifier_position(record: Any, *, source: str, now_ms: int,
                       ) -> tuple[dict[str, Any] | None, str, str]:
    """Certifie un snapshot de position leader. Replayable si vault+coin, szi fini, ts causal."""
    if not isinstance(record, dict):
        return None, QUARANTAINE, "non_objet"
    out: dict[str, Any] = dict(record)
    vault = str(record.get("vault") or "").strip().lower()
    if not vault.startswith("0x") or len(vault) < 10:
        return None, QUARANTAINE, "vault_absent_ou_invalide"
    out["vault"] = vault
    coin = _canonical_coin(record.get("coin"))
    if not coin:
        return None, QUARANTAINE, "coin_absent"
    out["coin"] = coin
    szi = _nombre_fini(record.get("szi"))
    if szi is None:
        return None, QUARANTAINE, "szi_invalide"
    out["szi"] = szi
    ts = _entier_positif(record.get("received_at_ms")) or _entier_positif(record.get("time"))
    if ts is None:
        return None, QUARANTAINE, "timestamp_absent"
    if ts > now_ms + _FUTUR_TOLERANCE_MS:
        return None, QUARANTAINE, "timestamp_futur"
    out["received_at_ms"] = ts
    out["source"] = str(record.get("source") or source)
    return out, PASS, ""


# --------------------------------------------------------------------------- #
# Identité (déduplication inter-lots / inter-tiers)
# --------------------------------------------------------------------------- #


def identite(record: dict[str, Any], famille: str) -> tuple[Any, ...]:
    """Clé d'identité d'un enregistrement certifié (pour déduplication)."""
    if famille == FAMILLE_SNAPSHOT:
        return ("vault_snapshot", record.get("vault"), record.get("ts_ms"))
    if famille == FAMILLE_EXPLORER_TX:
        return ("explorer_tx", record.get("hash"), record.get("user"), record.get("action_type"),
                record.get("time"))
    if famille in (FAMILLE_MICRO_BBO, FAMILLE_MICRO_L2):
        # la somme de contrôle couvre toute la ligne : deux mises à jour du même instant restent distinctes
        return (famille, record.get("coin"), record.get("ts_ex"), record.get("checksum"))
    if famille == FAMILLE_MICRO_TRADES:
        return ("micro_trade", record.get("coin"), record.get("tid"), record.get("ts_ex"),
                record.get("px"), record.get("sz"), record.get("side"))
    if famille == FAMILLE_VAULT_LEDGER:
        return ("vault_ledger", record.get("vault"), record.get("hash"), record.get("ts_ms"),
                record.get("type"), record.get("delta_usd"))
    if famille in (FAMILLE_FILLS_FORWARD, FAMILLE_FILLS_BACKFILL):
        return (
            "fill", record.get("vault"), record.get("coin"), record.get("ts_ms"),
            record.get("tid"), record.get("hash"), record.get("oid"),
            record.get("px"), record.get("sz"), record.get("signe"),
        )
    if famille == FAMILLE_BOOK_L2:
        return ("book", record.get("coin"), record.get("exchange_ts_ms"),
                record.get("bid"), record.get("ask"))
    if famille == FAMILLE_TRADES:
        return ("trade", record.get("coin"), record.get("exchange_ts_ms"),
                record.get("tid"), record.get("hash"), record.get("price"), record.get("size"))
    if famille == FAMILLE_CANDLE:
        return ("candle", record.get("coin"), record.get("interval"), record.get("open_ts_ms"))
    if famille == FAMILLE_POSITION:
        return ("position", record.get("vault"), record.get("coin"),
                record.get("received_at_ms"), record.get("szi"))
    if famille == FAMILLE_ALLMIDS:
        return ("allmids", record.get("ts_ms"), record.get("n"))
    if famille == FAMILLE_ASSET_CTX:
        return ("assetctx", record.get("coin"), record.get("ts_ms"))
    if famille == FAMILLE_LIQUIDATION:
        return ("liq", record.get("coin"), record.get("ts_ms"),
                record.get("stable_event_id") or record.get("hash"), record.get("tid"))
    if famille == FAMILLE_OVERSHOOT:
        return ("overshoot", record.get("coin"), record.get("ts_ms"), record.get("sens"))
    if famille == FAMILLE_VENUE:
        return ("venue", record.get("coin"), record.get("snapshot_ts_ms"),
                record.get("observation_id"))
    if famille == FAMILLE_DISPERSION:
        return ("disp", record.get("coin"), record.get("ts_ms"))
    # BBO
    return ("bbo", record.get("event_id") or (
        record.get("venue"), record.get("coin"), record.get("ts_ex"), record.get("sequence")))


def certifier_record(
    record: Any, *, famille: str, source: str, now_ms: int,
) -> tuple[dict[str, Any] | None, str, str]:
    """Aiguille vers le certificateur de la famille."""
    # INTÉGRITÉ (défense en profondeur) : une estimation/inférence n'entre jamais SAFE.
    if not _source_certifiable(record):
        return None, QUARANTAINE, "source_non_certifiable_inference"
    if famille == FAMILLE_SNAPSHOT:
        return certifier_snapshot_vault(record, source=source, now_ms=now_ms)
    if famille == FAMILLE_EXPLORER_TX:
        return certifier_explorer_tx(record, source=source, now_ms=now_ms)
    if famille == FAMILLE_MICRO_BBO:
        return certifier_micro_bbo(record, source=source, now_ms=now_ms)
    if famille == FAMILLE_MICRO_L2:
        return certifier_micro_l2(record, source=source, now_ms=now_ms)
    if famille == FAMILLE_MICRO_TRADES:
        return certifier_micro_trade(record, source=source, now_ms=now_ms)
    if famille == FAMILLE_VAULT_LEDGER:
        return certifier_vault_ledger(record, source=source, now_ms=now_ms)
    if famille in (FAMILLE_FILLS_FORWARD, FAMILLE_FILLS_BACKFILL):
        return certifier_fill(record, source=source, famille=famille, now_ms=now_ms)
    if famille == FAMILLE_BOOK_L2:
        return certifier_book(record, source=source, now_ms=now_ms)
    if famille == FAMILLE_BBO:
        return certifier_bbo(record, source=source, now_ms=now_ms)
    if famille == FAMILLE_TRADES:
        return certifier_trade(record, source=source, now_ms=now_ms)
    if famille == FAMILLE_CANDLE:
        return certifier_candle(record, source=source, now_ms=now_ms)
    if famille == FAMILLE_POSITION:
        return certifier_position(record, source=source, now_ms=now_ms)
    if famille == FAMILLE_ALLMIDS:
        return certifier_allmids(record, source=source, now_ms=now_ms)
    if famille == FAMILLE_ASSET_CTX:
        return certifier_asset_ctx(record, source=source, now_ms=now_ms)
    if famille == FAMILLE_LIQUIDATION:
        return certifier_liquidation(record, source=source, now_ms=now_ms)
    if famille == FAMILLE_OVERSHOOT:
        return certifier_overshoot(record, source=source, now_ms=now_ms)
    if famille == FAMILLE_VENUE:
        return certifier_venue(record, source=source, now_ms=now_ms)
    if famille == FAMILLE_DISPERSION:
        return certifier_dispersion(record, source=source, now_ms=now_ms)
    return None, QUARANTAINE, "famille_inconnue"


def certifier_lignes(
    lignes: Iterable[str], *, famille: str, source: str, now_ms: int,
    deja_vus: set | None = None, stats: StatsCertif | None = None,
) -> Iterator[tuple[dict[str, Any] | None, str, str]]:
    """Certifie un flux de lignes JSONL en **streaming**.

    Émet, pour CHAQUE ligne, ``(record_norm|None, decision, raison)`` :
    - ``decision`` ∈ {PASS, REPARE} → ``record_norm`` à déposer ;
    - ``decision == QUARANTAINE`` → ``record_norm is None``, ``raison`` renseignée.
    Déduplique via ``deja_vus`` (identités déjà déposées, tous tiers confondus).
    Met à jour ``stats`` si fourni.
    """
    import json

    vus = deja_vus if deja_vus is not None else set()
    st = stats if stats is not None else StatsCertif()
    for brut in lignes:
        brut = brut.strip()
        if not brut:
            continue
        st.entrees += 1
        try:
            record = json.loads(brut)
        except (ValueError, UnicodeError):
            st.quarantaine += 1
            st._ajouter_raison("json_invalide")
            yield None, QUARANTAINE, "json_invalide"
            continue
        norm, decision, raison = certifier_record(
            record, famille=famille, source=source, now_ms=now_ms,
        )
        if decision == QUARANTAINE:
            st.quarantaine += 1
            st._ajouter_raison(raison or "quarantaine")
            yield None, QUARANTAINE, raison
            continue
        cle = identite(norm, famille)
        if cle in vus:
            st.doublons += 1
            st._ajouter_raison("doublon")
            # un doublon n'est ni déposé ni mis en quarantaine : simplement ignoré.
            yield None, "DOUBLON", "doublon"
            continue
        vus.add(cle)
        if decision == REPARE:
            st.repares += 1
        else:
            st.passes += 1
        yield norm, decision, raison


__all__ = [
    "FAMILLE_FILLS_FORWARD", "FAMILLE_FILLS_BACKFILL", "FAMILLE_BOOK_L2",
    "FAMILLE_BBO", "FAMILLE_SNAPSHOT", "FAMILLE_TRADES", "FAMILLE_CANDLE",
    "FAMILLE_POSITION", "FAMILLE_ALLMIDS", "FAMILLE_ASSET_CTX", "FAMILLE_LIQUIDATION",
    "FAMILLE_OVERSHOOT", "FAMILLE_VENUE", "FAMILLE_DISPERSION",
    "SOURCES_NON_CERTIFIABLES", "PASS", "REPARE", "QUARANTAINE",
    "StatsCertif", "detecter_famille", "sniffer_famille", "certifier_fill", "certifier_book",
    "certifier_bbo", "certifier_trade", "certifier_candle", "certifier_position",
    "certifier_allmids", "certifier_asset_ctx", "certifier_liquidation",
    "certifier_overshoot", "certifier_venue", "certifier_dispersion",
    "certifier_snapshot_vault", "SCHEMA_SNAPSHOT_VAULT", "VERSIONS_CERTIFICATEUR", "version_certificateur",
    "FAMILLE_EXPLORER_TX", "FAMILLE_VAULT_LEDGER", "certifier_explorer_tx", "certifier_vault_ledger",
    "FICHIERS_NON_CERTIFIES", "motif_non_certifie", "nouvellement_accepte",
    "FAMILLE_MICRO_BBO", "FAMILLE_MICRO_L2", "FAMILLE_MICRO_TRADES",
    "certifier_micro_bbo", "certifier_micro_l2", "certifier_micro_trade",
    "certifier_record", "certifier_lignes", "identite", "MAX_TARGET_LAG_MS",
]
