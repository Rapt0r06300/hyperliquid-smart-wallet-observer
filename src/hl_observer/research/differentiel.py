r"""#3 + #15 — LE SCORE **DIFFÉRENTIEL** et les **ZONES VIERGES**.

═══════════════════════════════════════════════════════════════════════════════════════════════
#3 — ON NOTAIT LE NIVEAU. IL FALLAIT NOTER LE **DELTA**.
═══════════════════════════════════════════════════════════════════════════════════════════════

Un repo qui implémente **12 concepts** dont **on en a déjà 11** vaut… **une** idée.
Un repo qui en implémente **3** dont on en a **zéro** en vaut… **trois**.

    ***Le score doit comparer leur code AU NÔTRE, pas au vide.***

L'ancien score aurait mis le premier tout en haut et le second nulle part. **Et il aurait eu
tort dans les deux cas.** C'est la même faute que les étoiles : *une métrique qui a l'air
rigoureuse et qui mesure autre chose.*

On indexe donc **notre propre code** (le vrai, celui de `src/hl_observer/`), et le score d'un
repo devient : **ce qu'il a QUE NOUS N'AVONS PAS.**

═══════════════════════════════════════════════════════════════════════════════════════════════
#15 — CE QUE **PERSONNE** NE FAIT
═══════════════════════════════════════════════════════════════════════════════════════════════

Le contraire du grep. Après avoir scanné le corpus entier :

    **quels concepts ne sont couverts par AUCUN repo ?**

    Un concept que **personne** n'implémente est soit **inutile**, soit **inexploité**.
    ***Les deux méritent d'être sus — et le second, c'est là que vit un edge.***

    *Si 5 000 personnes ont essayé le market making et zéro n'a publié un carry HL delta-neutre
    documenté, ce n'est pas parce que c'est bête. C'est peut-être parce que personne n'a regardé.*

PUR : aucun réseau. Lecture seule.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# CE QU'ON A DÉJÀ — **indexé depuis notre VRAI code**, pas depuis ma mémoire.
#
# 🔒 *Une liste tenue à la main diverge du code dès le lendemain.* On la DÉRIVE.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
# concept -> (motifs qui prouvent qu'on l'a, où on l'a)
NOS_CAPACITES: dict[str, tuple[tuple[str, ...], str]] = {
    "frais_reels": ((r"TAKER_PERP_BPS", r"nos_frais", r"GRILLE_PERPS"),
                    "`fees/hyperliquid_fees.py` — la source unique"),
    "edge_net_apres_couts": ((r"compute_net_edge", r"plancher_edge_net_bps", r"PLANCHER_NET_BPS"),
                             "`edge/edge_calculator.py` + la porte du noyau"),
    "profondeur_du_carnet": ((r"marcher_dans_le_carnet", r"spot_depth"),
                             "`market/spot_depth.py` — branché le 14/07"),
    "toxicite_du_flux": ((r"faut_il_s_abstenir", r"\bvpin\b", r"flow_toxicity"),
                         "`market/flow_toxicity.py` — VPIN sur horloge de VOLUME"),
    "contraintes_exchange": ((r"valider_ordre", r"MinTradeNtl", r"BadAloPx"),
                             "`market/execution_constraints.py`"),
    "disjoncteurs_session": ((r"evaluer_session", r"session_gate", r"blocks_new_entries"),
                             "`risk/session_gate.py` — les 11 gates V19"),
    "verrou_de_cote": ((r"only_per_side", r"side_lock"),
                       "`risk/side_lock.py` — 19/21 SHORT"),
    "carry_delta_neutre": ((r"carry_runtime", r"carry_scanner", r"COUT_ALLER_RETOUR_TAKER_BPS"),
                           "`strategies/carry_*.py` — **notre seule piste positive**"),
    "funding_historique": ((r"funding_history", r"fundingHistory"),
                           "`hyperliquid/rest_info_client.py` — 365 j"),
    "ledger_de_paper": ((r"PaperLedger", r"paper_ledger", r"PaperIntent"),
                        "`paper_trading/` — la vérité du PnL"),
    "detection_lookahead": ((r"lookahead_detector", r"garch11_variance"),
                            "`testing/lookahead_detector.py`"),
    "replay_deterministe": ((r"replay_shadow", r"replay_determin"),
                            "`runtime/replay_shadow.py`"),
    # ── 🔴 CE QU'ON N'A **PAS** — et c'est ça qu'on cherche. ──────────────────────────────────
    "modele_de_file": ((r"qty_ahead", r"queue_position", r"ProbQueue"),
                       "🔴 **RIEN.** *Notre fill maker est « 10 % du flux » — un chiffre INVENTÉ.*"),
    "kappa_intensite": ((r"kappa", r"fill_intensity"),
                        "🔴 **RIEN.** *Jamais mesuré.*"),
    "impact_de_marche": ((r"market_impact", r"square_root_impact", r"almgren"),
                         "🔴 **RIEN.** *L'hypothèse qui expliquerait nos −7,97 bps.*"),
    "selection_adverse": ((r"markout", r"adverse_select"),
                          "🔴 **RIEN.** *Le maker est rempli quand il a TORT.*"),
    "parite_backtest_live": ((r"backtest_live_parity", r"parity"),
                             "⚠️ **module écrit, jamais appliqué.** *Le critère de hftbacktest : "
                             "le replay d'une période doit reproduire le live de cette période.*"),
    "cascade_de_liquidation": ((r"liquidation_cascade",),
                               "⚠️ recorder branché, **jamais mesuré** — 🎯 la dernière piste"),
    "modele_de_rejet_d_ordre": ((r"order_reject", r"rejected_by_exchange"),
                                "🔴 **RIEN.** *L'exchange rejette quand il est surchargé — "
                                "c'est-à-dire QUAND ÇA BOUGE. Nos stops.*"),
}


@dataclass(slots=True)
class NotreEtat:
    """Ce qu'on a **vraiment**, mesuré sur notre code. *Pas ce que je crois qu'on a.*"""
    acquis: dict[str, str] = field(default_factory=dict)     # concept -> où
    manquants: dict[str, str] = field(default_factory=dict)  # concept -> pourquoi ça manque

    def as_dict(self) -> dict[str, Any]:
        return {"acquis": self.acquis, "manquants": self.manquants,
                "n_acquis": len(self.acquis), "n_manquants": len(self.manquants)}


def indexer_notre_code(racine_src: Path,
                       capacites: Mapping[str, tuple[tuple[str, ...], str]] = NOS_CAPACITES,
                       ) -> NotreEtat:
    """🔒 **On lit NOTRE code.** *Une liste tenue à la main diverge dès le lendemain.*

    Si le fichier n'existe pas -> le concept est **MANQUANT**, et on le dit.
    *Ne pas savoir n'est pas « on l'a ».*
    """
    blob = ""
    if racine_src.exists():
        for p in racine_src.rglob("*.py"):
            try:
                blob += p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

    etat = NotreEtat()
    for concept, (motifs, ou) in capacites.items():
        present = any(re.search(m, blob, re.IGNORECASE) for m in motifs)
        if present and not ou.startswith(("🔴", "⚠️")):
            etat.acquis[concept] = ou
        elif present:
            # présent dans le code mais **marqué comme non branché / non mesuré**
            etat.manquants[concept] = ou
        else:
            etat.manquants[concept] = ou if ou.startswith(("🔴", "⚠️")) else \
                "🔴 introuvable dans notre code"
    return etat


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# LE SCORE DIFFÉRENTIEL — *ce qu'ils ont QUE NOUS N'AVONS PAS.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
POIDS_NOUVEAU = 25.0      # un concept qu'on n'a **pas du tout** : c'est ça qu'on cherche
POIDS_CONNU = 2.0         # un concept qu'on a déjà : *une validation externe, pas une découverte*


@dataclass(slots=True)
class Delta:
    score: float
    nouveaux: list[str]
    deja_vus: list[str]
    pourquoi: str

    def as_dict(self) -> dict[str, Any]:
        return {"score_differentiel": round(self.score, 1),
                "concepts_NOUVEAUX_pour_nous": self.nouveaux,
                "concepts_qu_on_a_deja": self.deja_vus,
                "pourquoi": self.pourquoi}


def score_differentiel(concepts_du_repo: Sequence[str], notre_etat: NotreEtat) -> Delta:
    """🔑 **Le score, enfin, mesure le DELTA.**

    *Un repo qui a 12 concepts dont on en a 11 vaut UNE idée.
     Un repo qui en a 3 dont on en a zéro en vaut TROIS.*
    """
    nouveaux = [c for c in concepts_du_repo if c in notre_etat.manquants]
    deja = [c for c in concepts_du_repo if c in notre_etat.acquis]
    s = POIDS_NOUVEAU * len(nouveaux) + POIDS_CONNU * len(deja)

    if nouveaux:
        pq = ("🔑 Il apporte **%d concept(s) qu'on N'A PAS** : %s. "
              "*C'est exactement ce qu'on cherche.*" % (len(nouveaux), ", ".join(nouveaux)))
    elif deja:
        pq = ("Il ne fait que ce qu'on **fait déjà** (%s). *Une validation externe, pas une "
              "découverte.* **Intéressant n'est pas utile.**" % ", ".join(deja[:4]))
    else:
        pq = "Il ne touche **aucun** de nos concepts. *Hors sujet.*"
    return Delta(s, nouveaux, deja, pq)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# #15 — LES ZONES VIERGES. *Ce que PERSONNE ne fait.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
@dataclass(slots=True)
class ZonesVierges:
    jamais_vus: list[str]
    rares: list[tuple[str, int]]
    partout: list[tuple[str, int]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "jamais_vus_dans_le_corpus": self.jamais_vus,
            "rares": [{"concept": c, "n_repos": n} for c, n in self.rares],
            "partout": [{"concept": c, "n_repos": n} for c, n in self.partout],
            "pourquoi": (
                "🔑 **Un concept que PERSONNE n'implémente est soit inutile, soit INEXPLOITÉ.** "
                "*Les deux méritent d'être sus — et le second, c'est là que vit un edge.* "
                "Si 5 000 personnes ont essayé le market making et que zéro n'a publié un carry "
                "HL delta-neutre documenté, ce n'est peut-être pas parce que c'est bête : "
                "**c'est peut-être parce que personne n'a regardé.**"
            ),
        }


def zones_vierges(concepts_par_repo: Mapping[str, Sequence[str]],
                  *, tous_les_concepts: Sequence[str] | None = None,
                  seuil_rare: int = 3) -> ZonesVierges:
    """Le **contraire** du grep : *ce que personne ne fait.*"""
    compte: dict[str, int] = {}
    for cs in concepts_par_repo.values():
        for c in set(cs):
            compte[c] = compte.get(c, 0) + 1

    univers = list(tous_les_concepts or NOS_CAPACITES.keys())
    jamais = sorted(c for c in univers if compte.get(c, 0) == 0)
    rares = sorted(((c, n) for c, n in compte.items() if 0 < n <= seuil_rare),
                   key=lambda x: x[1])
    partout = sorted(compte.items(), key=lambda x: -x[1])[:8]
    return ZonesVierges(jamais, rares, partout)


__all__ = [
    "NOS_CAPACITES", "POIDS_CONNU", "POIDS_NOUVEAU",
    "Delta", "NotreEtat", "ZonesVierges",
    "indexer_notre_code", "score_differentiel", "zones_vierges",
]
