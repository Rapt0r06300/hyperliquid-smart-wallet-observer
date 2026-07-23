"""BACKTEST CARRY — rejouer nos VRAIES passes de scan sous d'autres réglages (21/07).

POURQUOI
--------
Nos constantes carry ont été choisies par le raisonnement, pas par la mesure : plancher de
break-even 120 h, sécurité de liquidation 1,5×, 12 slots, exposant d'allocation 3, seuil de
renfort 40 %. Chacune est défendable — aucune n'est *mesurée*. Impossible de faire mieux
tant qu'on ne gardait que 96 lignes de données carry.

`carry_scan_recorder` enregistre désormais chaque passe (~20 coins, toutes les 10 min) avec
TOUS les intrants d'une décision : funding (snapshot / persistant / z-score / prévu), base
VWAP et MID, liquidité mesurée au carnet, levier max de la venue, pire hausse sur 200 jours.
Ce module les rejoue.

CE QUI REND CE BACKTEST HONNÊTE
-------------------------------
  * **On re-décide, on ne re-filtre pas.** Chaque passe est ré-évaluée par
    `evaluer_carry_neutre` — le MÊME moteur que le live — avec les paramètres testés. Changer
    la sécurité de liquidation change donc réellement le levier retenu, donc la viabilité.
  * **Aucune réimplémentation.** Le balayage de levier, la porte de risque, l'anti-churn,
    l'allocation, le renfort et le PnL viennent des modules de production. Un backtest qui
    réécrit la logique ne teste que lui-même.
  * **Pas de lookahead.** Une passe ne voit que sa propre ligne ; le funding encaissé entre
    deux passes est celui MESURÉ à la passe précédente, jamais le suivant.
  * **Mode BACKTEST** partout : le PnL de replay ne touche jamais celui du live.
  * **Zéro donnée = zéro résultat.** Un backtest sans passes rend `insuffisant`, jamais un
    chiffre. Un joli nombre sorti de rien coûte plus cher que pas de nombre du tout.

PAPER only : rejouer n'est pas passer un ordre.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from hl_observer.funding.carry_allocation_nette import EXPOSANT_DEFAUT, allouer_marges
from hl_observer.funding.carry_marge_dynamique import PART_MAX_PAR_COIN
from hl_observer.funding.carry_position_lifecycle import GestionnaireCarry
from hl_observer.funding.delta_neutral_carry import evaluer_carry_neutre

#: le même escalier que le feeder (`LEVIERS_A_ESSAYER`) — dupliquer serait créer un 2ᵉ standard.
LEVIERS = (1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0)
#: nombre minimal de passes pour qu'un résultat mérite d'être lu (sinon : `insuffisant`).
PASSES_MIN = 12


@dataclass(frozen=True)
class Config:
    """Un jeu de réglages carry. Les valeurs par défaut = la PRODUCTION d'aujourd'hui,
    pour que « la config actuelle » soit toujours l'un des candidats comparés."""
    exposant_allocation: float = EXPOSANT_DEFAUT
    max_break_even_h: float = 120.0
    securite_liquidation: float = 1.5
    max_slots: int = 12
    part_max_par_coin: float = PART_MAX_PAR_COIN
    capital_usd: float = 1000.0
    #: 🧪 EXP#1 (23/07) — seuil d'OUVERTURE sur le funding. 0.0 = BASELINE (production, aucun
    #: changement). > 0 = n'ouvre que si funding ≥ seuil : teste si concentrer le capital sur le
    #: funding au-dessus du plancher améliore le net. Porte par LIGNE (aucun lookahead : ne lit que
    #: le funding de SA passe). Rollback = remettre 0.0.
    funding_min_bps_h: float = 0.0

    def nom(self) -> str:
        return ("exp%.3g/be%.0f/sec%.2g/slots%d/part%.0f%%/fmin%.3g"
                % (self.exposant_allocation, self.max_break_even_h, self.securite_liquidation,
                   self.max_slots, 100 * self.part_max_par_coin, self.funding_min_bps_h))


