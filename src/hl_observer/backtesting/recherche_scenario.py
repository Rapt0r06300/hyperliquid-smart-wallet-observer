"""RECHERCHE DE SCÉNARIO — l'étage au-dessus du replay A/B, optimisé pour trouver un
scénario qui SURVIT, pas un pic qui brille.

Ce projet a déjà payé pour savoir ce que « parfait » veut dire : le faux « 1 sur 1M » était
un gagnant chanceux sorti de ~0 donnée ; 0 calibrage SL/TP n'a tenu hors échantillon ; la
coupe train/test fuyait à 68 %. Donc « optimisé au maximum » = trois choses PRÉCISES :

  1. VITESSE — candidats + marks (~500k lignes) chargés UNE fois, réutilisés pour toutes les
     configs (levier n°1 : sinon chaque config repaie des secondes de parsing).
  2. HONNÊTETÉ — chaque config jugée sur DEUX MOITIÉS TEMPORELLES DISJOINTES avec EMBARGO
     (les candidats à moins d'un horizon de la coupe sont jetés des deux côtés). Gagner sur
     les deux moitiés = le minimum vital contre le gagnant chanceux.
  3. STABILITÉ — un promu doit vivre sur un PLATEAU : la majorité de ses VOISINS (SL±, TP±)
     doivent aussi être profitables. Un pic isolé est un artefact, pas un scénario (W8).

La porte finale exige EN PLUS la survie à un stress des coûts ×1,5 (F29). REPLAY-only :
données enregistrées, aucun réseau, aucun ordre ; la session live n'est pas touchée.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from hl_observer.backtesting.ab_flag_replay import (
    DEFAULT_COST_BPS, load_jsonl, marks_by_coin, net_baseline_seul, run_ab_replay,
)
from hl_observer.paper_trading.sl_tp import SLTPConfig
from hl_observer.backtesting.boucle_objectif_replay import boucle_objectif
from hl_observer.backtesting import robustesse_selection
from hl_observer.backtesting.recherche_parallele import remplir_en_parallele
from hl_observer.backtesting.recherche_carry import chercher_carry
import statistics as _stats

# --- les barres de la porte, FIXÉES ICI (les déplacer se voit dans un diff) -------------
MIN_TRADES_PAR_MOITIE = 30        # sous ça, une moitié ne prouve rien (bruit)
MIN_PF_PAR_MOITIE = 1.1           # gagner "un peu" sur les deux moitiés > briller sur une
STRESS_COUTS = 1.5                # F29 : le scénario doit survivre à des coûts x1,5
FRACTION_VOISINS_VIVANTS = 0.6    # W8 : plateau exigé — 60 % des voisins net>0
EMBARGO_FACTEUR = 1.0             # embargo = 1 horizon de part et d'autre de la coupe

ETAT_RECHERCHE_RELPATH = Path("runtime") / "replay" / "recherche_scenario_etat.json"

#: seaux de strategies (21/07) : les '?' historiques sont des signaux COPY du firehose.
ALIAS_STRATEGIES: dict[str, set] = {
    "copy": {"copy", "?", "none"},
    "carry": {"carry"},
    "arbitrage": {"arbitrage", "funding_arb", "triangular"},
}
STRATEGIES_MODULES = ("carry", "copy", "arbitrage")


def repertoire_replay_consolide(root: str | Path) -> Path:
    """Où vivent les consolidés. 🔴 21/07 : `merge_replay` écrit dans `_merged/` (dossier différent
    pour ne pas se re-lire) mais la recherche lisait la RACINE → INSUFFISANT devant 331k candidats.
    Un seul résolveur, partagé par la recherche, le PnL des refus et le rapport."""
    base = Path(root) / "runtime" / "replay"
    if (base / "_merged" / "candidates.jsonl").exists():
        return base / "_merged"
    return base


# ================================================================ 1. données chargées UNE fois

@dataclass
class DonneesReplay:
    """Candidats + marks en mémoire, coupés une seule fois. Tout le reste les partage."""
    candidats: list[dict] = field(default_factory=list)
    marks: list[dict] = field(default_factory=list)

    @classmethod
    def charger(cls, root: str | Path, *, strategie: str | None = None) -> "DonneesReplay":
        """Chargement PAR STRATÉGIE — mélanger 262k signaux copy et les candidats carry dans
        une même grille donnerait le scénario moyen de RIEN. `strategie=None` garde tout."""
        base = repertoire_replay_consolide(root)
        if not (base / "candidates.jsonl").exists():
            return cls(candidats=[], marks=[])            # dossier vide = INSUFFISANT honnete
        cands = load_jsonl(str(base / "candidates.jsonl"))
        if strategie is not None:
            # 🔴 22/07 — bucketing par STRATEGIE EFFECTIVE (label OU inference de champs) : un
            # candidat carry/arbitrage sans label est reconnu par SES champs, jamais rangé en copy.
            from hl_observer.ops.strategie_candidat import strategie_effective
            cible = ALIAS_STRATEGIES.get(strategie, {strategie})
            cands = [c for c in cands if strategie_effective(c) in cible]
        return cls(candidats=cands, marks=load_jsonl(str(base / "marks.jsonl")))

    def moities_avec_embargo(self, horizon_min: float) -> tuple[list[dict], list[dict]]:
        """Coupe TEMPORELLE médiane + embargo d'un horizon DE CHAQUE CÔTÉ. Leçon du 13/07 (fuite
        à 68 %) : sans embargo, les outcomes des derniers candidats de la moitié 1 se réalisent
        dans la zone de la moitié 2 — le « hors échantillon » n'en est plus un."""
        ts = sorted(float(c.get("recorded_at") or 0.0) for c in self.candidats)
        if not ts:
            return [], []
        coupe = ts[len(ts) // 2]
        marge = float(horizon_min) * 60.0 * EMBARGO_FACTEUR
        m1 = [c for c in self.candidats
              if float(c.get("recorded_at") or 0.0) <= coupe - marge]
        m2 = [c for c in self.candidats
              if float(c.get("recorded_at") or 0.0) >= coupe + marge]
        return m1, m2


# ================================================================ 2. l'espace de recherche

#: 21/07 (« combinaisons ultra travaillées ») : chaque config SL/TP/horizon se croise avec des
#: FILTRES D'ENTRÉE mesurés sur nos candidats — les pépites vivent dans les SOUS-POPULATIONS
#: (un SL/TP moyen sur tout le monde n'a jamais payé ; sur les signaux frais+consensus, peut-être).
FILTRES_PRESETS: dict[str, dict] = {
    "tous": {},
    "frais": {"age_max_ms": 10_000},
    "consensus": {"min_consensus": 3},
    "frais_liquide": {"age_max_ms": 10_000, "min_liquidity": 0.55},
}


def filtrer_candidats(cands: list[dict], filtres: dict | None) -> list[dict]:
    """Applique un preset de filtres aux candidats — champs MESURÉS des candidats, jamais
    inventés (un candidat sans le champ requis est exclu du sous-échantillon : deny-by-default)."""
    if not filtres:
        return cands
    out = []
    for c in cands:
        try:
            if "age_max_ms" in filtres and not (
                    float(c.get("signal_age_ms") or 9e9) <= filtres["age_max_ms"]):
                continue
            if "min_consensus" in filtres and not (
                    float(c.get("consensus_wallets") or 0) >= filtres["min_consensus"]):
                continue
            if "min_liquidity" in filtres and not (
                    float(c.get("liquidity_score") or 0.0) >= filtres["min_liquidity"]):
                continue
        except (TypeError, ValueError):
            continue
        out.append(c)
    return out


def grille_large() -> Iterator[dict[str, Any]]:
    """Filet LARGE et FIN (~5 000 configs, 22/07 « monte vers 5000 ») : SL 15→160, TP 25→520,
    8 horizons 15 min→4 h, croisés aux presets de filtres — mailles fines là où vit l'edge. Portes
    inchangées (deux moitiés + stress ×1,5 + plateau). L'élargissement reste SÛR : le juge PBO
    (`annoter_robustesse`) fait monter la barre du multiple-testing avec la taille du filet, donc
    un plus grand filet NE PEUT PAS fabriquer un faux gagnant. Coût : le crible re-mesure ~4× plus
    de configs — c'est voulu (« teste tout »), et la mémoïsation du filtrage en amortit une part."""
    for base in grille_configs(
            sls=(15.0, 18.0, 22.0, 26.0, 30.0, 35.0, 40.0, 45.0, 50.0, 55.0,
                 62.0, 70.0, 80.0, 92.0, 105.0, 120.0, 140.0, 160.0),
            tps=(25.0, 30.0, 35.0, 42.0, 50.0, 60.0, 72.0, 86.0, 102.0, 122.0,
                 146.0, 175.0, 210.0, 250.0, 300.0, 360.0, 430.0, 520.0),
            horizons=(15.0, 30.0, 45.0, 60.0, 120.0, 240.0)):
        for nom, f in FILTRES_PRESETS.items():
            yield {**base, "filtre": nom, "filtres": f}


def grille_configs(*, sls=(30.0, 40.0, 60.0, 90.0), tps=(50.0, 70.0, 100.0, 150.0),
                   horizons=(30.0, 60.0, 120.0)) -> Iterator[dict[str, Any]]:
    """Grille grossière et PRINCIPIELLE : TP > SL toujours (un ratio perdant par construction
    n'a pas besoin d'être mesuré — il est refusé par l'arithmétique)."""
    for h in horizons:
        for sl in sls:
            for tp in tps:
                if tp > sl:
                    yield {"sl": sl, "tp": tp, "horizon_min": h}


def voisins(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Les 4 voisins directs dans la grille (SL±10, TP±20) — le test de plateau (W8)."""
    out = []
    for dsl, dtp in ((-10.0, 0.0), (10.0, 0.0), (0.0, -20.0), (0.0, 20.0)):
        v = dict(config)
        v["sl"] = round(float(config["sl"]) + dsl, 4)
        v["tp"] = round(float(config["tp"]) + dtp, 4)
        if v["sl"] > 0 and v["tp"] > v["sl"]:
            out.append(v)
    return out


def raffiner_autour(config: dict[str, Any], *, pas_sl=5.0, pas_tp=10.0) -> Iterator[dict[str, Any]]:
    """Raffinement local (grossier -> fin) autour d'un survivant de la grille."""
    for dsl in (-pas_sl, 0.0, pas_sl):
        for dtp in (-pas_tp, 0.0, pas_tp):
            v = dict(config)
            v["sl"] = round(float(config["sl"]) + dsl, 4)
            v["tp"] = round(float(config["tp"]) + dtp, 4)
            if v["sl"] > 0 and v["tp"] > v["sl"] and (dsl or dtp):
                yield v


# ================================================================ 3. évaluation deux-moitiés

def _sltp(config: dict[str, Any]) -> SLTPConfig:
    return SLTPConfig(stop_loss_bps=float(config["sl"]), take_profit_bps=float(config["tp"]))


def evaluer_sur_moities(donnees: DonneesReplay, config: dict[str, Any], *,
                        cost_bps: float = DEFAULT_COST_BPS,
                        evaluer_ab: Callable[..., dict] = run_ab_replay) -> dict[str, Any]:
    """Une config -> {moitie_1, moitie_2, stress} (bras A = l'environnement de PRODUCTION).
    `evaluer_ab` est injectable : les tests jugent NOTRE logique sans payer le vrai replay."""
    h = float(config.get("horizon_min") or 60.0)
    m1, m2 = donnees.moities_avec_embargo(h)
    # filtres APRÈS la coupe temporelle (la coupe ne dépend que du temps, pas du filtre).
    m1 = filtrer_candidats(m1, config.get("filtres"))
    m2 = filtrer_candidats(m2, config.get("filtres"))
    cfg = _sltp(config)
    r1 = evaluer_ab(m1, donnees.marks, base_config=cfg, horizon_min=h, cost_bps=cost_bps)
    r2 = evaluer_ab(m2, donnees.marks, base_config=cfg, horizon_min=h, cost_bps=cost_bps)
    stress = evaluer_ab(m1 + m2, donnees.marks, base_config=cfg, horizon_min=h,
                        cost_bps=cost_bps * STRESS_COUTS)
    return {"config": config, "moitie_1": r1.get("arm_a") or {}, "moitie_2": r2.get("arm_a") or {},
            "stress": stress.get("arm_a") or {}}


def _moitie_vivante(m: dict[str, Any]) -> bool:
    pf = m.get("profit_factor")
    pf_ok = (pf == "inf") or (isinstance(pf, (int, float)) and pf >= MIN_PF_PAR_MOITIE)
    return (int(m.get("trades") or 0) >= MIN_TRADES_PAR_MOITIE
            and float(m.get("net_total_usd") or 0.0) > 0.0 and pf_ok)


def porte_robuste(rapport: dict[str, Any]) -> bool:
    """LA porte du /goal : net>0 + PF>=1,1 + assez de trades sur CHAQUE moitié, ET net>0 sous
    coûts x1,5. Séparée de l'évaluateur — un rapport ne se promeut jamais lui-même."""
    return (_moitie_vivante(rapport.get("moitie_1") or {})
            and _moitie_vivante(rapport.get("moitie_2") or {})
            and float((rapport.get("stress") or {}).get("net_total_usd") or 0.0) > 0.0)


# ================================================================ 4. la recherche complète

def chercher(root: str | Path, *, configs: Iterable[dict[str, Any]] | None = None,
             max_essais: int | None = None, budget_s: float | None = None,
             donnees: DonneesReplay | None = None,
             strategie: str | None = None,
             s_arreter_au_premier: bool = True, raffiner: bool = False,
             evaluer_ab: Callable[..., dict] = net_baseline_seul) -> dict[str, Any]:
    """Grille -> porte deux-moitiés+stress -> PLATEAU des voisins -> verdict. Le plateau vit DANS
    la porte : un candidat qui passe les moitiés mais dont les voisins meurent est REJETE_INSTABLE
    — un pic isolé n'est jamais promu."""
    d = donnees if donnees is not None else DonneesReplay.charger(root, strategie=strategie)
    if not d.candidats:
        return {"statut": "INSUFFISANT", "strategie": strategie,
                "motif": "aucun candidat consolide pour %r "
                "(lancer la consolidation W2 d'abord)" % (strategie or "toutes"), "essais": []}

    def evaluer(config: dict[str, Any]) -> dict[str, Any]:
        return evaluer_sur_moities(d, config, evaluer_ab=evaluer_ab)

    def porte_avec_plateau(rapport: dict[str, Any]) -> bool:
        if not porte_robuste(rapport):
            return False
        vs = voisins(rapport["config"])
        if not vs:
            return False
        vivants = 0
        for v in vs:
            rv = evaluer_sur_moities(d, v, evaluer_ab=evaluer_ab)
            net = (float((rv["moitie_1"].get("net_total_usd") or 0.0))
                   + float((rv["moitie_2"].get("net_total_usd") or 0.0)))
            vivants += 1 if net > 0 else 0
        stable = vivants / len(vs) >= FRACTION_VOISINS_VIVANTS
        if not stable:
            rapport["instabilite"] = "REJETE_INSTABLE: %d/%d voisins vivants" % (vivants, len(vs))
        return stable

    etat = Path(root) / ETAT_RECHERCHE_RELPATH
    if strategie:                                 # un etat PAR module : jamais de melange
        etat = etat.with_name("recherche_scenario_etat_%s.json" % strategie)
    liste_configs = list(configs if configs is not None else grille_configs())
    liste_configs = _cribler_configs(d, liste_configs)      # screen bras-A rapide, index bâti 1×
    r = boucle_objectif(
        liste_configs,
        evaluer, porte_avec_plateau,
        etat_path=etat, max_essais=max_essais, budget_s=budget_s,
        s_arreter_au_premier=s_arreter_au_premier, total_hint=len(liste_configs))
    # ── RAFFINAGE grossier -> fin : on resserre la grille (pas/2) autour des PROMUS et meilleurs
    # presque-promus ; les raffinés passent LES MÊMES portes, la dedup par clé évite tout doublon.
    if raffiner and r.get("essais"):
        def _net12(e):
            n = e.get("nets") or {}
            return float(n.get("moitie_1") or 0.0) + float(n.get("moitie_2") or 0.0)
        graines = [e["config"] for e in r["essais"] if e.get("verdict") == "PROMU"]
        graines += [e["config"] for e in sorted(
            (e for e in r["essais"] if e.get("verdict") == "REJETE" and e.get("nets")),
            key=_net12, reverse=True)[:3]]
        raffines: list[dict[str, Any]] = []
        for g in graines[:6]:
            raffines.extend(raffiner_autour(g, pas_sl=5.0, pas_tp=10.0))
        if raffines:
            print("  -- raffinage : %d configs autour de %d graine(s) --"
                  % (len(raffines), len(graines[:6])), flush=True)
            r2 = boucle_objectif(raffines, evaluer, porte_avec_plateau, etat_path=etat,
                                 max_essais=max_essais, budget_s=budget_s,
                                 s_arreter_au_premier=False, total_hint=len(raffines))
            promus = (r.get("promus") or []) + (r2.get("promus") or [])
            r["essais"] = r["essais"] + r2["essais"]
            r["promus"] = promus
            if promus:
                r["statut"] = "PROMU"
                r["gagnant"] = max(promus, key=lambda p: float(
                    (p.get("nets") or {}).get("stress") or 0.0))["config"]
    # rang OR / ARGENT (CPCV — folds purges) : promus seulement, 4 evals chacun (rares = pas cher)
    for p in (r.get("promus") or []):
        try:
            p.update(rang_pepite(d, p["config"], evaluer_ab=evaluer_ab))
        except Exception:  # noqa: BLE001 — un rang illisible reste ARGENT, jamais un plantage
            p.setdefault("rang", "ARGENT")
    # 22/07 — LE JUGE DU SUR-AJUSTEMENT (PBO) : mesure si la PROCÉDURE généralise ou a eu de la
    # chance ; un PBO > 0,5 interdit tout « FAIS ÇA ».
    annoter_robustesse(d, r, evaluer_ab=evaluer_ab)
    r["strategie"] = strategie
    r["n_candidats"] = len(d.candidats)
    return r


# ================================================================ 5. cross-venue (son PROPRE espace)

def evaluer_episodes_cross_venue(series: list[dict], config: dict[str, Any], *,
                                 cout_ar_bps: float = 22.0) -> dict[str, Any]:
    """Rejoue la strategie de dispersion : ENTRER quand `dispersion_bps_h >= seuil_entree`,
    SORTIR quand elle retombe sous `seuil_sortie`. Gain d'un episode = ∫dispersion·dt (bps)
    − coût aller-retour 4 jambes (2 venues × 2 jambes, ~22 bps — stress ×1,5 ailleurs).
    Retourne la même forme que l'arm A du replay -> les MÊMES portes jugent (net, PF, trades).
    Sur 100 $ de notional par jambe : bps → $ directement (100$/1e4 = 0,01 $/bps)."""
    se, ss = float(config["seuil_entree"]), float(config["seuil_sortie"])
    par_coin: dict[str, list] = {}
    for r in series:
        c = str(r.get("coin") or "")
        t = float(r.get("ts_ms") or (r.get("ts") or 0) * 1000.0) / 1000.0
        d = r.get("dispersion_bps_h")
        if c and t > 0 and isinstance(d, (int, float)):
            par_coin.setdefault(c, []).append((t, float(d)))
    nets: list[float] = []
    for pts in par_coin.values():
        pts.sort()
        en_pos, capture, t_prec, d_prec = False, 0.0, None, 0.0
        for (t, d) in pts:
            if en_pos and t_prec is not None:
                capture += d_prec * (t - t_prec) / 3600.0          # bps/h × h = bps
            if not en_pos and d >= se:
                en_pos, capture = True, 0.0
            elif en_pos and d < ss:
                nets.append((capture - cout_ar_bps) / 1e4 * 100.0)  # $ sur 100 $/jambe
                en_pos = False
            t_prec, d_prec = t, d
    gains = sum(x for x in nets if x > 0)
    pertes = -sum(x for x in nets if x < 0)
    pf = "inf" if (gains > 0 and pertes == 0) else (gains / pertes if pertes > 0 else 0.0)
    return {"net_total_usd": round(sum(nets), 6), "trades": len(nets), "profit_factor": pf}


def etude_maker_refuge(series: list[dict], *, seuil_bps: float = 19.0) -> dict[str, Any]:
    """Refuge MAKER de l'arbitrage, MESURÉ sur la même série de dispersion (22/07). La loi
    `arb_dislocation_cout_all_in` gardait la porte « à 9 bps tout-maker les trades survivent » :
    `arb_maker_study` la mesure (sélection adverse comprise), branchée ici pour voyager AVEC le
    rapport. Un écart absent/illisible n'est jamais un fill. MESURE only, aucun réseau, aucun ordre."""
    from hl_observer.funding.arb_maker_study import etudier as _etudier_maker
    par_coin: dict[str, list[tuple[float, float]]] = {}
    for r in series or []:
        if not isinstance(r, dict):
            continue
        c = str(r.get("coin") or "")
        try:
            t = float(r.get("ts_ms") or (r.get("ts") or 0) * 1000.0) / 1000.0
        except (TypeError, ValueError):
            continue
        d = r.get("dispersion_bps_h")
        if c and t > 0 and isinstance(d, (int, float)):
            par_coin.setdefault(c, []).append((t, float(d)))
    return _etudier_maker(par_coin, seuil_bps=seuil_bps)


def chercher_cross_venue(root: str | Path, *, series: list[dict] | None = None,
                         max_essais: int | None = None) -> dict[str, Any]:
    """Recherche cross-venue, MÊMES portes (deux moitiés + stress ×1,5 + plateau). ⚠️ EXPLORATOIRE :
    ne touche pas au verdict 72 h (barres pré-écrites) — un seuil optimisé ici devra survivre au
    hors-échantillon APRÈS les 72 h avant d'exister en live."""
    if series is None:
        p = Path(root) / "runtime" / "data" / "dispersion_venues.jsonl"
        series = load_jsonl(str(p)) if p.exists() else []
    if len(series) < 500:
        return {"statut": "INSUFFISANT", "strategie": "cross_venue",
                "motif": "%d observations (<500) — laisser le collecteur tourner" % len(series),
                "essais": []}
    def ts(r):
        return float(r.get("ts_ms") or (r.get("ts") or 0) * 1000.0)
    tries = sorted(series, key=ts)
    coupe = ts(tries[len(tries) // 2])
    m1 = [r for r in tries if ts(r) <= coupe - 3600_000.0]   # embargo 1 h de part et d'autre
    m2 = [r for r in tries if ts(r) >= coupe + 3600_000.0]
    def evaluer(config):
        return {"config": config,
                "moitie_1": evaluer_episodes_cross_venue(m1, config),
                "moitie_2": evaluer_episodes_cross_venue(m2, config),
                "stress": evaluer_episodes_cross_venue(tries, config, cout_ar_bps=22.0 * STRESS_COUTS)}
    def porte(rapport):
        if not porte_robuste(rapport):
            return False
        vivants = 0
        vs = [dict(rapport["config"], seuil_entree=rapport["config"]["seuil_entree"] + d)
              for d in (-0.05, 0.05)]
        for v in vs:
            rv = evaluer(v)
            net = (float(rv["moitie_1"].get("net_total_usd") or 0)
                   + float(rv["moitie_2"].get("net_total_usd") or 0))
            vivants += 1 if net > 0 else 0
        return vivants / len(vs) >= FRACTION_VOISINS_VIVANTS
    configs = [{"seuil_entree": se, "seuil_sortie": ss}
               for se in (0.10, 0.15, 0.20, 0.30, 0.50, 0.80)
               for ss in (0.02, 0.05, 0.10, 0.20) if ss < se]
    r = boucle_objectif(configs, evaluer, porte,
                        etat_path=Path(root) / "runtime" / "replay"
                        / "recherche_scenario_etat_cross_venue.json",
                        max_essais=max_essais)
    r["strategie"] = "cross_venue"
    r["honnetete"] = ("exploratoire — le verdict officiel reste celui du protocole 72 h "
                      "(barres pre-ecrites), puis survie hors echantillon exigee")
    # 22/07 — le refuge MAKER voyage AVEC le rapport (branché, plus dans un test qui dort).
    try:
        r["etude_maker_refuge"] = etude_maker_refuge(series)
    except Exception:  # noqa: BLE001 — une mesure absente ne casse jamais la recherche
        r["etude_maker_refuge"] = {"signaux": 0, "verdict": "non mesurable ce tour"}
    return r


# ================================================================ 5bis. les canons du 21/07
# CPCV/folds purgés (Lopez de Prado — PBO plus bas que le walk-forward) + successive halving
# (cribler sur un sous-échantillon avant l'évaluation complète). Réf. ml4t, Optuna Hyperband.

def folds_purges(d: DonneesReplay, horizon_min: float, k: int = 4) -> list[list[dict]]:
    """K tranches TEMPORELLES avec embargo d'un horizon entre chaque — l'esprit CPCV : une
    pepite doit gagner sur PLUSIEURS epoques disjointes, pas sur une coupe chanceuse."""
    ts = sorted(float(c.get("recorded_at") or 0.0) for c in d.candidats)
    if len(ts) < k * 2:
        return []
    marge = float(horizon_min) * 60.0
    bornes = [ts[int(len(ts) * i / k)] for i in range(k)] + [ts[-1] + 1]
    folds = []
    for i in range(k):
        lo = bornes[i] + (marge if i > 0 else 0.0)
        hi = bornes[i + 1] - (marge if i < k - 1 else 0.0)
        folds.append([c for c in d.candidats
                      if lo <= float(c.get("recorded_at") or 0.0) < hi])
    return folds


def rang_pepite(d: DonneesReplay, config: dict[str, Any], *,
                evaluer_ab: Callable[..., dict] = run_ab_replay,
                cost_bps: float = DEFAULT_COST_BPS) -> dict[str, Any]:
    """OR / ARGENT (post-porte, promus seulement — 4 evals, rares donc pas cher) : OR = net > 0
    sur ≥ 3 des 4 folds purgés EN PLUS de la porte. L'ARGENT reste une pépite ; l'OR a survécu à
    une découpe de plus."""
    h = float(config.get("horizon_min") or 60.0)
    folds = folds_purges(d, h)
    if not folds:
        return {"rang": "ARGENT", "folds_nets": None}
    cfg = _sltp(config)
    nets = []
    for f in folds:
        f2 = filtrer_candidats(f, config.get("filtres"))
        r = evaluer_ab(f2, d.marks, base_config=cfg, horizon_min=h, cost_bps=cost_bps)
        nets.append(round(float((r.get("arm_a") or {}).get("net_total_usd") or 0.0), 4))
    vivants = sum(1 for n in nets if n > 0)
    return {"rang": "OR" if vivants >= 3 else "ARGENT", "folds_nets": nets,
            "folds_vivants": "%d/%d" % (vivants, len(nets))}


def _matrice_robustesse(d: DonneesReplay, configs: list[dict], *, k: int = 8,
                        evaluer_ab: Callable[..., dict] = run_ab_replay,
                        cost_bps: float = DEFAULT_COST_BPS) -> list[list[float]]:
    """Matrice [config][fold] du net pour le PBO (blocs temporels purgés). Bornée à ~24 configs ×
    k folds (survivants rares = peu cher) ; matrice vide (< 4 folds) => PBO INSUFFISANT plus haut."""
    if not configs:
        return []
    h_ref = float(configs[0].get("horizon_min") or 60.0)
    folds = folds_purges(d, h_ref, k=k)
    if len(folds) < 4:
        return []
    M: list[list[float]] = []
    for cfg in configs:
        h = float(cfg.get("horizon_min") or 60.0)
        ligne: list[float] = []
        for f in folds:
            f2 = filtrer_candidats(f, cfg.get("filtres"))
            try:
                r = evaluer_ab(f2, d.marks, base_config=_sltp(cfg), horizon_min=h, cost_bps=cost_bps)
                ligne.append(float((r.get("arm_a") or {}).get("net_total_usd") or 0.0))
            except Exception:  # noqa: BLE001 — un fold illisible = 0, jamais un plantage
                ligne.append(0.0)
        M.append(ligne)
    return M


def _candidats_pour_robustesse(r: dict[str, Any], maximum: int = 24) -> list[dict]:
    """Configs pour le PBO : PROMUS d'abord, complétés des meilleurs presque-promus (net m1+m2) —
    il faut du CORPS dans la matrice pour que le rang OOS ait un sens."""
    cands = [p["config"] for p in (r.get("promus") or []) if p.get("config")]
    def _net12(e):
        n = e.get("nets") or {}
        return float(n.get("moitie_1") or 0.0) + float(n.get("moitie_2") or 0.0)
    for e in sorted((e for e in (r.get("essais") or []) if e.get("nets")), key=_net12, reverse=True):
        c = e.get("config")
        if c and c not in cands:
            cands.append(c)
        if len(cands) >= maximum:
            break
    return cands


def annoter_robustesse(d: DonneesReplay, r: dict[str, Any], *,
                       evaluer_ab: Callable[..., dict] = run_ab_replay) -> dict[str, Any]:
    """Attache `r['robustesse']` : PBO + seuil de bruit du multiple-testing sur les candidats.
    C'est CE qui rend la recherche extrême SÛRE — plus on essaie de configs, plus la barre monte."""
    try:
        cands = _candidats_pour_robustesse(r)
        M = _matrice_robustesse(d, cands, evaluer_ab=evaluer_ab)
        totaux = [sum(row) for row in M]
        sigma = _stats.pstdev(totaux) if len(totaux) > 1 else 0.0
        gagnant = max(totaux) if totaux else None
        r["robustesse"] = robustesse_selection.verdict_robustesse(
            M, len(r.get("essais") or []), net_gagnant=gagnant, sigma_null=(sigma or None))
    except Exception as exc:  # noqa: BLE001 — la robustesse est un juge, jamais un point de panne
        r["robustesse"] = {"verdict": "non mesurable", "pbo": None, "motif": str(exc)[:80]}
    return r


SEUIL_CRIBLE_CANDIDATS = 20_000
FRACTION_CRIBLE = 0.25
#: 21/07 matin : le crible sur 25 % de 262k = 65 000 candidats x 600 configs a tue le run de
#: la nuit EN SILENCE (aucun print, aucun etat). Un crible est une PASSOIRE, pas une preuve :
#: 12 000 candidats recents suffisent largement pour reperer un net<=0 evident.
CAP_CRIBLE_CANDIDATS = 12_000


def _cribler_configs(d: DonneesReplay, configs: list[dict], *,
                     screen: Callable[..., dict] = net_baseline_seul) -> list[dict]:
    """SUCCESSIVE HALVING : sur les grosses populations (copy : 262k), on crible d'abord chaque
    config sur le QUART LE PLUS RECENT (structure temporelle préservée) ; seules celles à net > 0
    passent à l'évaluation complète. Le crible n'admet personne, il ÉPARGNE du calcul aux perdants.

    22/07 (« améliore notre façon de faire ») — DEUX économies, résultat IDENTIQUE (testé) :
    (1) le SCREEN est `net_baseline_seul` (bras A seul) et non `run_ab_replay` : plus de bras B, de
    vetos ni d'estimateur de vol calculés pour rien ; (2) l'index des marks est bâti UNE fois
    (run_ab_replay le reconstruisait à chaque config) et le filtrage est mémoïsé par preset."""
    if len(d.candidats) < SEUIL_CRIBLE_CANDIDATS or not configs:
        return configs
    tries = sorted(d.candidats, key=lambda c: float(c.get("recorded_at") or 0.0))
    n = min(int(len(tries) * FRACTION_CRIBLE), CAP_CRIBLE_CANDIDATS)
    recent = tries[-n:]
    print("  crible multi-fidelite : %d configs sur les %d candidats les plus recents..."
          % (len(configs), len(recent)), flush=True)
    idx_marks = marks_by_coin(d.marks)                    # UNE fois, réutilisé par toutes les configs
    cache_f: dict[tuple, list] = {}
    def _filtre(cfg: dict) -> list:
        cle = tuple(sorted((cfg.get("filtres") or {}).items()))
        r = cache_f.get(cle)
        if r is None:
            r = cache_f[cle] = filtrer_candidats(recent, cfg.get("filtres"))
        return r
    retenues = []
    for i, cfg in enumerate(configs, 1):
        f = _filtre(cfg)
        try:
            r = screen(f, idx_marks, base_config=_sltp(cfg),
                       horizon_min=float(cfg.get("horizon_min") or 60.0),
                       cost_bps=DEFAULT_COST_BPS)
            if float((r.get("arm_a") or {}).get("net_total_usd") or 0.0) > 0.0:
                retenues.append(cfg)
        except Exception:  # noqa: BLE001 — un crible qui explose laisse passer (porte derriere)
            retenues.append(cfg)
        if i % 25 == 0:                         # jamais plus de ~1 min de silence
            print("    crible %d/%d (%d retenues)" % (i, len(configs), len(retenues)),
                  flush=True)
    print("  crible : %d/%d configs passent a l'evaluation complete"
          % (len(retenues), len(configs)), flush=True)
    return retenues


# ================================================================ 6. TOUS les modules d'un coup

def chercher_module(root: str | Path, strat: str, *, budget_s: float | None = None,
                    max_essais: int | None = None) -> dict[str, Any]:
    """AIGUILLAGE : chaque module vers SA vraie grille. 22/07 — le carry n'est PAS directionnel,
    il a sa propre grille (funding × durée, `chercher_carry`) ; le SL/TP est l'outil de COPY. Copy
    (et fallback) passent par `chercher` (grille SL/TP + filtres copy)."""
    if strat == "carry":
        return chercher_carry(root, budget_s=budget_s)
    return chercher(root, strategie=strat, configs=grille_large(), max_essais=max_essais,
                    budget_s=budget_s, s_arreter_au_premier=False, raffiner=True)


def chercher_toutes(root: str | Path, *, max_essais_par_strategie: int | None = None,
                    budget_s_par_module: float | None = 7_200.0,
                    parallele: bool = False) -> dict[str, Any]:
    """Recherche PAR module (populations jamais mélangées), grille LARGE, rapports écrits À LA FIN
    QUOI QU'IL ARRIVE. Chaque module est blindé (s'il explose, verdict ERREUR, les autres
    continuent) et borné par son budget. AUCUN plafond de population : on teste TOUT.

    🔴 22/07 — SÉQUENTIEL PAR DÉFAUT (HUD en direct + ETA mesurée). Le `ProcessPoolExecutor` a été
    RETIRÉ : il DEADLOCKAIT sur grosses populations (le blocage vu par Flo à 114 min sur budget 90).
    Le séquentiel streame en direct et ne peut pas se bloquer. Le PARALLÉLISME est désormais OPT-IN
    (`parallele=True` ou env `TOUT_TESTER_RECHERCHE_PARALLELE=1`) et passe par des SOUS-PROCESSUS
    ISOLÉS (`recherche_parallele`, sortie en fichiers, tuables) — jamais le pool qui deadlockait."""
    resultats: dict[str, Any] = {}
    import os as _os
    veut_par = parallele or _os.environ.get(
        "TOUT_TESTER_RECHERCHE_PARALLELE", "").strip().lower() in ("1", "true", "oui")
    if veut_par:
        remplir_en_parallele(root, budget_s_par_module, max_essais_par_strategie,
                             STRATEGIES_MODULES, resultats)
    else:
        total = len(STRATEGIES_MODULES) + 1                   # +1 pour cross_venue (progression run)
        for i, strat in enumerate(STRATEGIES_MODULES, 1):
            print("=== module %s (%d/%d) ===" % (strat, i, total), flush=True)
            try:
                resultats[strat] = chercher_module(root, strat, budget_s=budget_s_par_module,
                                                   max_essais=max_essais_par_strategie)
            except Exception as exc:  # noqa: BLE001 — un module qui explose ne tue plus la nuit
                print("  !! module %s en ERREUR : %s" % (strat, str(exc)[:200]), flush=True)
                resultats[strat] = {"statut": "ERREUR", "strategie": strat,
                                    "motif": str(exc)[:300], "essais": []}
    print("=== module cross_venue ===", flush=True)
    try:
        resultats["cross_venue"] = chercher_cross_venue(root, max_essais=max_essais_par_strategie)
    except Exception as exc:  # noqa: BLE001
        print("  !! module cross_venue en ERREUR : %s" % str(exc)[:200], flush=True)
        resultats["cross_venue"] = {"statut": "ERREUR", "strategie": "cross_venue",
                                    "motif": str(exc)[:300], "essais": []}
    try:
        _ecrire_pepites(root, resultats)
        _ecrire_resultats_md(root, resultats)
    except OSError:
        print("  (rapports inecrivables)")
    print("", flush=True)
    print("=" * 62, flush=True)
    print(" RECOMMANDATIONS (le detail est dans RESULTATS_RECHERCHE.md)", flush=True)
    print("=" * 62, flush=True)
    for strat, r in resultats.items():
        print("  %-11s -> %s" % (strat, recommandation(strat, r)), flush=True)
    return resultats


def recommandation(strat: str, r: dict[str, Any]) -> str:
    """La CONCLUSION en français, dérivée des résultats, jamais inventée. Quatre cas : pépite OR
    (à câbler en paper), ARGENT (à surveiller), espace épuisé (le réglage n'existe pas dans ces
    données), données insuffisantes."""
    # 21/07 — LES LOIS MESUREES : une pépite qui retombe sur un mécanisme déjà RÉFUTÉ par nos
    # chiffres le dit ICI (le chiffre à battre, pas un interdit) — sinon on ré-implémente un perdant.
    rappel = ""
    try:
        from hl_observer.research.lois_mesurees import avertissement as _avert
        a = _avert(strat)
        if a:
            rappel = " ⚠️ RAPPEL — %s" % a
    except Exception:  # noqa: BLE001 — un rappel absent ne casse jamais une recommandation
        rappel = ""
    # 22/07 — GARDE-FOU PBO : une recherche extrême peut promouvoir par pure chance. Si la
    # PROCÉDURE sur-ajuste, AUCUN « FAIS ÇA » même avec un beau net (la barre monte avec l'ambition).
    rob = r.get("robustesse") or {}
    if rob.get("pbo") is not None and rob.get("verdict") == "SUR_AJUSTE":
        return ("NE FAIS RIEN ENCORE : la recherche SUR-AJUSTE (PBO %.0f%% > 50%% sur %d essais) "
                "— le meilleur calibrage ne généralise pas hors échantillon. Élargis les données "
                "ou réduis l'espace de recherche avant de croire un promu.%s"
                % (100.0 * rob["pbo"], rob.get("n_essais") or 0, rappel))
    promus = sorted((r.get("promus") or []),
                    key=lambda p: (p.get("rang") != "OR",
                                   -float((p.get("nets") or {}).get("stress") or 0.0)))
    if promus:
        p = promus[0]
        return ("FAIS ÇA : câble `%s` en paper (rang %s, nets %s%s) et juge-le au profit "
                "factor sur une semaine avant d'y croire.%s"
                % (p["config"], p.get("rang", "?"), p.get("nets"),
                   ", folds %s" % p["folds_vivants"] if p.get("folds_vivants") else "", rappel))
    if r.get("statut") == "ERREUR":
        return "PANNE À RÉPARER : ce module a explosé (%s) — envoie ça à Claude." \
            % (r.get("motif") or "?")
    if r.get("statut") == "INSUFFISANT":
        return "PATIENCE : %s — laisse les collecteurs accumuler, relance demain." \
            % (r.get("motif") or "données insuffisantes")
    essais = r.get("essais") or []
    if essais:
        pires = [e for e in essais if e.get("nets")]
        if pires and all(float((e["nets"].get("moitie_1") or 0))
                         + float((e["nets"].get("moitie_2") or 0)) < 0 for e in pires):
            return ("ARRÊTE DE CHERCHER ICI : aucun réglage ne rend ce module positif dans "
                    "ces données (%d essais, tous négatifs) — le verrou actuel est la bonne "
                    "décision ; la voie passe par un AUTRE mécanisme, pas un autre réglage."
                    % len(essais))
        return ("PRESQUE : %d essais jugés, des configs frôlent les portes — regarde les "
                "presque-promus ci-dessus, et relance après 24 h de données en plus."
                % len(essais))
    if int(r.get("n_candidats") or 0) > 0 and r.get("statut") == "ESPACE_EPUISE":
        return ("LE CRIBLE A TOUT ÉLIMINÉ : sur les %d candidats, AUCUNE des ~600 combinaisons "
                "n'est même positive sur l'époque récente — ce module n'a pas de réglage, il a "
                "un verrou justifié. La voie passe par un autre mécanisme."
                % int(r["n_candidats"]))
    return "RIEN À JUGER ce tour-ci."


def _ecrire_resultats_md(root: str | Path, resultats: dict[str, Any]) -> None:
    """Le rapport COMPLET : profil de données, pépites OR/ARGENT (nets + folds), meilleurs
    presque-promus avec la porte qui les a tués, et un bloc JSON machine-lisible. Écriture atomique."""
    import datetime as _dt
    import json as _json
    import os as _os
    lignes = ["# RÉSULTATS DE RECHERCHE — replay multi-modules",
              "", "_Généré le %s. Portes : 2 moitiés purgées+embargo, coûts ×1,5, plateau "
              "des voisins ; rang OR = net>0 sur ≥3/4 folds purgés (CPCV) en plus. "
              "Crible multi-fidélité sur les grosses populations. AUCUNE promesse : une "
              "pépite est un candidat à valider en paper._"
              % _dt.datetime.now().strftime("%d/%m/%Y %H:%M"), ""]
    for strat, r in resultats.items():
        lignes.append("## Module `%s` — statut %s" % (strat, r.get("statut")))
        lignes.append("- candidats évalués : %s · essais jugés : %d"
                      % (r.get("n_candidats", "?"), len(r.get("essais") or [])))
        promus = sorted((r.get("promus") or []),
                        key=lambda p: (p.get("rang") != "OR",
                                       -float((p.get("nets") or {}).get("stress") or 0.0)))
        if promus:
            lignes.append("- **%d pépite(s)** :" % len(promus))
            for i, p in enumerate(promus[:8], 1):
                lignes.append("  %d. [%s] `%s` — nets %s%s"
                              % (i, p.get("rang", "?"), p["config"], p.get("nets"),
                                 (" · folds %s %s" % (p.get("folds_vivants"),
                                                      p.get("folds_nets"))
                                  if p.get("folds_nets") else "")))
        elif r.get("motif"):
            lignes.append("- %s" % r["motif"])
        # les presque-promus les plus instructifs (la porte tueuse est ecrite dans l'essai)
        rates = [e for e in (r.get("essais") or [])
                 if e.get("verdict") == "REJETE" and e.get("nets")]
        rates.sort(key=lambda e: float((e.get("nets") or {}).get("moitie_1") or 0.0)
                   + float((e.get("nets") or {}).get("moitie_2") or 0.0), reverse=True)
        if rates:
            lignes.append("- presque-promus (à comprendre, pas à repêcher) :")
            for e in rates[:3]:
                lignes.append("  - `%s` — nets %s%s"
                              % (e["config"], e.get("nets"),
                                 " · %s" % e["instabilite"] if e.get("instabilite") else ""))
        if r.get("honnetete"):
            lignes.append("- ⚠️ %s" % r["honnetete"])
        lignes.append("- **👉 RECOMMANDATION : %s**" % recommandation(strat, r))
        lignes.append("")
    lignes.append("## En une phrase par module")
    lignes.append("")
    for strat, r in resultats.items():
        lignes.append("- **%s** → %s" % (strat, recommandation(strat, r)))
    lignes.append("")
    lignes.append("<!-- JSON_RESULTATS")
    lignes.append(_json.dumps(
        {s: {k: v for k, v in r.items() if k != "essais"} for s, r in resultats.items()},
        ensure_ascii=False, default=str))
    lignes.append("-->")
    p = Path(root) / "runtime" / "replay" / "RESULTATS_RECHERCHE.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".md.tmp")
    tmp.write_text("\n".join(lignes), encoding="utf-8")
    _os.replace(tmp, p)


def _ecrire_pepites(root: str | Path, resultats: dict[str, Any]) -> None:
    lignes = ["# PÉPITES — recherche de scénarios par module", "",
              "_Replay sur données enregistrées : un PROMU a survécu à deux moitiés "
              "temporelles disjointes (embargo), aux coûts ×1,5 et au plateau des voisins. "
              "Ce n'est PAS une promesse de PnL : c'est un candidat à valider en paper._", ""]
    for strat, r in resultats.items():
        lignes.append("## %s — %s" % (strat, r.get("statut")))
        promus = sorted((r.get("promus") or []),
                        key=lambda p: float((p.get("nets") or {}).get("stress") or 0.0),
                        reverse=True)
        if promus:
            lignes.append("- **%d pépite(s)**, classées par net SOUS STRESS ×1,5 :" % len(promus))
            for i, p in enumerate(promus[:5], 1):
                lignes.append("  %d. `%s` — nets %s" % (i, p["config"], p.get("nets")))
        elif r.get("gagnant"):
            lignes.append("- **PÉPITE** : `%s`" % r["gagnant"])
        if r.get("motif"):
            lignes.append("- %s" % r["motif"])
        if r.get("honnetete"):
            lignes.append("- ⚠️ %s" % r["honnetete"])
        lignes.append("- essais jugés : %d" % len(r.get("essais") or []))
        lignes.append("")
    p = Path(root) / "runtime" / "replay" / "PEPITES.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".md.tmp")
    tmp.write_text("\n".join(lignes), encoding="utf-8")
    import os as _os
    _os.replace(tmp, p)


__all__ = ["DonneesReplay", "grille_configs", "grille_large", "voisins", "raffiner_autour",
           "evaluer_sur_moities", "porte_robuste", "chercher", "chercher_cross_venue",
           "chercher_toutes", "evaluer_episodes_cross_venue", "repertoire_replay_consolide",
           "ALIAS_STRATEGIES", "STRATEGIES_MODULES",
           "MIN_TRADES_PAR_MOITIE", "MIN_PF_PAR_MOITIE", "STRESS_COUTS",
           "FRACTION_VOISINS_VIVANTS", "ETAT_RECHERCHE_RELPATH"]
