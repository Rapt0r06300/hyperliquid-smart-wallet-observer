"""Étape 2/3 — joindre la profondeur exécutable aux épisodes (lecture seule, 0 réseau, 0 ordre).

Sans capacité, tout classement de stratégies est une extrapolation : un edge de 20 bps sur 50 $ et le même
edge sur 50 000 $ ne valent pas la même chose, et rien dans le PnL ne le dit.

Ce module joint à chaque épisode le **carnet causal** — le dernier carnet observé **à ou avant** l'ouverture,
jamais après. Un carnet postérieur donnerait une capacité que le décideur ne pouvait pas connaître : ce
serait du lookahead déguisé en mesure de liquidité.

Trois refus explicites :
  • aucun carnet à ou avant l'épisode ⇒ `capacite_usd = None`, épisode compté `SANS_CARNET_CAUSAL` ;
  • carnet trop vieux (au-delà de `age_max_ms`) ⇒ `CARNET_PERIME`, pas une capacité approchée ;
  • la source actuelle ne porte que le **haut de carnet** ⇒ la mesure est étiquetée `TOP_OF_BOOK_ONLY`,
    jamais présentée comme une capacité multi-niveaux.

`fill_ratio` est borné à 1.0 : une capacité supérieure au notionnel ne « remplit » pas plus que demandé.
"""
from __future__ import annotations

import json
from bisect import bisect_right
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "hypersmart.episode_capacity.v1"
CARNET_RELPATH = Path("runtime") / "data" / "carnet_venues.jsonl"
AGE_MAX_MS_DEFAUT = 300_000.0          # 5 min : au-delà, la profondeur affichée n'engage plus rien
QUALITE = "TOP_OF_BOOK_ONLY"


def _ts_ms(ligne: Mapping[str, Any]) -> int | None:
    """`collecte_ts` est en secondes flottantes ; `ts_ms` en millisecondes. Aucun repli sur `now`."""
    for cle, facteur in (("ts_ms", 1.0), ("collecte_ts", 1000.0)):
        v = ligne.get(cle)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            f = float(v) * facteur
            if f == f and f > 0:
                return int(f)
    return None


def _taille_usd(ligne: Mapping[str, Any]) -> float | None:
    v = ligne.get("taille_min_usd")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        f = float(v)
        if f == f and f > 0:
            return f
    return None


def charger_carnets(chemin: Path | str, *, coins: Iterable[str] | None = None,
                    max_lignes: int = 400_000) -> dict[str, dict[str, list]]:
    """Index {coin: {"ts": [...trié...], "taille": [...]}}. Les lignes illisibles sont ignorées."""
    voulus = {str(c).upper() for c in coins} if coins else None
    brut: dict[str, list[tuple[int, float]]] = {}
    try:
        with Path(chemin).open("r", encoding="utf-8", errors="replace") as fh:
            for i, ligne in enumerate(fh):
                if i >= max_lignes:
                    break
                ligne = ligne.strip()
                if not ligne:
                    continue
                try:
                    row = json.loads(ligne)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                coin = str(row.get("coin") or "").upper()
                if not coin or (voulus is not None and coin not in voulus):
                    continue
                ts, taille = _ts_ms(row), _taille_usd(row)
                if ts is None or taille is None:
                    continue
                brut.setdefault(coin, []).append((ts, taille))
    except OSError:
        return {}
    index: dict[str, dict[str, list]] = {}
    for coin, paires in brut.items():
        paires.sort(key=lambda p: p[0])
        index[coin] = {"ts": [p[0] for p in paires], "taille": [p[1] for p in paires]}
    return index


