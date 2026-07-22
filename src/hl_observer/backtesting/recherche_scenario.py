"""RECHERCHE DE SCÉNARIO — l'étage au-dessus du replay A/B, optimisé pour trouver un
scénario qui SURVIT, pas un pic qui brille.

DEMANDE DE FLO (20/07) : « le replay doit être optimisé au maximum pour trouver le scénario
parfait ». Ce projet a déjà payé pour savoir ce que « parfait » veut dire : le faux
« 1 sur 1M » était un gagnant chanceux sorti de ~0 donnée ; 0 calibrage SL/TP n'a jamais
tenu hors échantillon ; la coupe train/test fuyait à 68 %. Donc ici, « optimisé au
maximum » = trois choses PRÉCISES :

  1. VITESSE — les données (candidats + marks, ~500k lignes) sont chargées UNE fois et
     réutilisées pour toutes les configurations. C'est le levier n°1 : sans ça, chaque
     config repaierait des secondes de parsing.
  2. HONNÊTETÉ — chaque config est jugée sur DEUX MOITIÉS TEMPORELLES DISJOINTES avec
     EMBARGO (les candidats à moins d'un horizon de la coupe sont jetés des deux côtés :
     aucune fenêtre d'outcome ne chevauche la frontière). Gagner sur les deux moitiés,
     c'est le minimum vital contre le gagnant chanceux.
  3. STABILITÉ — un candidat à la promotion doit vivre sur un PLATEAU : la majorité de
     ses VOISINS (SL±, TP±) doivent aussi être profitables. Un pic isolé dans la grille
     est un artefact, pas un scénario (W8).

La porte finale exige EN PLUS la survie à un stress des coûts ×1,5 (F29) : un scénario qui
meurt quand les frais respirent n'était pas un scénario.

REPLAY-only : données enregistrées, aucun réseau, aucun ordre. La session live n'est pas
touchée (lecture seule des shards, état de recherche dans son propre fichier).
"""
from __future__ import annotations


