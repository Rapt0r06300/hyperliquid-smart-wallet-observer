"""Garde OVERSHOOT *live* pour le moteur paper (dernier fil du cliquet labo->moteur).

Relie le champion gelé par le labo (son ``overshoot_seuil_bps``) au flux de marché
RÉEL écrit par le collecteur asset_ctx (``runtime/data/asset_ctx_tape.jsonl`` :
une ligne par coin/snapshot, champs ``mark``/``oracle``). Au moment d'ouvrir une
copie, le moteur demande au garde si le coin est en débordement ; si oui, l'ouverture
est refusée.

GARDE-FOUS (identiques au reste du système paper) :
- Read-only : aucun ordre, aucune clé, aucune signature. Ne lit que des fichiers locaux.
- OFF par défaut : si le moteur n'a pas opté (``HL_APPLY_CHAMPION=1``) ou si aucun
  champion n'est déployé, le garde est INERTE et NE LIT MÊME PAS la tape (coût nul).
- Causal : réutilise ``overshoot_signal`` (dernier snapshot ``<= ts``, zéro look-ahead).
- Fail-open : toute erreur (fichier absent, corrompu) => garde inerte, jamais de blocage
  fantôme ni d'exception dans le chemin de décision.
"""
from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hl_observer.backtesting.copy_vault_local_lab import seuil_overshoot_champion
from hl_observer.backtesting.overshoot_signal import (
    build_overshoot_index,
    copie_bloquee,
    overshoot_bps_at,
)

TAPE_REL = ("runtime", "data", "asset_ctx_tape.jsonl")
#: nb de lignes de queue à lire : >= nb de coins d'un snapshot (~235) pour couvrir
#: au moins le dernier snapshot complet. Marge large.
DERNIERES_LIGNES = 600
#: on ne reconstruit l'index qu'au plus toutes les N secondes (poll collecteur = 30 s).
TTL_S = 20.0


@dataclass(frozen=True)
class GardeOvershootLive:
    """Décision overshoot live, immuable. ``seuil_bps is None`` => inerte."""

    seuil_bps: float | None = None
    index: dict[str, tuple[list[int], list[float]]] = field(default_factory=dict)

    def actif(self) -> bool:
        return self.seuil_bps is not None

    def bloque(self, coin: Any, ts_ms: int) -> tuple[bool, float | None]:
        """(bloquer?, overshoot_bps_causal). Inerte => (False, None)."""
        if self.seuil_bps is None:
            return (False, None)
        try:
            ov = overshoot_bps_at(self.index, coin, ts_ms)
            bloquer = copie_bloquee(self.index, coin, ts_ms, seuil_bps=self.seuil_bps)
            return (bool(bloquer), ov)
        except Exception:
            return (False, None)


_INERTE = GardeOvershootLive(seuil_bps=None, index={})
# cache module-level : racine_resolue -> (expire_monotonic_s, garde)
_cache: dict[str, tuple[float, GardeOvershootLive]] = {}


def _lire_tail_jsonl(chemin: Path, n: int) -> list[dict[str, Any]]:
    """Lit (au plus) les ``n`` dernières lignes JSON d'un .jsonl. Fail-soft -> []."""
    try:
        if chemin.is_symlink() or not chemin.is_file():
            return []
        # Lecture bornée : on garde seulement les n dernières lignes en mémoire.
        dernieres: deque[str] = deque(maxlen=n)
        with chemin.open("r", encoding="utf-8", errors="ignore") as handle:
            for ligne in handle:
                ligne = ligne.strip()
                if ligne:
                    dernieres.append(ligne)
        out: list[dict[str, Any]] = []
        for ligne in dernieres:
            try:
                rec = json.loads(ligne)
            except (ValueError, TypeError):
                continue
            if isinstance(rec, dict):
                out.append(rec)
        return out
    except Exception:
        return []


def charger_garde(
    root: str | Path,
    *,
    respecter_opt_in: bool = True,
    maintenant_s: float | None = None,
) -> GardeOvershootLive:
    """Construit (ou réutilise via cache TTL) le garde overshoot live.

    Si non opt-in ou pas de champion => garde INERTE sans lire la tape.
    """
    try:
        racine = Path(root)
        cle = str(racine.resolve())
    except Exception:
        return _INERTE
    now = time.monotonic() if maintenant_s is None else float(maintenant_s)
    hit = _cache.get(cle)
    if hit is not None and now < hit[0]:
        return hit[1]

    # 1) Seuil du champion déployé (déjà gardé par HL_APPLY_CHAMPION dans le loader).
    seuil = seuil_overshoot_champion(racine, respecter_opt_in=respecter_opt_in)
    if seuil is None:
        _cache[cle] = (now + TTL_S, _INERTE)  # inerte : aucune lecture de tape
        return _INERTE

    # 2) Opt-in + champion avec seuil actif -> on lit le flux live et on indexe.
    rows = _lire_tail_jsonl(racine.joinpath(*TAPE_REL), DERNIERES_LIGNES)
    index = build_overshoot_index(rows)
    garde = GardeOvershootLive(seuil_bps=float(seuil), index=index)
    _cache[cle] = (now + TTL_S, garde)
    return garde


def vider_cache() -> None:
    """Pour les tests : force la reconstruction au prochain appel."""
    _cache.clear()


__all__ = [
    "DERNIERES_LIGNES",
    "TTL_S",
    "TAPE_REL",
    "GardeOvershootLive",
    "charger_garde",
    "vider_cache",
]