@dataclass
class Resultat:
    config: Config
    passes: int = 0
    coins_vus: int = 0
    ouvertures: int = 0
    fermetures: int = 0
    renforts: int = 0
    realise_usd: float = 0.0
    funding_accru_ouvert_usd: float = 0.0
    positions_finales: int = 0
    notional_final_usd: float = 0.0
    heures: float = 0.0
    insuffisant: bool = True
    motifs_fermeture: dict[str, int] = field(default_factory=dict)

    @property
    def pnl_total_usd(self) -> float:
        """Réalisé + funding déjà encaissé sur les positions encore ouvertes. Le latent de
        base n'y est PAS : il est réversible, il ne se compte pas comme un gain."""
        return round(self.realise_usd + self.funding_accru_ouvert_usd, 6)

    @property
    def pnl_par_jour_usd(self) -> float:
        return round(self.pnl_total_usd / (self.heures / 24.0), 6) if self.heures > 0 else 0.0

    def resume(self) -> dict[str, Any]:
        return {"config": self.config.nom(), "passes": self.passes, "heures": round(self.heures, 2),
                "coins_vus": self.coins_vus, "ouvertures": self.ouvertures,
                "fermetures": self.fermetures, "renforts": self.renforts,
                "realise_usd": round(self.realise_usd, 6),
                "funding_accru_ouvert_usd": round(self.funding_accru_ouvert_usd, 6),
                "pnl_total_usd": self.pnl_total_usd, "pnl_par_jour_usd": self.pnl_par_jour_usd,
                "positions_finales": self.positions_finales,
                "notional_final_usd": round(self.notional_final_usd, 2),
                "motifs_fermeture": self.motifs_fermeture,
                "insuffisant": self.insuffisant, "mode": "BACKTEST", "real_execution": False}


def _f(d: dict, k: str) -> float | None:
    v = d.get(k)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return None if f != f else f


def grouper_par_passe(lignes: Iterable[dict]) -> list[tuple[int, list[dict]]]:
    """[(ts_ms, [lignes de cette passe])], trié dans le temps. Une passe = un instant de
    décision ; on ne mélange jamais deux instants (ce serait du lookahead déguisé)."""
    par_ts: dict[int, list[dict]] = {}
    for d in lignes or ():
        if not isinstance(d, dict):        # une ligne corrompue n'annule pas la passe
            continue
        ts = d.get("ts_ms")
        if isinstance(ts, (int, float)) and not isinstance(ts, bool) and d.get("coin"):
            par_ts.setdefault(int(ts), []).append(d)
    return sorted(par_ts.items())


def redecider(ligne: dict, cfg: Config) -> tuple[dict, dict] | None:
    """Re-joue la décision d'UNE ligne de scan sous `cfg`. (decision, inputs) ou None.

    C'est ici que le backtest gagne son honnêteté : on rappelle `evaluer_carry_neutre` (le
    moteur du live) au lieu de refiltrer un verdict déjà pris. Une donnée manquante rend
    None — on ne comble jamais un trou pour faire tourner une simulation.
    """
    coin = str(ligne.get("coin") or "").upper()
    funding = _f(ligne, "funding_bps_h")
    if funding is None:
        funding = _f(ligne, "funding_snapshot_bps_h")
    # 🧪 EXP#1 — porte de funding (par ligne, aucun lookahead) : sous le seuil testé, on n'ouvre pas.
    if funding is not None and funding < float(cfg.funding_min_bps_h):
        return None
    base = _f(ligne, "base_bps")
    liq = _f(ligne, "liquidite_spot_usd")
    lmax = _f(ligne, "levier_max")
    pire = _f(ligne, "pire_hausse_observee")
    if not coin or funding is None or base is None or liq is None or pire is None:
        return None
    if lmax is None or lmax <= 0:
        return None                                   # coin malformé côté venue -> écarté
    pire_stresse = max(0.0, pire) * float(cfg.securite_liquidation)
    meilleur = None
    for lev in LEVIERS:
        if lev > lmax:
            continue
        try:
            v = evaluer_carry_neutre(coin=coin, funding_bps_h=funding, base_bps=base,
                                     liquidite_spot_usd=liq, maker=True, levier_max=lmax,
                                     marge_ratio=round(1.0 / lev, 6),
                                     pire_hausse_observee=pire_stresse)
        except (ValueError, TypeError, ZeroDivisionError):
            continue
        if v.viable:
            meilleur = (lev, v)
    if meilleur is None:
        return None
    lev, v = meilleur
    be = v.heures_pour_rentabiliser
    if be is None or float(be) > float(cfg.max_break_even_h):
        return None                                   # plancher de break-even (paramètre testé)
    decision = {"coin": coin, "viable": True, "funding_bps_h": funding,
                "cout_entree_bps": v.cout_entree_bps, "base_bps": base,
                "gain_net_24h_bps": v.gain_net_24h_bps, "liquidite_spot_usd": liq,
                "levier": lev}
    inputs = {"levier_utilise": lev, "levier_max": lmax, "marge_ratio": round(1.0 / lev, 6),
              "perp_px": _f(ligne, "perp_px") or 0.0, "pire_hausse_observee": pire,
              "liquidite_spot_usd": liq, "base_mid_bps": _f(ligne, "base_mid_bps")}
    return decision, inputs


