"""Cluster W — DOCTEUR REPLAY : rendre le replay A/B DIGNE DE CONFIANCE.

CAUSE RACINE du « 1 sur 1M » (18/07) : le recorder écrit des shards PAR-PID
(`candidates.<pid>.jsonl`, `marks.<pid>.jsonl`) mais la recherche lisait le fichier MONO
`candidates.jsonl` (vide/périmé) via `load_jsonl` → 0 candidat → `prefilter_candidates` jette
tout → 1 faux gagnant dégénéré présenté comme « la meilleure simulation ».

Ce module :
  * **W1/W2** `charger_replay_depuis_base` AGRÈGE tous les shards (+ legacy + archive) via
    `read_replay_lines` — c'est CE chargement qui manquait ;
  * **W6** `diagnostiquer` mesure la santé des données (volumes, coins, couverture marks) ;
  * **W3** `exiger_suffisant` ÉCHOUE BRUYAMMENT (exception) sur données insuffisantes — jamais un
    résultat fabriqué ;
  * **W8** `gagnant_robuste` refuse un « gagnant » à trop peu de trades (chance ≠ edge) ;
  * **W9** `trier_deterministe` ordonne les candidats de façon reproductible ;
  * **W10** `cout_total_bps` somme les coûts réels par candidat (fees+spread+slippage+dégradation).

REPLAY strict : lit des fichiers, ne renvoie qu'un rapport, ne touche JAMAIS au ledger live,
n'émet aucun ordre. Les métriques sont descriptives — jamais une promesse de PnL.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from hl_observer.runtime.replay_recorder import read_replay_lines

# Seuils de crédibilité statistique. Sous ces planchers, une recherche A/B ne veut RIEN dire.
MIN_CANDIDATS = 200
MIN_MARKS = 500
MIN_COINS = 2
MIN_COUVERTURE_MARKS = 0.5        # < 50% des candidats ont des marks -> inexploitable
MIN_TRADES_GAGNANT = 30          # un "gagnant" à < 30 trades = chance, pas edge (le "1 sur 1M")


class DonneesReplayInsuffisantes(RuntimeError):
    """Levée quand le replay n'a PAS assez de données pour un résultat crédible (W3, échec bruyant)."""


@dataclass(frozen=True)
class RapportSante:
    n_candidats: int
    n_marks: int
    n_coins_candidats: int
    n_coins_marks: int
    couverture_marks: float
    suffisant: bool
    raisons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_candidats": self.n_candidats, "n_marks": self.n_marks,
            "n_coins_candidats": self.n_coins_candidats, "n_coins_marks": self.n_coins_marks,
            "couverture_marks": self.couverture_marks, "suffisant": self.suffisant,
            "raisons": list(self.raisons),
        }


def _coin(row: dict) -> str:
    return str(row.get("coin") or "").upper()


def charger_replay_depuis_base(base: str) -> tuple[list[dict], list[dict]]:
    """(candidates, marks) AGRÉGÉS depuis TOUS les shards par-PID (+ legacy + archive). W1/W2 :
    c'est CE chargement — pas `load_jsonl` sur un fichier mono — qui rend les données visibles."""
    cands = [r for r in read_replay_lines(base, "candidates.jsonl", include_archive=True) if isinstance(r, dict)]
    marks = [r for r in read_replay_lines(base, "marks.jsonl", include_archive=True) if isinstance(r, dict)]
    return cands, marks


