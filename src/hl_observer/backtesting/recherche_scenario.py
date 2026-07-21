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
    def charger(cls, root: str | Path) -> "DonneesReplay":
        base = repertoire_replay_consolide(root)
        return cls(candidats=load_jsonl(str(base / "candidates.jsonl")),
                   marks=load_jsonl(str(base / "marks.jsonl")))

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
             evaluer_ab: Callable[..., dict] = run_ab_replay) -> dict[str, Any]:
    """Grille -> porte deux-moitiés+stress -> PLATEAU des voisins -> verdict.

    Le contrôle de plateau vit DANS la porte du /goal : un candidat qui passe les moitiés
    mais dont les voisins meurent est rejeté (REJETE_INSTABLE dans son rapport) — un pic
    isolé n'est pas promu, jamais.
    """
    d = donnees if donnees is not None else DonneesReplay.charger(root)
    if not d.candidats:
        return {"statut": "INSUFFISANT", "motif": "aucun candidat consolide "
                "(lancer la consolidation W2 d'abord)", "essais": []}

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

    return boucle_objectif(
        configs if configs is not None else grille_configs(),
        evaluer, porte_avec_plateau,
        etat_path=Path(root) / ETAT_RECHERCHE_RELPATH,
        max_essais=max_essais, budget_s=budget_s)


__all__ = ["DonneesReplay", "grille_configs", "voisins", "raffiner_autour",
           "evaluer_sur_moities", "porte_robuste", "chercher",
           "MIN_TRADES_PAR_MOITIE", "MIN_PF_PAR_MOITIE", "STRESS_COUTS",
           "FRACTION_VOISINS_VIVANTS", "ETAT_RECHERCHE_RELPATH"]
