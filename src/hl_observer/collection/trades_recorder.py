"""LE FLUX REEL : QUI TRAVERSE LE SPREAD, ET DE QUEL COTE (2026-07-12).

POURQUOI CE MODULE EXISTE.

Le carnet L2 nous a donne 10 marches candidats au market making (spread > frais, profondeur
suffisante, toxicite acceptable). Mais un carnet ne dit PAS l'essentiel :

    UN MARKET MAKER GAGNE = spread x VOLUME ECHANGE CONTRE LUI.

Un spread de 49 bps sur un marche que PERSONNE ne traverse ne rapporte RIEN. On ne capture pas
le spread : on porte l'inventaire d'un coin illiquide, et on attend.

Le canal `trades` d'Hyperliquid donne chaque transaction publique : prix, taille, cote agresseur.
C'est la SEULE source qui reponde a :

  * combien de fois par minute quelqu'un traverse le spread ?
  * de quel cote (achete a l'ask / vend au bid) ?
  * le prix va-t-il CONTRE moi juste apres m'avoir rempli ? (selection adverse -- ce qui tue
    les market makers, bien avant les frais)

PUR : le parsing et l'agregation ne font aucune I/O. Le runner reseau est separe et
explicitement opt-in.

LECTURE SEULE. Canal public. Aucune cle, aucune signature, aucun ordre. JAMAIS.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

WS_URL_PUBLIC = "wss://api.hyperliquid.xyz/ws"
ENV_ACTIF = "HYPERSMART_RECORD_TRADES"
FICHIER = "trades"

# Borne dure : on n'ecrit jamais un fichier sans fin.
MAX_OCTETS = 200 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Trade:
    """Une transaction publique. `agresseur` = le cote qui a TRAVERSE le spread."""

    coin: str
    ts_ms: int
    prix: float
    taille: float
    agresseur: str          # "BUY" (a pris l'ask) | "SELL" (a tape le bid)
    notionnel_usd: float
    # PIEGE (2026-07-12) : a la souscription, Hyperliquid renvoie les DERNIERS trades.
    # C'est de l'HISTORIQUE, pas du flux. Le confondre avec du temps reel gonfle les debits
    # et fabrique un volume qui n'existe pas. On le MARQUE, et l'analyse l'exclut.
    snapshot: bool = False
    # L'IDENTIFIANT DE TRADE. Indispensable des qu'on RECONNECTE : a chaque re-souscription,
    # Hyperliquid renvoie les derniers trades. Sans `tid`, on les recompterait -- et on
    # fabriquerait du volume a chaque coupure reseau. 0 = absent du message.
    tid: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "coin": self.coin,
            "ts": self.ts_ms / 1000.0,
            "px": self.prix,
            "sz": self.taille,
            "aggressor": self.agresseur,
            "notional_usd": round(self.notionnel_usd, 6),
            "snapshot": self.snapshot,
            "tid": self.tid,
        }

    @property
    def cle(self) -> tuple:
        """Identite d'un trade, pour la deduplication. `tid` s'il existe, sinon le quadruplet."""
        if self.tid:
            return ("tid", self.tid)
        return ("brut", self.coin, self.ts_ms, self.prix, self.taille, self.agresseur)


def message_abonnement(coins: Iterable[str]) -> list[dict[str, Any]]:
    """Les messages d'abonnement au canal PUBLIC `trades`. Un par marche."""
    out = []
    for c in coins:
        c = str(c or "").strip().upper()
        if c:
            out.append({"method": "subscribe", "subscription": {"type": "trades", "coin": c}})
    return out


def parse_trade(msg: Mapping[str, Any], *, snapshot: bool = False) -> list[Trade]:
    """Extrait les trades d'un message WS. Un message peut en contenir plusieurs.

    Format Hyperliquid : {"channel": "trades", "data": [{"coin","side","px","sz","time"}, ...]}
    `side` = "B" (l'agresseur a ACHETE, il a pris l'ask) | "A" (il a VENDU, il a tape le bid).
    """
    if not isinstance(msg, Mapping) or str(msg.get("channel") or "") != "trades":
        return []
    data = msg.get("data")
    if not isinstance(data, list):
        return []

    out: list[Trade] = []
    for row in data:
        if not isinstance(row, Mapping):
            continue
        coin = str(row.get("coin") or "").upper()
        if not coin:
            continue
        try:
            px = float(row.get("px"))
            sz = float(row.get("sz"))
            ts = int(row.get("time"))
        except (TypeError, ValueError):
            continue                      # donnee incomplete -> on n'invente rien
        if px <= 0 or sz <= 0 or ts <= 0:
            continue
        cote = str(row.get("side") or "").upper()
        if cote in {"B", "BUY"}:
            agresseur = "BUY"
        elif cote in {"A", "S", "SELL"}:
            agresseur = "SELL"
        else:
            continue                      # cote inconnu -> le trade est INUTILISABLE pour un MM
        try:
            tid = int(row.get("tid") or 0)
        except (TypeError, ValueError):
            tid = 0
        out.append(Trade(coin=coin, ts_ms=ts, prix=px, taille=sz,
                         agresseur=agresseur, notionnel_usd=px * sz, snapshot=snapshot,
                         tid=tid))
    return out


