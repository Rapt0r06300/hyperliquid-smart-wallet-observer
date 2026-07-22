"""SOCLE DE COLLECTE FIABLE — le maximum de données, SANS se faire bannir ni stocker de poubelle.

Flo (22/07) : « il nous faut une quantité EXTRAORDINAIRE de données pour trouver les meilleurs
calibrages ». Le CLAUDE.md l'autorise pleinement (collecte publique agressive 24/7). Mais « plus »
n'a de valeur que si c'est FIABLE et PROPRE :

  * se faire couper par une source = MOINS de données -> backoff avec jitter, jamais du hammering ;
  * un doublon gonfle les volumes et fausse un calibrage -> déduplication par clé stable ;
  * une écriture coupée en plein vol corrompt le fichier -> append atomique (flush+fsync) ;
  * une valeur aberrante (mauvais appariement, prix nul) empoisonne la mesure -> porte de qualité ;
  * une donnée sans origine ne se conteste pas -> chaque ligne est estampillée (source, ts, read_only).

Ce module ne fait AUCUN appel réseau : ce sont des primitives PURES, réutilisées par tous les
collecteurs (dispersion, carnet, fills, liquidations). PAPER/READ-ONLY : collecter n'est pas trader.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import time
from pathlib import Path
from typing import Any, Iterable, Sequence


# ─────────────────────────────── déduplication ───────────────────────────────

def cle_dedup(enr: dict, champs: Sequence[str]) -> str:
    """Clé stable et courte d'un enregistrement sur `champs` (ordre fixe). Un champ absent compte
    comme vide — deux enregistrements ne sont « les mêmes » que s'ils coïncident sur TOUS les champs."""
    brut = "\x1f".join(str(enr.get(c, "")) for c in champs)
    return hashlib.sha1(brut.encode("utf-8", "replace")).hexdigest()[:16]


class CacheDedup:
    """Un cache borné des clés déjà vues (FIFO). Borné pour ne jamais grossir sans fin — la
    déduplication protège contre les doublons PROCHES, pas contre l'histoire entière."""

    def __init__(self, maximum: int = 100_000) -> None:
        self.maximum = int(maximum)
        self._vus: dict[str, None] = {}

    def neuf(self, cle: str) -> bool:
        """True si la clé est nouvelle (et l'enregistre). False si déjà vue."""
        if cle in self._vus:
            return False
        self._vus[cle] = None
        if len(self._vus) > self.maximum:
            for vieux in list(self._vus)[: len(self._vus) - self.maximum]:
                self._vus.pop(vieux, None)
        return True

    def filtrer(self, enrs: Iterable[dict], champs: Sequence[str]) -> list[dict]:
        """Ne garde que les enregistrements dont la clé est neuve."""
        return [e for e in enrs if self.neuf(cle_dedup(e, champs))]


# ─────────────────────────────── écriture atomique / append sûr ───────────────────────────────

def append_jsonl(chemin: str | Path, enrs: Sequence[dict], *, fsync: bool = True) -> int:
    """Append JSONL avec flush (+fsync) : une écriture coupée ne laisse pas un fichier à moitié.
    Rend le nombre de lignes écrites. Crée le dossier au besoin."""
    p = Path(chemin)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with p.open("a", encoding="utf-8") as fh:
        for e in enrs:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
            n += 1
        fh.flush()
        if fsync:
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
    return n


def ecrire_atomique(chemin: str | Path, texte: str) -> None:
    """Écrit un fichier ENTIER de façon atomique (tmp + fsync + os.replace) : un lecteur ne voit
    jamais un état intermédiaire. Pour les snapshots/index, pas pour les journaux append-only."""
    p = Path(chemin)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(texte)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    os.replace(tmp, p)


# ─────────────────────────────── politesse réseau (durer 3 jours, pas 3 minutes) ───────────────

def backoff_jitter(tentative: int, *, base_s: float = 0.5, plafond_s: float = 60.0) -> float:
    """Délai d'attente exponentiel AVEC jitter (± 25 %) après un échec réseau/rate-limit. Le
    jitter évite que N collecteurs re-tapent la source à la même seconde (thundering herd)."""
    t = max(0, int(tentative))
    d = min(float(plafond_s), float(base_s) * (2 ** t))
    return round(d * (0.75 + 0.5 * random.random()), 4)


class Limiteur:
    """Un limiteur de débit MINIMAL : au plus 1 action toutes `intervalle_s`. Rester SOUS la
    limite d'une source publique = durer, donc collecter PLUS au total (se faire bannir = 0)."""

    def __init__(self, intervalle_s: float) -> None:
        self.intervalle_s = max(0.0, float(intervalle_s))
        self._dernier = 0.0

    def attente(self, maintenant: float | None = None) -> float:
        """Combien de secondes attendre avant la prochaine action (0 si prête). Met à jour l'horloge."""
        t = time.time() if maintenant is None else float(maintenant)
        reste = self.intervalle_s - (t - self._dernier)
        if reste <= 0:
            self._dernier = t
            return 0.0
        self._dernier = t + reste
        return round(reste, 4)


# ─────────────────────────────── provenance & qualité ───────────────────────────────

def estampiller(enr: dict, *, source: str, maintenant: float | None = None) -> dict:
    """Ajoute la PROVENANCE : source, horodatage de collecte, et les invariants read-only. Une
    donnée sans origine ne se conteste pas plus tard — donc elle finit par mentir."""
    return {**enr, "source": str(source),
            "collecte_ts": round(time.time() if maintenant is None else float(maintenant), 3),
            "read_only": True, "real_execution": False}


def qualite_ok(enr: dict, *, champs_prix: Sequence[str] = (),
               ecart_bps_max: float | None = None, champ_ecart: str = "ecart_prix_bps",
               ts_min: float = 1_577_836_800.0) -> bool:
    """Porte de QUALITÉ (deny-by-default) : rejette ce qui empoisonnerait un calibrage.
      * un prix cité doit être un nombre > 0 (jamais un 0 de remplissage) ;
      * un |écart| au-delà de `ecart_bps_max` = mauvais appariement (mémoire « base aberrante ») ;
      * un horodatage implausible (avant 2020) = fixture/erreur, pas une vraie observation.
    """
    ts = enr.get("collecte_ts") or enr.get("ts")
    if isinstance(ts, (int, float)) and float(ts) < ts_min:
        return False
    for c in champs_prix:
        v = enr.get(c)
        if not isinstance(v, (int, float)) or float(v) <= 0 or float(v) != float(v):
            return False
    if ecart_bps_max is not None:
        e = enr.get(champ_ecart)
        if isinstance(e, (int, float)) and abs(float(e)) > float(ecart_bps_max):
            return False
    return True


def collecter_proprement(enrs: Iterable[dict], *, source: str, champs_cle: Sequence[str],
                         cache: CacheDedup | None = None, **qualite: Any) -> list[dict]:
    """Le pipeline en un appel : estamper la provenance -> porte de qualité -> déduplication.
    Rend les enregistrements PROPRES, prêts à écrire. Rien d'inventé : on ne fait que filtrer."""
    cache = cache if cache is not None else CacheDedup()
    propres: list[dict] = []
    for e in enrs or ():
        est = estampiller(e, source=source)
        if not qualite_ok(est, **qualite):
            continue
        if cache.neuf(cle_dedup(est, champs_cle)):
            propres.append(est)
    return propres


__all__ = ["cle_dedup", "CacheDedup", "append_jsonl", "ecrire_atomique", "backoff_jitter",
           "Limiteur", "estampiller", "qualite_ok", "collecter_proprement"]
