"""LES COINS QU'ON REGARDE VRAIMENT -- et pourquoi cette liste etait VIDE (2026-07-11).

LE BUG, ET IL A ANNULE TOUT LE RESTE.

Le poller de carnet L2 (`l2_snapshot_cache._loop`) demandait sa liste de coins a
`DEFAULT_EDGE_TREND_RECORDER.coins()`. Or `record_edge_observation()` -- la seule fonction qui
remplit ce recorder -- **n'est appelee NULLE PART dans tout le code**. Elle est exportee dans
`__all__`, et c'est tout.

Consequence en chaine :

    recorder vide -> coins() rend []  ->  le poller sonde une liste VIDE
                                      ->  le carnet L2 n'est JAMAIS recupere
                                      ->  live_costs_for(coin) ne trouve jamais rien
                                      ->  spread/slippage/profondeur retombent sur des CONSTANTES
                                          (6 bps, 6 bps, 50 000 $) -- identiques pour BTC et pour
                                          un meme coin illiquide
                                      ->  et aucune donnee de carnet n'est enregistree, donc le
                                          market making est INTESTABLE.

Le flag `HYPERSMART_V26_BOOK_POLLER=1` etait allume. Le code etait cable. Le recorder etait branche.
**Et rien ne se passait**, parce qu'une liste vide ne fait pas de bruit.

C'est le meme motif que les autres pieges de ce projet : une capacite presente, un interrupteur
allume, et une donnee absente qui ne se plaint pas.

CE MODULE : un registre explicite des coins d'interet, alimente la ou les coins sont REELLEMENT
observes (signaux de leaders, candidats). Borne, avec TTL, thread-safe -- et surtout **il sait dire
qu'il est vide**, au lieu de le taire.

PUR (sauf l'horloge, injectable). Aucun ordre reel.
"""
from __future__ import annotations

import threading
import time
from typing import Any

# Bornes : un registre non borne finirait par faire sonder 300 marches toutes les 30 s.
MAX_COINS = 200
TTL_S = 900.0                      # un coin plus vu depuis 15 min sort du radar

_lock = threading.Lock()
_vus: dict[str, float] = {}        # coin -> derniere observation (epoch s)


def note_coin(coin: str, *, now_s: float | None = None) -> bool:
    """« On vient de voir ce marche. » Appele la ou un signal/candidat existe VRAIMENT."""
    c = str(coin or "").strip().upper()
    if not c:
        return False
    t = float(now_s if now_s is not None else time.time())
    with _lock:
        _vus[c] = t
        if len(_vus) > MAX_COINS:
            # on jette les plus anciens, jamais les plus recents
            for vieux, _ in sorted(_vus.items(), key=lambda kv: kv[1])[: len(_vus) - MAX_COINS]:
                _vus.pop(vieux, None)
    return True


def note_coins(coins: Any, *, now_s: float | None = None) -> int:
    n = 0
    for c in (coins or []):
        if note_coin(c, now_s=now_s):
            n += 1
    return n


def coins(*, limit: int = 20, now_s: float | None = None) -> list[str]:
    """Les coins vus recemment, du PLUS RECENT au plus ancien. TTL applique."""
    t = float(now_s if now_s is not None else time.time())
    with _lock:
        vivants = [(c, ts) for c, ts in _vus.items() if (t - ts) <= TTL_S]
    vivants.sort(key=lambda kv: -kv[1])
    return [c for c, _ in vivants[: max(0, int(limit))]]


def is_empty(*, now_s: float | None = None) -> bool:
    return not coins(limit=1, now_s=now_s)


def health(*, now_s: float | None = None) -> dict[str, Any]:
    """L'ETAT VIDE DOIT ETRE VISIBLE. C'est exactement ce qui a manque pendant des semaines."""
    actifs = coins(limit=MAX_COINS, now_s=now_s)
    return {
        "n_coins": len(actifs),
        "vide": not actifs,
        # Si `vide` est vrai en plein run, le carnet n'est PAS collecte et les couts sont des
        # constantes. Ce n'est pas un detail d'observabilite : c'est un moteur a l'arret.
        "consequence_si_vide": (
            "aucun carnet L2 collecte -> spread/slippage/profondeur = constantes -> "
            "les gates de liquidite et de cout ne mesurent RIEN"
        ),
        "coins": actifs[:20],
        "real_execution": False,
    }


def clear() -> None:
    with _lock:
        _vus.clear()


__all__ = ["MAX_COINS", "TTL_S", "clear", "coins", "health", "is_empty", "note_coin", "note_coins"]