def carnet_causal(index: Mapping[str, Mapping[str, Sequence]], coin: str, ts_ms: Any,
                  *, age_max_ms: float = AGE_MAX_MS_DEFAUT) -> dict[str, Any]:
    """Dernier carnet **à ou avant** `ts_ms`. Jamais un carnet postérieur, même s'il est plus proche."""
    if not isinstance(ts_ms, (int, float)) or isinstance(ts_ms, bool):
        return {"taille_usd": None, "statut": "HORODATAGE_EPISODE_ABSENT", "age_ms": None}
    bloc = index.get(str(coin).upper())
    if not bloc or not bloc.get("ts"):
        return {"taille_usd": None, "statut": "SANS_CARNET_CAUSAL", "age_ms": None}
    temps = bloc["ts"]
    i = bisect_right(temps, int(ts_ms)) - 1
    if i < 0:
        return {"taille_usd": None, "statut": "SANS_CARNET_CAUSAL", "age_ms": None}
    age = float(ts_ms) - float(temps[i])
    if age > float(age_max_ms):
        return {"taille_usd": None, "statut": "CARNET_PERIME", "age_ms": round(age, 1)}
    return {"taille_usd": float(bloc["taille"][i]), "statut": "OK", "age_ms": round(age, 1),
            "carnet_ts_ms": int(temps[i]), "qualite": QUALITE}


def capacite_episode(episode: Any, index: Mapping[str, Mapping[str, Sequence]],
                     *, age_max_ms: float = AGE_MAX_MS_DEFAUT) -> dict[str, Any]:
    """Capacité et `fill_ratio` d'un épisode. Sans carnet causal : `None`, jamais une estimation."""
    coin = getattr(episode, "coin", None) or (episode.get("coin") if isinstance(episode, dict) else None)
    ts = getattr(episode, "ts_open_ms", None)
    if ts is None and isinstance(episode, dict):
        ts = episode.get("ts_open_ms")
    notional = getattr(episode, "notional_usd", None)
    if notional is None and isinstance(episode, dict):
        notional = episode.get("notional_usd")

    carnet = carnet_causal(index, str(coin or ""), ts, age_max_ms=age_max_ms)
    capacite = carnet["taille_usd"]
    ratio = None
    if capacite is not None and isinstance(notional, (int, float)) and float(notional) > 0:
        ratio = round(min(1.0, capacite / float(notional)), 6)
    return {"coin": coin, "capacite_usd": capacite, "fill_ratio": ratio,
            "statut": carnet["statut"], "age_carnet_ms": carnet.get("age_ms"),
            "qualite": carnet.get("qualite")}


def enrichir_episodes(episodes: Sequence[Any], index: Mapping[str, Mapping[str, Sequence]],
                      *, age_max_ms: float = AGE_MAX_MS_DEFAUT) -> dict[str, Any]:
    """Agrège la capacité sur un lot d'épisodes, en nommant ce qui n'a pas pu être joint."""
    details = [capacite_episode(e, index, age_max_ms=age_max_ms) for e in episodes]
    mesures = [d for d in details if d["capacite_usd"] is not None]
    motifs: dict[str, int] = {}
    for d in details:
        if d["capacite_usd"] is None:
            motifs[d["statut"]] = motifs.get(d["statut"], 0) + 1

    def _mediane(valeurs: list[float]) -> float | None:
        if not valeurs:
            return None
        tries = sorted(valeurs)
        milieu = len(tries) // 2
        return round(tries[milieu] if len(tries) % 2 else (tries[milieu - 1] + tries[milieu]) / 2.0, 6)

    ratios = [d["fill_ratio"] for d in mesures if d["fill_ratio"] is not None]
    return {
        "schema_version": SCHEMA_VERSION,
        "n_episodes": len(details),
        "n_avec_carnet_causal": len(mesures),
        "couverture": round(len(mesures) / len(details), 4) if details else None,
        "capacite_mediane_usd": _mediane([d["capacite_usd"] for d in mesures]),
        "fill_ratio_median": _mediane(ratios),
        "fill_ratio_min": min(ratios) if ratios else None,
        "motifs_non_joints": motifs,
        "qualite": QUALITE,
        "note": "haut de carnet uniquement : une capacite multi-niveaux exige la tape L2",
        "details": details,
    }


__all__ = ["SCHEMA_VERSION", "CARNET_RELPATH", "AGE_MAX_MS_DEFAUT", "QUALITE",
           "charger_carnets", "carnet_causal", "capacite_episode", "enrichir_episodes"]