from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from hl_observer.backtesting.ab_flag_replay import (
    DEFAULT_COST_BPS, load_jsonl, run_ab_replay,
)
from hl_observer.paper_trading.sl_tp import SLTPConfig
from hl_observer.backtesting.boucle_objectif_replay import boucle_objectif

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
    """Où vivent les consolidés. 🔴 21/07 : le consolidateur (`merge_replay`) écrit dans
    `_merged/` (dossier DIFFÉRENT pour ne pas se re-lire) — mais la recherche lisait la
    RACINE de runtime/replay → INSUFFISANT devant 331 366 candidats consolidés. Un seul
    résolveur, partagé par la recherche, le PnL des refus et le rapport (§10)."""
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
        """21/07 (Flo : « les meilleurs scénarios pour TOUS nos modules ») : chargement
        PAR STRATÉGIE — mélanger 262k signaux copy et les candidats carry dans une même
        grille donnerait le scénario moyen de RIEN. `strategie=None` garde tout (compat)."""
        base = repertoire_replay_consolide(root)
        if not (base / "candidates.jsonl").exists():
            return cls(candidats=[], marks=[])            # dossier vide = INSUFFISANT honnete
        cands = load_jsonl(str(base / "candidates.jsonl"))
        if strategie is not None:
            # 🔴 22/07 — bucketing par STRATEGIE EFFECTIVE (label OU inference de champs), plus
            # par l'alias aveugle qui mappait tout « ? » en copy. Un candidat carry/arbitrage
            # sans label est desormais reconnu par SES champs, jamais range en copy par accident.
            from hl_observer.ops.strategie_candidat import strategie_effective
            cible = ALIAS_STRATEGIES.get(strategie, {strategie})
            cands = [c for c in cands if strategie_effective(c) in cible]
        return cls(candidats=cands, marks=load_jsonl(str(base / "marks.jsonl")))

    def moities_avec_embargo(self, horizon_min: float) -> tuple[list[dict], list[dict]]:
        """Coupe TEMPORELLE médiane + embargo d'un horizon DE CHAQUE CÔTÉ de la frontière.

        La leçon du 13/07 (fuite à 68 %) : sans embargo, les outcomes des derniers candidats
        de la moitié 1 se réalisent DANS la zone de la moitié 2 — les deux moitiés ne sont
        plus indépendantes, et le « hors échantillon » n'en est pas un.
        """
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
    """21/07 (« il doit nous trouver des pépites ! ») : le FILET s'élargit — SL 20→120,
    TP 40→300, horizons 15 min→4 h, CROISÉS avec les 4 presets de filtres (~600 configs).
    Les MAILLES ne bougent pas : chaque config passe les mêmes portes (deux moitiés +
    stress ×1,5 + plateau). Plus de candidats au concours, jamais un concours plus facile."""
    for base in grille_configs(sls=(20.0, 30.0, 40.0, 60.0, 90.0, 120.0),
                               tps=(40.0, 50.0, 70.0, 100.0, 150.0, 200.0, 300.0),
                               horizons=(15.0, 30.0, 60.0, 120.0, 240.0)):
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
    # sous-population du preset de filtres (21/07) — APRES la coupe temporelle : la coupe ne
    # depend que du temps, le filtre ne peut pas la biaiser.
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
             evaluer_ab: Callable[..., dict] = run_ab_replay) -> dict[str, Any]:
    """Grille -> porte deux-moitiés+stress -> PLATEAU des voisins -> verdict.

    Le contrôle de plateau vit DANS la porte du /goal : un candidat qui passe les moitiés
    mais dont les voisins meurent est rejeté (REJETE_INSTABLE dans son rapport) — un pic
    isolé n'est pas promu, jamais.
    """
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
    liste_configs = _cribler_configs(d, liste_configs, evaluer_ab=evaluer_ab)
    r = boucle_objectif(
        liste_configs,
        evaluer, porte_avec_plateau,
        etat_path=etat, max_essais=max_essais, budget_s=budget_s,
        s_arreter_au_premier=s_arreter_au_premier)
    # ── RAFFINAGE grossier -> fin (21/07, « ultra intelligent ») : on resserre la grille
    # (pas/2) autour des PROMUS et des meilleurs presque-promus (net m1+m2 les plus hauts).
    # Les raffines passent LES MEMES portes ; la dedup par cle (etat) evite tout double calcul.
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
                                 s_arreter_au_premier=False)
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


def chercher_cross_venue(root: str | Path, *, series: list[dict] | None = None,
                         max_essais: int | None = None) -> dict[str, Any]:
    """La recherche cross-venue — MÊMES portes (deux moitiés temporelles + stress coûts ×1,5
    + plateau des seuils voisins). ⚠️ EXPLORATOIRE : ne touche pas au verdict 72 h du
    protocole (barres pré-écrites) — un seuil optimisé ici devra survivre au hors-échantillon
    APRÈS les 72 h avant d'exister en live."""
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
    return r


# ================================================================ 5bis. les canons du 21/07
# Recherche X/GitHub (demande de Flo) : CPCV/folds purges (Lopez de Prado — PBO plus bas que
# le walk-forward simple) + successive halving (multi-fidelite : cribler sur un sous-echantillon
# AVANT de payer l'evaluation complete). References : ml4t/diagnostic, Optuna Hyperband.

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
    """OR / ARGENT (post-porte, sur les promus seulement — 4 evals, pas cher car ils sont
    rares) : OR = net > 0 sur >= 3 des 4 folds purges EN PLUS de la porte. L'ARGENT reste
    une pepite ; l'OR a survecu a une decoupe de plus."""
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


SEUIL_CRIBLE_CANDIDATS = 20_000
FRACTION_CRIBLE = 0.25
#: 21/07 matin : le crible sur 25 % de 262k = 65 000 candidats x 600 configs a tue le run de
#: la nuit EN SILENCE (aucun print, aucun etat). Un crible est une PASSOIRE, pas une preuve :
#: 12 000 candidats recents suffisent largement pour reperer un net<=0 evident.
CAP_CRIBLE_CANDIDATS = 12_000