def diagnostiquer(candidates: Iterable[dict], marks: Iterable[dict], *,
                  min_candidats: int = MIN_CANDIDATS, min_marks: int = MIN_MARKS,
                  min_coins: int = MIN_COINS, min_couverture: float = MIN_COUVERTURE_MARKS) -> RapportSante:
    """W6 — santé des données. Un candidat n'est exploitable que si son coin a des marks."""
    cands = [c for c in candidates if isinstance(c, dict)]
    mks = [m for m in marks if isinstance(m, dict)]
    coins_c = {_coin(c) for c in cands if _coin(c)}
    coins_m = {_coin(m) for m in mks if _coin(m)}
    couverture = 0.0
    if cands:
        avec_marks = sum(1 for c in cands if _coin(c) in coins_m)
        couverture = round(avec_marks / len(cands), 4)
    raisons: list[str] = []
    if len(cands) < int(min_candidats):
        raisons.append(f"CANDIDATS_INSUFFISANTS<{min_candidats}")
    if len(mks) < int(min_marks):
        raisons.append(f"MARKS_INSUFFISANTS<{min_marks}")
    if len(coins_c) < int(min_coins):
        raisons.append(f"COINS_INSUFFISANTS<{min_coins}")
    if couverture < float(min_couverture):
        raisons.append(f"COUVERTURE_MARKS<{int(min_couverture*100)}%")
    return RapportSante(len(cands), len(mks), len(coins_c), len(coins_m), couverture,
                        not raisons, tuple(raisons))


def exiger_suffisant(rapport: RapportSante) -> None:
    """W3 — échec BRUYANT. Aucune recherche/rapport sur données insuffisantes : on lève."""
    if not rapport.suffisant:
        raise DonneesReplayInsuffisantes("; ".join(rapport.raisons) or "DONNEES_REPLAY_INSUFFISANTES")


def diagnostiquer_base(base: str, **kw) -> RapportSante:
    """W6 pratique : agrège les shards puis diagnostique, en une passe."""
    cands, marks = charger_replay_depuis_base(base)
    return diagnostiquer(cands, marks, **kw)


def gagnant_robuste(n_trades_gagnant: int, *, min_trades: int = MIN_TRADES_GAGNANT) -> bool:
    """W8 — un gagnant crédible a >= min_trades. En dessous, c'est de la chance (le « 1 sur 1M »)."""
    try:
        return int(n_trades_gagnant) >= int(min_trades)
    except (TypeError, ValueError):
        return False


def trier_deterministe(candidates: Iterable[dict]) -> list[dict]:
    """W9 — ordre reproductible : par (recorded_at, coin, ts). Deux runs = même ordre = même résultat."""
    def cle(c: dict) -> tuple[float, str, float]:
        return (float(c.get("recorded_at") or 0.0), _coin(c), float(c.get("ts") or 0.0))
    return sorted((c for c in candidates if isinstance(c, dict)), key=cle)


def cout_total_bps(*, fees_bps: float = 0.0, spread_bps: float = 0.0, slippage_bps: float = 0.0,
                   copy_degradation_bps: float = 0.0) -> float:
    """W10 — coût réel par candidat = somme des composantes (pas un forfait plat). >= 0."""
    return max(0.0, float(fees_bps) + float(spread_bps) + float(slippage_bps) + float(copy_degradation_bps))


def format_rapport(rapport: RapportSante) -> str:
    """W12 — rapport lisible (console/dashboard)."""
    etat = "SUFFISANT ✓" if rapport.suffisant else "INSUFFISANT ✗"
    lignes = [
        f"DOCTEUR REPLAY — {etat}",
        f"  candidats : {rapport.n_candidats}  (coins {rapport.n_coins_candidats})",
        f"  marks     : {rapport.n_marks}  (coins {rapport.n_coins_marks})",
        f"  couverture marks : {rapport.couverture_marks:.0%}",
    ]
    if rapport.raisons:
        lignes.append("  raisons   : " + ", ".join(rapport.raisons))
    return "\n".join(lignes)


__all__ = [
    "DonneesReplayInsuffisantes", "RapportSante", "charger_replay_depuis_base", "diagnostiquer",
    "diagnostiquer_base", "exiger_suffisant", "gagnant_robuste", "trier_deterministe",
    "cout_total_bps", "format_rapport", "MIN_CANDIDATS", "MIN_MARKS", "MIN_COINS",
    "MIN_COUVERTURE_MARKS", "MIN_TRADES_GAGNANT",
]
