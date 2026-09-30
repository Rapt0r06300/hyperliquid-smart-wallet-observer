"""LE PIPELINE ANTI-LOOKAHEAD — un seul point d'entrée qui compose ce qui existait déjà.

La « maladie du projet » : les garde-fous anti-triche du backtest existent tous, mais **éparpillés**
et jamais appelés ensemble. Un backtest honnête doit répondre à TROIS questions, et il n'y avait pas
d'endroit unique pour les poser :

1. **Le signal LIT-il le futur ?** (statique) → `testing/lookahead_detector.analyser_source` (AST).
2. **La coupe train/test FUIT-elle ?** (données) → `backtesting/purged_split.purged_temporal_split`
   (purge des trades qui débordent + embargo autour de la frontière).
3. **L'edge SURVIT-il à la déflation ?** (sur-apprentissage) → `backtesting/anti_overfit_gate.evaluer`
   (Sharpe déflaté par le nombre d'essais — le « meilleur de 150 000 000 tirages de bruit » meurt ici).

Ce module ne réécrit AUCUNE de ces logiques : il les BRANCHE. Deny-by-default — le moindre échec
sur l'une des trois questions → `accepte = False`. C'est la porte que #17 (re-tester les idées
enterrées) doit franchir : une idée ne « revit » que si elle passe les trois.

Module PUR. Une vérification n'est pas un ordre.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from hl_observer.backtesting.anti_overfit_gate import PROBA_MIN, evaluer
from hl_observer.backtesting.purged_split import purged_temporal_split
from hl_observer.testing.lookahead_detector import analyser_source

MOTIF_OK = "BACKTEST_HONNETE"
MOTIF_AST_SALE = "LE_SIGNAL_LIT_LE_FUTUR_AST"
MOTIF_COUPE_INVALIDE = "COUPE_TRAIN_TEST_VIDE_APRES_PURGE"
MOTIF_OVERFIT = "EDGE_NE_SURVIT_PAS_A_LA_DEFLATION"


@dataclass(frozen=True, slots=True)
class VerdictPipeline:
    accepte: bool
    ast_verifie: bool
    ast_propre: bool
    n_suspicions: int
    coupe_valide: bool
    n_purges: int
    n_embargo: int
    overfit_survit: bool
    proba_deflatee: float
    motifs: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepte": self.accepte,
            "ast_verifie": self.ast_verifie,
            "ast_propre": self.ast_propre,
            "n_suspicions": self.n_suspicions,
            "coupe_valide": self.coupe_valide,
            "n_purges": self.n_purges,
            "n_embargo": self.n_embargo,
            "overfit_survit": self.overfit_survit,
            "proba_deflatee": round(self.proba_deflatee, 6),
            "motifs": list(self.motifs),
            "note": (
                "Trois questions, une porte : le signal lit-il le futur (AST) ? la coupe "
                "train/test fuit-elle (purge+embargo) ? l'edge survit-il à la déflation (PBO) ? "
                "Deny-by-default : un seul non → refus."
            ),
            "real_execution": False,
        }


def verifier_backtest(
    *,
    candidats: Sequence[Mapping[str, Any]],
    horizon_min: float,
    pnls_test: Sequence[float],
    n_essais: int,
    source_du_signal: str | None = None,
    train_frac: float = 0.7,
    embargo_min: float | None = None,
    proba_min: float = PROBA_MIN,
) -> VerdictPipeline:
    """Fait passer un backtest par les trois portes. `accepte=True` seulement si TOUTES passent.

    - `candidats` : les candidats horodatés (`recorded_at`) pour la coupe purgée.
    - `horizon_min` : le PIRE horizon de la grille (durée max qu'un trade reste ouvert).
    - `pnls_test` : les PnL mesurés SUR LE TEST (jamais le train).
    - `n_essais` : combien de configs ont été essayées avant de choisir celle-ci (déflation).
    - `source_du_signal` : le code source de la fonction de signal (analyse AST). `None` → non vérifié.
    """
    motifs: list[str] = []

    # ── Porte 1 : le signal lit-il le futur ? (statique, AST) ────────────────────────────────
    ast_verifie = source_du_signal is not None
    n_susp = 0
    ast_propre = True
    if ast_verifie:
        susp = analyser_source(source_du_signal or "")
        n_susp = len(susp)
        ast_propre = n_susp == 0
        if not ast_propre:
            motifs.append(MOTIF_AST_SALE)

    # ── Porte 2 : la coupe train/test fuit-elle ? (purge + embargo) ──────────────────────────
    coupe = purged_temporal_split(
        candidats, train_frac=train_frac, horizon_min=horizon_min, embargo_min=embargo_min
    )
    if not coupe.valide:
        motifs.append(MOTIF_COUPE_INVALIDE)

    # ── Porte 3 : l'edge survit-il à la déflation ? (PBO / Sharpe déflaté) ────────────────────
    v = evaluer(pnls_test, n_essais=n_essais, proba_min=proba_min)
    if not v.survit:
        motifs.append(MOTIF_OVERFIT)

    accepte = ast_propre and coupe.valide and v.survit
    if accepte:
        motifs.append(MOTIF_OK)

    return VerdictPipeline(
        accepte=accepte,
        ast_verifie=ast_verifie,
        ast_propre=ast_propre,
        n_suspicions=n_susp,
        coupe_valide=coupe.valide,
        n_purges=coupe.n_purges,
        n_embargo=coupe.n_embargo,
        overfit_survit=v.survit,
        proba_deflatee=v.proba_deflatee,
        motifs=tuple(motifs),
    )


__all__ = [
    "MOTIF_AST_SALE", "MOTIF_COUPE_INVALIDE", "MOTIF_OK", "MOTIF_OVERFIT",
    "VerdictPipeline", "verifier_backtest",
]
