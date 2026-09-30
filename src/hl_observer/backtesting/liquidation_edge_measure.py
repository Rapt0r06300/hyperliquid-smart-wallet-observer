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


def evenements_declenches(grappes: Iterable[dict], marks_par_coin: dict[str, list],
                          *, tolerance_bps: float = 5.0,
                          fenetre_s: float = 6 * 3600.0) -> list[dict]:
    """Transforme des SNAPSHOTS de grappes (carte B9) en ÉVÉNEMENTS de liquidation déclenchés.

    🔴 ARTEFACT DU 20/07 (attrapé avant publication) : mesurer directement sur les snapshots
    donnait « +735 bps, hit 100 %, PF ∞ » — parce qu'on « entrait » au PRIX DE LA GRAPPE
    (le niveau de liquidation, ~700 bps SOUS le marché) alors que personne n'a jamais tradé
    là : l'edge mesuré ÉTAIT la distance_bps. Et la même grappe re-photographiée toutes les
    minutes comptait pour 54 « événements ».

    Règles honnêtes :
      * un événement n'existe que si le MARK FRANCHIT le niveau de la grappe (± tolérance)
        dans la fenêtre qui suit le snapshot — la liquidation a alors réellement pu se
        produire ;
      * l'entrée du trade simulé = le MARK au moment du franchissement (un prix réel),
        jamais le niveau lui-même ;
      * une grappe suivie dans le temps (même coin, même sens, niveau à ±20 bps) ne compte
        qu'UNE fois — au premier franchissement.
    """
    marks = {c: sorted((float(t), float(m)) for (t, m) in pts)
             for c, pts in (marks_par_coin or {}).items()}
    vus: set[tuple] = set()
    out: list[dict] = []
    for g in sorted((g for g in grappes if isinstance(g, dict)),
                    key=lambda g: float(g.get("ts_ms") or 0)):
        coin = str(g.get("coin") or "").upper()
        try:
            niveau = float(g.get("prix") or 0.0)
            ts = float(g.get("ts_ms") or 0.0) / 1000.0
        except (TypeError, ValueError):
            continue
        if not coin or niveau <= 0 or coin not in marks:
            continue
        # 🔴 22/07 — LA CLE DE DEDUP INCLUT LE TEMPS. Avant : (coin, sens, niveau) SANS temps ->
        # une liquidation BTC a 60k aujourd'hui et une AUTRE a 60k dans 3 jours comptaient pour
        # UNE seule (286 snapshots -> 1 evenement). C'est l'exces INVERSE de l'artefact du 20/07 :
        # on avait tue le sur-comptage de la meme grappe, mais aussi le comptage d'evenements
        # DISTINCTS au meme niveau. Deux purges separees de plus d'une fenetre sont deux
        # evenements. Chacune exige toujours un franchissement de mark REEL -> rien d'invente.
        bucket_t = round(ts / max(float(fenetre_s), 1.0))
        cle = (coin, str(g.get("sens") or ""),
               round(niveau / max(niveau * 20e-4, 1e-9)), bucket_t)
        if cle in vus:
            continue
        sens = str(g.get("sens") or "").upper()
        tol = niveau * tolerance_bps / 1e4
        for (t, m) in marks[coin]:
            if t < ts or t > ts + fenetre_s:
                continue
            franchi = (m <= niveau + tol) if sens == "SELL" else (m >= niveau - tol)
            if franchi:
                vus.add(cle)
                out.append({**g, "prix": m, "ts_ms": t * 1000.0,
                            "niveau_grappe": niveau, "declenchee": True})
                break
    return out


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