def actif() -> bool:
    return str(os.environ.get(ENV_ACTIF, "0")).strip().lower() in {"1", "true", "yes", "on"}


def ecrire(base_dir: str, trades: Iterable[Trade]) -> int:
    """Append borne. Jamais de fichier sans fin."""
    lignes = [json.dumps(t.as_dict(), ensure_ascii=False) for t in trades]
    if not lignes:
        return 0
    d = Path(base_dir)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{FICHIER}.{os.getpid()}.jsonl"
    try:
        if p.exists() and p.stat().st_size > MAX_OCTETS:
            return 0                      # borne atteinte : on arrete d'ecrire, on ne tronque pas
        with p.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lignes) + "\n")
    except OSError:
        return 0
    return len(lignes)


# ---------------------------------------------------------------------- le runner reseau

MAX_TIDS_MEMORISES = 400_000       # borne memoire du dedupe (~4 h de flux large, largement)


async def enregistrer(coins: list[str], base_dir: str, duree_s: float = 3600.0) -> dict[str, Any]:  # pragma: no cover
    """Ecoute le canal PUBLIC `trades` et enregistre. LECTURE SEULE, opt-in.

    Aucun message d'ordre n'est jamais envoye : les seuls messages sortants sont des
    `subscribe` au canal public `trades`.

    UNE COUPURE RESEAU NE DOIT PAS TUER LA MESURE (corrige le 2026-07-12)
    --------------------------------------------------------------------
    La version precedente faisait `except: break` : **au premier drop du WebSocket, l'ecoute
    s'arretait -- et rendait quand meme un "verdict"**, calcule sur les 12 minutes captees avant
    la coupure. Sur une fenetre de 4 h, un drop est quasi certain. On aurait donc tranche KAITO
    sur une fraction de la donnee, sans jamais le savoir.

    Desormais : reconnexion avec backoff, re-souscription, et **deduplication par `tid`** --
    car a chaque re-souscription Hyperliquid RENVOIE les derniers trades. Sans dedupe, chaque
    coupure fabriquerait du volume. Le nombre de reconnexions est REMONTE dans le rapport :
    une mesure qui a survecu a 30 coupures n'est pas la meme qu'une mesure continue.
    """
    import websockets

    debut = time.time()
    n_total = 0
    n_doublons = 0
    n_reconnexions = 0
    par_coin: dict[str, int] = {}
    vus_tid: set[tuple] = set()

    while (time.time() - debut) < duree_s:
        restant = duree_s - (time.time() - debut)
        if restant <= 0:
            break
        try:
            async with websockets.connect(
                WS_URL_PUBLIC, ping_interval=20, ping_timeout=20, close_timeout=5
            ) as ws:
                for sub in message_abonnement(coins):
                    await ws.send(json.dumps(sub))

                # 1er message d'un coin SUR CETTE CONNEXION = son snapshot (historique, pas du
                # flux). A la reconnexion, Hyperliquid re-envoie : le dedupe par tid l'absorbe.
                vus_coin: set[str] = set()

                while (time.time() - debut) < duree_s:
                    brut = await ws.recv()
                    try:
                        msg = json.loads(brut)
                    except (TypeError, ValueError):
                        continue

                    data = msg.get("data") if isinstance(msg, dict) else None
                    coin_msg = ""
                    if isinstance(data, list) and data and isinstance(data[0], dict):
                        coin_msg = str(data[0].get("coin") or "").upper()
                    est_snapshot = bool(coin_msg) and coin_msg not in vus_coin
                    if coin_msg:
                        vus_coin.add(coin_msg)

                    trades = parse_trade(msg, snapshot=est_snapshot)
                    if not trades:
                        continue

                    neufs = []
                    for t in trades:
                        k = t.cle
                        if k in vus_tid:
                            n_doublons += 1
                            continue
                        if len(vus_tid) < MAX_TIDS_MEMORISES:
                            vus_tid.add(k)
                        neufs.append(t)
                    if not neufs:
                        continue

                    n_total += ecrire(base_dir, neufs)
                    for t in neufs:
                        par_coin[t.coin] = par_coin.get(t.coin, 0) + 1
        except Exception:
            # coupure, timeout, DNS, reset : on RECONNECTE. On ne rend jamais un verdict
            # silencieusement ampute.
            if (time.time() - debut) >= duree_s:
                break
            n_reconnexions += 1
            import asyncio as _aio
            await _aio.sleep(min(30.0, 2.0 * min(n_reconnexions, 8)))

    return {
        "trades_enregistres": n_total,
        "doublons_ignores": n_doublons,
        "reconnexions": n_reconnexions,
        "par_coin": par_coin,
        "duree_s": round(time.time() - debut, 1),
        "read_only": True,
        "real_execution": False,
    }


__all__ = [
    "ENV_ACTIF", "MAX_OCTETS", "WS_URL_PUBLIC",
    "Trade", "actif", "ecrire", "enregistrer", "message_abonnement", "parse_trade",
]
