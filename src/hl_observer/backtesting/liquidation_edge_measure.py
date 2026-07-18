"""#3 / #530 — MESURE de l'edge post-liquidation (la dernière piste non testée).

L'idée (la seule non réfutée) : un trader LIQUIDÉ est FORCÉ — long liquidé = VENTE forcée, short
liquidé = ACHAT forcé. Il ne CHOISIT pas. Ce flux forcé pousse le prix puis s'ÉPUISE ; la direction
RELÂCHÉE est l'opposé (longs liquidés → vente finie → le HAUT est relâché). On MESURE : entrer dans
la direction relâchée juste après la purge rapporte-t-il un edge NET après coûts ?

Ce module ne PROMET rien. Il MESURE sur des liquidations RÉELLES enregistrées + le chemin de prix
réel qui suit. Données insuffisantes → verdict INSUFFISANT (jamais un edge fabriqué — leçon du
« 1 sur 1M »). Verdict EDGE seulement si net moyen > 0 ET profit factor > 1 ET assez d'événements.
MESURE only : lit des données, aucun ordre, aucune signature. Un edge mesuré n'est pas une promesse.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

COUT_ALLER_RETOUR_BPS = 12.0     # entrée+sortie taker (frais+spread+slippage), cohérent avec le replay
MIN_EVENEMENTS = 50              # sous ce seuil, aucune conclusion crédible (données insuffisantes)


class DonneesLiquidationInsuffisantes(RuntimeError):
    """Levée si on tente de conclure sur trop peu d'événements mesurables (anti edge fabriqué)."""


@dataclass(frozen=True)
class RapportEdgeLiquidation:
    n_evenements: int
    n_mesurables: int
    edge_net_moyen_bps: float
    hit_rate: float
    profit_factor: float
    net_total_bps: float
    verdict: str                 # EDGE_NET_POSITIF | PAS_D_EDGE | INSUFFISANT
    horizon_s: float
    cout_aller_retour_bps: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_evenements": self.n_evenements, "n_mesurables": self.n_mesurables,
            "edge_net_moyen_bps": self.edge_net_moyen_bps, "hit_rate": self.hit_rate,
            "profit_factor": self.profit_factor, "net_total_bps": self.net_total_bps,
            "verdict": self.verdict, "horizon_s": self.horizon_s,
            "cout_aller_retour_bps": self.cout_aller_retour_bps,
            "promesse": "aucune — mesure descriptive sur données réelles", "real_execution": False,
        }


def direction_trade(sens: str | None) -> str | None:
    """Direction RELÂCHÉE (le trade de fade). VENTE (longs liquidés) → LONG ; ACHAT (shorts) → SHORT."""
    s = str(sens or "").strip().upper()
    if s in ("VENTE", "SELL", "LONG_LIQUIDE", "LONG"):
        return "LONG"
    if s in ("ACHAT", "BUY", "SHORT_LIQUIDE", "SHORT"):
        return "SHORT"
    return None


def rendement_net_bps(entry_px: float, path: Sequence[tuple[float, float]], entry_ts: float,
                      direction: str, *, horizon_s: float, cout_bps: float) -> float | None:
    """Rendement NET (bps) du trade de fade sur le chemin RÉEL. None = non mesurable (pas de futur)."""
    if entry_px <= 0:
        return None
    futur = [(t, m) for (t, m) in path if t > entry_ts and t <= entry_ts + float(horizon_s) and m > 0]
    if not futur:
        return None
    exit_px = futur[-1][1]                          # markout à l'horizon (dernier mark réel)
    move = (exit_px - entry_px) / entry_px * 10_000.0
    brut = move if direction == "LONG" else -move
    return brut - float(cout_bps)                    # net APRÈS coût aller-retour


def mesurer_edge_liquidation(evenements: Iterable[dict], marks_par_coin: dict[str, list],
                             *, horizon_s: float = 1800.0,
                             cout_aller_retour_bps: float = COUT_ALLER_RETOUR_BPS,
                             min_evenements: int = MIN_EVENEMENTS) -> RapportEdgeLiquidation:
    """Pour CHAQUE liquidation : entrer dans la direction relâchée, mesurer le markout net. Agréger."""
    evs = [e for e in evenements if isinstance(e, dict)]
    nets: list[float] = []
    for e in evs:
        coin = str(e.get("coin") or "").upper()
        d = direction_trade(e.get("sens"))
        if not coin or d is None:
            continue
        try:
            entry = float(e.get("prix") or 0.0)
            ts = float(e.get("ts_ms") or 0.0) / 1000.0
        except (TypeError, ValueError):
            continue
        path = [(float(t), float(m)) for (t, m) in marks_par_coin.get(coin, [])
                if isinstance(t, (int, float)) and isinstance(m, (int, float))]
        r = rendement_net_bps(entry, path, ts, d, horizon_s=horizon_s, cout_bps=cout_aller_retour_bps)
        if r is not None:
            nets.append(r)

    n_mes = len(nets)
    if n_mes < int(min_evenements):
        return RapportEdgeLiquidation(len(evs), n_mes, 0.0, 0.0, 0.0, 0.0, "INSUFFISANT",
                                      horizon_s, cout_aller_retour_bps)
    net_total = sum(nets)
    moyen = net_total / n_mes
    gains = sum(x for x in nets if x > 0)
    pertes = -sum(x for x in nets if x < 0)
    pf = (gains / pertes) if pertes > 0 else (float("inf") if gains > 0 else 0.0)
    hit = sum(1 for x in nets if x > 0) / n_mes
    verdict = "EDGE_NET_POSITIF" if (moyen > 0 and pf > 1.0) else "PAS_D_EDGE"
    return RapportEdgeLiquidation(len(evs), n_mes, round(moyen, 4), round(hit, 4),
                                  round(pf, 4) if pf != float("inf") else pf,
                                  round(net_total, 4), verdict, horizon_s, cout_aller_retour_bps)


def exiger_assez_d_evenements(rapport: RapportEdgeLiquidation) -> None:
    """Refuse BRUYAMMENT de conclure sur données insuffisantes (jamais un faux edge)."""
    if rapport.verdict == "INSUFFISANT":
        raise DonneesLiquidationInsuffisantes(
            "seulement %d événements mesurables (< %d) : aucune conclusion crédible"
            % (rapport.n_mesurables, MIN_EVENEMENTS))


__all__ = ["DonneesLiquidationInsuffisantes", "RapportEdgeLiquidation", "direction_trade",
           "rendement_net_bps", "mesurer_edge_liquidation", "exiger_assez_d_evenements",
           "COUT_ALLER_RETOUR_BPS", "MIN_EVENEMENTS"]
