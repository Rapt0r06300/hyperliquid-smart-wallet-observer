"""BACKTEST DE L'ARBITRAGE DE DISLOCATION — la question de Flo, tranchée par la mesure (21/07).

« L'arbitrage n'ouvre que deux fois par mois, ce n'est vraiment pas normal. »

Il avait raison de trouver ça anormal, et j'avais commencé par la mauvaise réponse : baisser
le seuil. Baisser un seuil augmente le nombre de trades — ça ne crée pas d'edge. La vraie
question, la seule, est **antérieure** :

    UN ÉCART HYPERLIQUID ↔ BINANCE SE REFERME-T-IL, OUI OU NON ?

Si oui, il existe un seuil optimal et on peut le trouver. Si non, aucun seuil ne sauve la
stratégie et il faut le dire — pas la calibrer jusqu'à ce qu'elle ait l'air de marcher.

CE MODULE RÉPOND AUX DEUX QUESTIONS, DANS CET ORDRE
---------------------------------------------------
1. `convergence(...)` — **l'étude de retour à la moyenne, sans aucun seuil ni coût.** Pour
   chaque observation d'écart |e_t| au-dessus d'un niveau, on regarde ce que devient |e_{t+h}|.
   Si l'écart moyen se réduit, il y a matière ; sinon, il n'y en a pas, et c'est la fin de
   l'histoire — un backtest de seuils sur une série qui ne converge pas ne mesure que le bruit.
2. `balayer(...)` — **seulement si (1) est concluant** : le PnL paper, coûts payés, pour une
   grille de seuils d'ouverture / de sortie / d'âge maximum.

RÈGLES
------
  * Coûts **toujours** payés (aller-retour maker 2 jambes, la constante du module de prod).
  * Pas de lookahead : une entrée à `t` ne voit que les observations ≤ `t` ; la sortie est
    cherchée dans le futur de la position, jamais avant.
  * Un écart mesuré sur DEUX venues n'est pas un profit : sans jambe Binance réelle, la
    convergence est une hypothèse. On la teste, on ne la suppose pas.
  * Données insuffisantes -> `insuffisant`, jamais un chiffre.

PAPER only : rejouer une série de prix n'est pas passer un ordre.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from hl_observer.funding.arb_dislocation_paper import (AGE_MAX_H, COUT_AR_BPS, NOTIONAL_USD,
                                                       SEUIL_OUVERTURE_BPS, SEUIL_SORTIE_BPS,
                                                       VENUES_RELPATH)

#: sous ce nombre d'observations exploitables, on ne conclut rien.
OBSERVATIONS_MIN = 200
#: sous ce nombre d'entrées déclenchées, un PnL n'est pas un résultat, c'est une anecdote.
ENTREES_MIN = 10


def charger_serie(root: str | Path = ".",
                  chemin: str | Path | None = None) -> dict[str, list[tuple[float, float]]]:
    """{coin: [(ts_s, ecart_bps), ...]} trié dans le temps. Lignes sans écart -> ignorées
    (le champ est récent : les vieilles lignes n'en ont pas, et on n'en invente pas)."""
    p = Path(chemin) if chemin else Path(root) / VENUES_RELPATH
    par_coin: dict[str, list[tuple[float, float]]] = {}
    try:
        with p.open(encoding="utf-8", errors="ignore") as f:
            for l in f:
                l = l.strip()
                if not l:
                    continue
                try:
                    d = json.loads(l)
                except ValueError:
                    continue
                if not isinstance(d, dict):
                    continue
                coin, ts, e = d.get("coin"), d.get("ts"), d.get("ecart_prix_bps")
                if (not coin or not isinstance(ts, (int, float)) or isinstance(ts, bool)
                        or not isinstance(e, (int, float)) or isinstance(e, bool)):
                    continue
                if float(e) != float(e):                       # NaN
                    continue
                par_coin.setdefault(str(coin).upper(), []).append((float(ts), float(e)))
    except OSError:
        return {}
    return {c: sorted(v) for c, v in par_coin.items() if v}


def convergence(serie: dict[str, list[tuple[float, float]]], *, seuil_bps: float = 10.0,
                horizons_h: Iterable[float] = (0.5, 1.0, 2.0, 4.0, 8.0)) -> dict[str, Any]:
    """LA question préalable : quand |écart| ≥ seuil, que devient-il ?

    Pour chaque horizon, on rend la variation MOYENNE de |écart| (en bps) et la part des cas
    où il s'est réduit. Négatif = ça converge (matière à arbitrer). ~0 ou positif = pas d'edge,
    et aucun réglage de seuil n'y changera quoi que ce soit.
    """
    total_obs = sum(len(v) for v in serie.values())
    res: dict[str, Any] = {"seuil_bps": float(seuil_bps), "observations": total_obs,
                           "coins": len(serie), "horizons": {}}
    if total_obs < OBSERVATIONS_MIN:
        res["insuffisant"] = True
        res["detail"] = ("%d observation(s) d'écart pour %d minimum : le champ `ecart_prix_bps` "
                         "vient d'être ajouté au collecteur, la série est encore jeune."
                         % (total_obs, OBSERVATIONS_MIN))
        return res
    res["insuffisant"] = False
    for h in horizons_h:
        deltas: list[float] = []
        for points in serie.values():
            for i, (t, e) in enumerate(points):
                if abs(e) < float(seuil_bps):
                    continue
                cible = t + float(h) * 3600.0
                # première observation À OU APRÈS l'horizon, tolérance une demi-fenêtre
                futur = next(((tf, ef) for tf, ef in points[i + 1:]
                              if cible <= tf <= cible + float(h) * 1800.0), None)
                if futur is None:
                    continue
                deltas.append(abs(futur[1]) - abs(e))
        if not deltas:
            res["horizons"]["%.1fh" % h] = {"n": 0}
            continue
        moy = sum(deltas) / len(deltas)
        res["horizons"]["%.1fh" % h] = {
            "n": len(deltas), "delta_moyen_bps": round(moy, 3),
            "part_reduite_pct": round(100.0 * sum(1 for d in deltas if d < 0) / len(deltas), 1),
        }
    utiles = [v for v in res["horizons"].values() if v.get("n")]
    if not utiles:
        res["verdict"] = "PAS ASSEZ DE PAIRES (t, t+h) — série trop courte ou trop trouée"
    elif min(v["delta_moyen_bps"] for v in utiles) < -COUT_AR_BPS:
        res["verdict"] = ("ÇA CONVERGE ASSEZ POUR PAYER LES COÛTS (%.1f bps d'aller-retour) — "
                          "un seuil optimal existe, le balayage a du sens" % COUT_AR_BPS)
    elif min(v["delta_moyen_bps"] for v in utiles) < 0:
        res["verdict"] = ("ça converge, mais MOINS que les %.1f bps de coûts : l'edge net est "
                          "négatif en moyenne — seuls les écarts EXTRÊMES peuvent payer"
                          % COUT_AR_BPS)
    else:
        res["verdict"] = ("AUCUNE CONVERGENCE MESURÉE : l'écart ne se referme pas. Aucun seuil "
                          "ne sauve la stratégie — la baisser ferait juste PLUS de trades "
                          "perdants. À rouvrir seulement si la mesure change.")
    return res


@dataclass(frozen=True)
class ConfigArb:
    seuil_ouverture_bps: float = SEUIL_OUVERTURE_BPS
    seuil_sortie_bps: float = SEUIL_SORTIE_BPS
    age_max_h: float = AGE_MAX_H
    cout_ar_bps: float = COUT_AR_BPS
    notional_usd: float = NOTIONAL_USD

    def nom(self) -> str:
        return ("ouv%.3g/sortie%.3g/age%.0fh" % (self.seuil_ouverture_bps,
                                                 self.seuil_sortie_bps, self.age_max_h))


@dataclass
class ResultatArb:
    config: ConfigArb
    entrees: int = 0
    gagnants: int = 0
    pnl_usd: float = 0.0
    capture_moyenne_bps: float = 0.0
    duree_moyenne_h: float = 0.0
    sorties_par_age: int = 0
    insuffisant: bool = True

    def resume(self) -> dict[str, Any]:
        return {"config": self.config.nom(), "entrees": self.entrees, "gagnants": self.gagnants,
                "winrate_pct": (round(100.0 * self.gagnants / self.entrees, 1)
                                if self.entrees else None),
                "pnl_usd": round(self.pnl_usd, 6),
                "capture_moyenne_bps": round(self.capture_moyenne_bps, 3),
                "duree_moyenne_h": round(self.duree_moyenne_h, 2),
                "sorties_par_age": self.sorties_par_age, "insuffisant": self.insuffisant,
                "mode": "BACKTEST", "real_execution": False}


def rejouer(serie: dict[str, list[tuple[float, float]]],
            cfg: ConfigArb | None = None) -> ResultatArb:
    """Rejoue la série sous `cfg`. Une position par coin à la fois (comme le live)."""
    cfg = cfg or ConfigArb()
    r = ResultatArb(config=cfg)
    captures: list[float] = []
    durees: list[float] = []
    for points in serie.values():
        i, n = 0, len(points)
        while i < n:
            t, e = points[i]
            if abs(e) < cfg.seuil_ouverture_bps:
                i += 1
                continue
            # sortie : convergence, aggravation (stop), ou âge — cherchée UNIQUEMENT dans le futur
            j = i + 1
            sortie = None
            while j < n:
                tf, ef = points[j]
                if (tf - t) / 3600.0 >= cfg.age_max_h:
                    sortie = (tf, ef, "AGE")
                    break
                if abs(ef) <= cfg.seuil_sortie_bps:
                    sortie = (tf, ef, "CONVERGENCE")
                    break
                j += 1
            if sortie is None:                          # la série s'arrête : trade NON clos, ignoré
                break                                   # (compter un trade ouvert serait inventer)
            tf, ef, motif = sortie
            # CAPTURE — on est SHORT LE SPREAD (on parie sur son resserrement) :
            #   même signe  -> capture = |e_in| − |e_out|  (négative si l'écart s'est ÉLARGI) ;
            #   signe opposé-> capture = |e_in| + |e_out|  (le spread a traversé zéro et a
            #                  continué : on gagne des deux côtés du passage).
            # Écrit explicitement parce que la version compacte se relit mal — et une formule
            # de PnL qu'on relit mal finit par devenir un bug.
            capture = (abs(e) - abs(ef)) if e * ef > 0 else (abs(e) + abs(ef))
            net_bps = capture - cfg.cout_ar_bps
            r.entrees += 1
            r.gagnants += 1 if net_bps > 0 else 0
            r.pnl_usd += net_bps / 1e4 * cfg.notional_usd
            r.sorties_par_age += 1 if motif == "AGE" else 0
            captures.append(capture)
            durees.append((tf - t) / 3600.0)
            i = j + 1                                   # on repart APRÈS la sortie (pas de chevauchement)
    if captures:
        r.capture_moyenne_bps = sum(captures) / len(captures)
        r.duree_moyenne_h = sum(durees) / len(durees)
    r.insuffisant = r.entrees < ENTREES_MIN
    return r


def grille_defaut() -> list[ConfigArb]:
    cfgs = [ConfigArb()]
    for s in (5.0, 8.0, 10.0, 20.0, 30.0, 50.0):
        cfgs.append(ConfigArb(seuil_ouverture_bps=s))
    for so in (1.0, 5.0, 8.0):
        cfgs.append(ConfigArb(seuil_sortie_bps=so))
    for a in (2.0, 6.0, 24.0, 48.0):
        cfgs.append(ConfigArb(age_max_h=a))
    return cfgs


def balayer(serie: dict[str, list[tuple[float, float]]],
            configs: Iterable[ConfigArb] | None = None) -> list[ResultatArb]:
    return sorted((rejouer(serie, c) for c in (configs or grille_defaut())),
                  key=lambda r: -r.pnl_usd)


def verdict(conv: dict[str, Any], resultats: list[ResultatArb]) -> dict[str, Any]:
    """L'ordre compte : la convergence d'ABORD. Un classement de seuils sur une série qui ne
    converge pas est un exercice de sur-ajustement, pas un résultat."""
    if conv.get("insuffisant"):
        return {"conclusion": "DONNEES INSUFFISANTES", "detail": conv.get("detail", ""),
                "convergence": conv}
    if "AUCUNE CONVERGENCE" in str(conv.get("verdict", "")):
        return {"conclusion": "PAS D'EDGE D'ARBITRAGE SUR CES DONNEES",
                "detail": conv["verdict"], "convergence": conv,
                "avertissement": "Ne PAS baisser le seuil : plus de trades ≠ plus d'edge."}
    exploitables = [r for r in resultats if not r.insuffisant]
    if not exploitables:
        return {"conclusion": "TROP PEU D'ENTREES POUR TRANCHER",
                "detail": ("aucun réglage n'atteint %d entrées closes sur cette fenêtre — la "
                           "série est encore trop courte." % ENTREES_MIN),
                "convergence": conv}
    meilleur = exploitables[0]
    actuel = next((r for r in resultats if r.config == ConfigArb()), None)
    return {"conclusion": ("LE SEUIL ACTUEL EST LE MEILLEUR"
                           if actuel is not None and meilleur.config == actuel.config
                           else "UN AUTRE SEUIL FAIT MIEUX SUR CES DONNEES"),
            "meilleur": meilleur.resume(),
            "actuel": actuel.resume() if actuel is not None else None,
            "convergence": conv,
            "avertissement": ("Sans jambe Binance réelle, la convergence reste une HYPOTHÈSE "
                              "mesurée sur les prix, pas un profit encaissé.")}


__all__ = ["OBSERVATIONS_MIN", "ENTREES_MIN", "ConfigArb", "ResultatArb", "charger_serie",
           "convergence", "rejouer", "grille_defaut", "balayer", "verdict"]