def rejouer(lignes: Iterable[dict], cfg: Config | None = None) -> Resultat:
    """Rejoue toutes les passes sous `cfg` et rend le PnL paper obtenu.

    Le moteur est `GestionnaireCarry` en mode BACKTEST : ouvertures, accruals, sorties,
    anti-churn, porte de risque, renfort — exactement le code du live.
    """
    cfg = cfg or Config()
    res = Resultat(config=cfg)
    passes = grouper_par_passe(lignes)
    if len(passes) < 2:
        return res
    g = GestionnaireCarry(mode="BACKTEST")
    coins_vus: set[str] = set()
    for ts, groupe in passes:
        decisions: dict[str, tuple[dict, dict]] = {}
        for l in groupe:
            coins_vus.add(str(l.get("coin") or "").upper())
            rd = redecider(l, cfg)
            if rd is not None:
                decisions[rd[0]["coin"]] = rd
        # top-K par rendement net, comme le live (A2), puis allocation ∝ net**exposant
        classes = sorted(decisions, key=lambda c: -(decisions[c][0]["gain_net_24h_bps"] or 0.0))
        retenus = classes[: max(1, int(cfg.max_slots))]
        nets = {c: decisions[c][0]["gain_net_24h_bps"] for c in retenus}
        marges = allouer_marges(nets, capital_usd=cfg.capital_usd,
                                n_positions_visees=len(retenus) or 1,
                                exposant=cfg.exposant_allocation,
                                part_max_par_coin=cfg.part_max_par_coin)
        ctx = {"capital_usd": cfg.capital_usd}
        for c in retenus:
            d, inp = decisions[c]
            marge = marges.get(c) or 0.0
            if marge <= 0:
                marge = float((g.ouvertes.get(c) or {}).get("marge_usdt") or 0.0)
            if marge <= 0:
                continue
            evt = g.tick(d, inp, now_ms=ts, funding_bps_h_courant=d["funding_bps_h"],
                         prix_courant=inp.get("perp_px") or None,
                         base_bps_courant=d["base_bps"], marge_usd=marge, risque_contexte=ctx)
            res.ouvertures += 1 if evt.get("ouvert") else 0
            if evt.get("ferme"):
                res.fermetures += 1
                m = str(evt["ferme"])
                res.motifs_fermeture[m] = res.motifs_fermeture.get(m, 0) + 1
            if evt.get("renfort"):
                res.renforts += 1
        # les coins ouverts NON revus cette passe : on ne les touche pas (l'absence fige la
        # décision, elle ne déclenche pas d'aller-retour — leçon anti-churn du 19/07).
    res.passes = len(passes)
    res.heures = (passes[-1][0] - passes[0][0]) / 3.6e6
    res.coins_vus = len(coins_vus)
    res.realise_usd = float(g.journal.summary().get("realized_net_pnl_usdc") or 0.0)
    res.funding_accru_ouvert_usd = round(
        sum(float(p.get("funding_accrued_usdt") or 0.0) for p in g.ouvertes.values()), 6)
    res.positions_finales = len(g.ouvertes)
    res.notional_final_usd = sum(float(p.get("notional_usdt") or 0.0) for p in g.ouvertes.values())
    res.insuffisant = res.passes < PASSES_MIN
    return res


def grille_defaut() -> list[Config]:
    """Les axes qui décident vraiment du PnL carry, un par un autour de la production.
    On balaie peu et large plutôt que beaucoup et étroit : moins de sur-ajustement."""
    cfgs = [Config()]                                   # la production d'aujourd'hui, en repère
    for e in (1.0, 2.0, 5.0, 8.0):
        cfgs.append(Config(exposant_allocation=e))
    for be in (60.0, 90.0, 180.0, 235.0, 300.0):
        cfgs.append(Config(max_break_even_h=be))
    for s in (1.0, 1.25, 2.0, 3.0):
        cfgs.append(Config(securite_liquidation=s))
    for k in (3, 6, 8, 20):
        cfgs.append(Config(max_slots=k))
    for pm in (0.20, 0.30, 0.60, 1.0):
        cfgs.append(Config(part_max_par_coin=pm))
    return cfgs