def _cribler_configs(d: DonneesReplay, configs: list[dict], *,
                     evaluer_ab: Callable[..., dict] = run_ab_replay) -> list[dict]:
    """SUCCESSIVE HALVING (multi-fidelite) : sur les grosses populations (copy : 262k), payer
    3 evaluations completes par config est un gachis — on crible d'abord chaque config sur le
    QUART LE PLUS RECENT (structure temporelle preservee, jamais un sous-echantillon aleatoire)
    et seules les configs a net > 0 au crible passent a l'evaluation complete. Un crible
    n'admet jamais personne : il ne fait qu'EPARGNER du calcul aux perdants evidents."""
    if len(d.candidats) < SEUIL_CRIBLE_CANDIDATS or not configs:
        return configs
    tries = sorted(d.candidats, key=lambda c: float(c.get("recorded_at") or 0.0))
    n = min(int(len(tries) * FRACTION_CRIBLE), CAP_CRIBLE_CANDIDATS)
    recent = tries[-n:]
    print("  crible multi-fidelite : %d configs sur les %d candidats les plus recents..."
          % (len(configs), len(recent)), flush=True)
    retenues = []
    for i, cfg in enumerate(configs, 1):
        f = filtrer_candidats(recent, cfg.get("filtres"))
        try:
            r = evaluer_ab(f, d.marks, base_config=_sltp(cfg),
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

def chercher_toutes(root: str | Path, *, max_essais_par_strategie: int | None = None,
                    budget_s_par_module: float | None = 7_200.0) -> dict[str, Any]:
    """« Il doit replay TOUS nos modules » (21/07). Une recherche PAR module (populations
    jamais mélangées), grille LARGE (le filet s'élargit, les mailles jamais), rapports écrits
    À LA FIN QUOI QU'IL ARRIVE. Leçons du run de la nuit (mort en silence pendant copy,
    AUCUN rapport) : (1) chaque module est blindé — s'il explose, son verdict devient
    ERREUR et les AUTRES continuent ; (2) budget de 2 h par module — BUDGET_EPUISE honnête
    et reprise au prochain lancement (états par module), jamais une nuit avalée."""
    resultats: dict[str, Any] = {}
    for strat in STRATEGIES_MODULES:
        print("=== module %s ===" % strat, flush=True)
        try:
            resultats[strat] = chercher(root, strategie=strat, configs=grille_large(),
                                        max_essais=max_essais_par_strategie,
                                        budget_s=budget_s_par_module,
                                        s_arreter_au_premier=False, raffiner=True)
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
    """21/07 (Flo : « le rapport doit dire : c'est mieux si on fait ÇA avec le carry... ») —
    la CONCLUSION en français, dérivée des résultats, jamais inventée. Quatre cas :
    pépite OR (à câbler en paper), pépite ARGENT (à surveiller), espace épuisé (le réglage
    n'existe pas dans ces données — le dire épargne des semaines), données insuffisantes."""
    # 21/07 — LES LOIS MESUREES. Une pepite qui retombe sur un mecanisme deja REFUTE par nos
    # propres chiffres doit le dire ICI, au moment ou elle est proposee. Sinon le rapport
    # recommande d'implementer quelque chose qu'on a deja prouve perdant — et personne ne s'en
    # souvient trois semaines plus tard. Ce n'est pas un interdit : c'est le chiffre a battre.
    rappel = ""
    try:
        from hl_observer.research.lois_mesurees import avertissement as _avert
        a = _avert(strat)
        if a:
            rappel = " ⚠️ RAPPEL — %s" % a
    except Exception:  # noqa: BLE001 — un rappel absent ne casse jamais une recommandation
        rappel = ""
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
    """21/07 (Flo : « un fichier .md contenant TOUS les résultats pour que tu puisses les
    examiner ») — le rapport COMPLET : profil de données, pépites OR/ARGENT avec leurs nets
    et leurs folds, meilleurs presque-promus avec la porte qui les a tués, et un bloc JSON
    embarqué (machine-lisible) pour l'examen par Claude. Écriture atomique."""
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
