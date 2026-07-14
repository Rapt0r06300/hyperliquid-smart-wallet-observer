"""Sécurité & résilience — pur, testé. Exécution du backlog :
scan_for_secrets (IMPROVE-22), no_real_trade_violations (IMPROVE-21, fuzz du garde-fou),
kill_switch_engaged (IMPROVE-23), chaos_wrap (IDEA-91), deterministic_replay (IDEA-100).
Ces outils RENFORCENT l'interdiction d'ordre réel. Aucun ordre, jamais.
"""
from __future__ import annotations

import os
import random
import re

# Motifs de secrets : clé privée PEM, clé hex 32 octets, mots-clés sensibles.
SECRET_PATTERNS = (
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"\b0x[a-fA-F0-9]{64}\b",
    r"(?i)\b(mnemonic|seed[_ ]?phrase|private[_ ]?key)\b\s*[:=]",
)

TRUTHY = {"1", "true", "yes", "on"}
FALSY = {"0", "false", "no", "off"}


def scan_for_secrets(text: str) -> list:
    """Repère tout secret potentiel (clé privée, seed, mnemonic). Aucun ne doit JAMAIS apparaître."""
    hits = []
    for pat in SECRET_PATTERNS:
        for m in re.finditer(pat, text or ""):
            hits.append({"pattern": pat, "match": m.group(0)[:16] + "..."})
    return hits


def no_real_trade_violations(env: dict) -> list:
    """FUZZ du garde-fou : toute config susceptible d'activer un ordre RÉEL est une violation.
    Retourne la liste des violations (vide = sûr)."""
    v = []
    if str(env.get("REAL_MAINNET_TRADING", "false")).strip().lower() in TRUTHY:
        v.append("REAL_MAINNET_TRADING_ENABLED")
    if str(env.get("TESTNET_ONLY", "true")).strip().lower() in FALSY:
        v.append("TESTNET_ONLY_DISABLED")
    if str(env.get("ENABLE_REAL_ORDERS", "false")).strip().lower() in TRUTHY:
        v.append("REAL_ORDERS_ENABLED")
    if str(env.get("HYPERSMART_ALLOW_EXCHANGE_ENDPOINT", "false")).strip().lower() in TRUTHY:
        v.append("EXCHANGE_ENDPOINT_ENABLED")
    return v


def kill_switch_engaged(stop_file: str) -> bool:
    """True si le fichier d'arrêt existe -> tout doit s'arrêter proprement."""
    return os.path.exists(stop_file)


def chaos_wrap(fn, *, failure_rate: float = 0.3, seed: int = 0):
    """Chaos engineering : injecte des pannes déterministes pour tester la résilience."""
    rng = random.Random(seed)

    def wrapped(*args, **kwargs):
        if rng.random() < float(failure_rate):
            raise RuntimeError("CHAOS_INJECTED_FAILURE")
        return fn(*args, **kwargs)

    return wrapped


def deterministic_replay(events, handler, *, initial: dict | None = None) -> dict:
    """Rejoue une séquence d'événements -> état final IDENTIQUE à chaque exécution (auditabilité)."""
    state = dict(initial or {})
    for e in events:
        state = handler(state, e)
    return state