def balayer(lignes: Iterable[dict], configs: Iterable[Config] | None = None) -> list[Resultat]:
    """Rejoue la grille et rend les résultats TRIÉS par PnL décroissant.
    Les lignes sont matérialisées une fois : chaque config rejoue les MÊMES données."""
    donnees = list(lignes or ())
    return sorted((rejouer(donnees, c) for c in (configs or grille_defaut())),
                  key=lambda r: -r.pnl_total_usd)


def verdict(resultats: list[Resultat]) -> dict[str, Any]:
    """Ce qu'on peut dire — et surtout ce qu'on ne peut PAS dire — de ce balayage."""
    if not resultats:
        return {"conclusion": "AUCUNE DONNEE", "detail":
                "aucune passe enregistrée : `runtime/replay/carry_scan.jsonl` est vide ou trop "
                "récent. Le journal se remplit d'environ 2 900 lignes/jour dès que le feeder "
                "tourne — reviens demain, il n'y a rien à conclure avant.", "sur": 0}
    meilleur = resultats[0]
    actuel = next((r for r in resultats if r.config == Config()), None)
    if meilleur.insuffisant:
        return {"conclusion": "DONNEES INSUFFISANTES",
                "detail": ("%d passe(s) sur %d minimum (%.1f h). Un classement sur si peu de "
                           "passes est du bruit, pas un réglage." % (meilleur.passes, PASSES_MIN,
                                                                     meilleur.heures)),
                "sur": meilleur.passes}
    gain = None
    if actuel is not None and actuel.pnl_total_usd != 0:
        gain = round(100.0 * (meilleur.pnl_total_usd / abs(actuel.pnl_total_usd) - 1.0), 1)
    # 🔴 GARDE ANTI-« BAISSE LA SÉCURITÉ ET GAGNE PLUS ». Réduire `securite_liquidation`
    # augmente MÉCANIQUEMENT le levier retenu, donc le funding encaissé — et un backtest sur
    # une fenêtre calme ne peut PAS voir la liquidation qu'on vient de rendre possible : la
    # queue qu'on a supprimée est justement absente des données. Le PnL monte, le risque de
    # ruine aussi, et seul le premier est mesuré. On refuse donc de couronner ce réglage.
    if actuel is not None and meilleur.config.securite_liquidation < actuel.config.securite_liquidation:
        sur = next((r for r in resultats
                    if r.config.securite_liquidation >= actuel.config.securite_liquidation), None)
        return {
            "conclusion": "GAIN REFUSE : IL VIENT D'UNE BAISSE DE SECURITE",
            "detail": ("le meilleur PnL (%+.6f $) s'obtient avec securite_liquidation %.2f au "
                       "lieu de %.2f. Ce n'est pas un meilleur reglage, c'est plus de levier : "
                       "un backtest sur une fenetre sans krach ne peut pas voir la liquidation "
                       "qu'on vient de rendre possible. Refuse tant qu'un test de stress "
                       "n'aura pas mesure la queue."
                       % (meilleur.pnl_total_usd, meilleur.config.securite_liquidation,
                          actuel.config.securite_liquidation)),
            "meilleur_a_securite_egale": sur.resume() if sur is not None else None,
            "actuel": actuel.resume(), "sur": meilleur.passes,
        }
    return {
        "conclusion": ("LA CONFIG ACTUELLE RESTE LA MEILLEURE"
                       if actuel is not None and meilleur.config == actuel.config
                       else "UN AUTRE REGLAGE FAIT MIEUX SUR CES DONNEES"),
        "meilleur": meilleur.resume(),
        "actuel": actuel.resume() if actuel is not None else None,
        "gain_vs_actuel_pct": gain,
        "sur": meilleur.passes,
        "avertissement": ("Mesuré sur %.1f h d'un seul régime de marché (funding proche du "
                          "plancher). Un réglage qui gagne ici n'est pas prouvé ailleurs : "
                          "à re-mesurer quand le funding aura bougé." % meilleur.heures),
    }


__all__ = ["Config", "Resultat", "LEVIERS", "PASSES_MIN", "grouper_par_passe", "redecider",
           "rejouer", "grille_defaut", "balayer", "verdict"]
