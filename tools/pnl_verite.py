"""VÉRITÉ DU PNL — ledger corrompu, validation économique, ROI explicite, MtM causal, drawdown (IDEA-36 → 40).

Suite directe de `ledger_verite`. Ici on protège les CHIFFRES eux-mêmes :

  • IDEA-36 : une ligne JSON invalide = `LEDGER_CORRUPTED` + localisation (ligne/offset) + promotion
    interdite. Jamais un `continue` silencieux qui ferait « disparaître » un trade du PnL ;
  • IDEA-37 : validation économique CENTRALE — notional<=0, prix<=0, side hors {-1,+1}, levier<=0, NaN,
    inf, fraction de reduce hors ]0,1] sont refusés AVANT toute écriture (state et ledger restent intacts) ;
  • IDEA-38 : trois ROI distincts et nommés (initial / pic de marge / marge moyenne). `capital_initial -
    final_cash` n'est JAMAIS un capital déployé ;
  • IDEA-39 : mark-to-market CAUSAL — on ne marque qu'avec un prix dont le timestamp est <= maintenant ;
    sans mark disponible, la position est `UNMEASURABLE`, jamais un latent zéro implicite ;
  • IDEA-40 : drawdown recalculé à CHAQUE mark (intraposition), pas seulement aux OPEN/CLOSE.

Calcul pur : 0 réseau, 0 ordre, paper-only.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

LEDGER_CORRUPTED = "LEDGER_CORRUPTED"
UNMEASURABLE = "UNMEASURABLE"
OK = "OK"

#: les trois ROI, jamais confondus (IDEA-38).
ROI_ON_INITIAL_CAPITAL = "ROI_ON_INITIAL_CAPITAL"
ROI_ON_PEAK_MARGIN = "ROI_ON_PEAK_MARGIN"
ROI_ON_AVG_MARGIN = "ROI_ON_AVG_MARGIN"


def _fini(x) -> bool:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return False
    return math.isfinite(v)


# ─────────────────────── IDEA-36 : ledger corrompu ───────────────────────
def scanner_ledger(chemin: Path) -> dict:
    """IDEA-36 — parcourt TOUT le ledger et rend la liste EXHAUSTIVE des lignes invalides (numéro + offset
    + extrait). Une seule ligne corrompue suffit à interdire la promotion : un PnL amputé silencieusement
    d'un trade est un PnL faux."""
    p = Path(chemin)
    if not p.exists():
        return {"statut": OK, "n_lignes": 0, "n_valides": 0, "erreurs": [], "promotion_autorisee": True}
    erreurs, n_ok, n = [], 0, 0
    offset = 0
    with p.open("r", encoding="utf-8", errors="ignore") as f:
        for i, ligne in enumerate(f, 1):
            n += 1
            brut = ligne.rstrip("\n")
            if brut.strip():
                try:
                    json.loads(brut)
                    n_ok += 1
                except ValueError as e:
                    erreurs.append({"ligne": i, "offset": offset, "extrait": brut[:80],
                                    "erreur": str(e)[:100]})
            offset += len(ligne.encode("utf-8"))
    return {"statut": (LEDGER_CORRUPTED if erreurs else OK), "n_lignes": n, "n_valides": n_ok,
            "erreurs": erreurs, "n_erreurs": len(erreurs),
            "promotion_autorisee": not erreurs}


# ─────────────────────── IDEA-37 : validation économique centrale ───────────────────────
def valider_operation(*, type_: str, notional=None, prix=None, side=None, levier=None,
                      fraction=None) -> dict:
    """IDEA-37 — porte d'entrée UNIQUE de toute opération. Rend {valide, motifs}. Tant que `valide` est
    faux, l'appelant ne doit RIEN écrire (ni state, ni ledger) : une opération invalide ne doit laisser
    aucune trace comptable."""
    motifs = []
    t = str(type_).upper()
    if t not in ("OPEN", "ADD", "REDUCE", "CLOSE", "FLIP"):
        motifs.append("TYPE_INCONNU:%s" % t)
    if notional is not None:
        if not _fini(notional) or float(notional) <= 0:
            motifs.append("NOTIONAL_INVALIDE")
    if prix is not None:
        if not _fini(prix) or float(prix) <= 0:
            motifs.append("PRIX_INVALIDE")
    if side is not None:
        try:
            if int(side) not in (-1, 1):
                motifs.append("SIDE_INVALIDE")
        except (TypeError, ValueError):
            motifs.append("SIDE_INVALIDE")
    if levier is not None:
        if not _fini(levier) or float(levier) <= 0:
            motifs.append("LEVIER_INVALIDE")
    if fraction is not None:
        if not _fini(fraction) or not (0 < float(fraction) <= 1):
            motifs.append("FRACTION_INVALIDE")
    if t in ("REDUCE",) and fraction is None:
        motifs.append("FRACTION_REQUISE_POUR_REDUCE")
    return {"valide": not motifs, "motifs": motifs, "type": t}


def appliquer_si_valide(etat: dict, operation: dict, appliquer) -> dict:
    """Applique `appliquer(etat)` UNIQUEMENT si l'opération est valide. Sinon l'état est rendu INCHANGÉ
    (copie défensive) avec le motif du refus : aucune opération invalide ne modifie state/ledger."""
    v = valider_operation(**operation)
    if not v["valide"]:
        return {"applique": False, "etat": dict(etat), "refus": v["motifs"]}
    return {"applique": True, "etat": appliquer(dict(etat)), "refus": []}


# ─────────────────────── IDEA-38 : ROI explicite ───────────────────────
def roi_explicite(*, pnl_realise: float, capital_initial: float, marge_pic: float | None = None,
                  marge_moyenne: float | None = None) -> dict:
    """IDEA-38 — trois ROI NOMMÉS. Un dénominateur absent donne None (le ROI correspondant n'est pas
    calculable), jamais un chiffre de remplacement. `capital_initial - final_cash` n'apparaît nulle part :
    ce n'est pas un capital déployé (il mélange marge, coûts et PnL)."""
    def _roi(num, den):
        if not _fini(den) or float(den) <= 0 or not _fini(num):
            return None
        return round(float(num) / float(den) * 100.0, 6)
    return {ROI_ON_INITIAL_CAPITAL: _roi(pnl_realise, capital_initial),
            ROI_ON_PEAK_MARGIN: _roi(pnl_realise, marge_pic),
            ROI_ON_AVG_MARGIN: _roi(pnl_realise, marge_moyenne),
            "pnl_realise": (round(float(pnl_realise), 6) if _fini(pnl_realise) else None),
            "denominateurs": {"capital_initial": capital_initial, "marge_pic": marge_pic,
                              "marge_moyenne": marge_moyenne},
            "avertissement": "capital_initial - final_cash n'est PAS un capital deploye"}


# ─────────────────────── IDEA-39/40 : mark-to-market causal + drawdown intraposition ───────────────────────
def mark_causal(marks, *, maintenant_ms: float):
    """IDEA-39 — dernier mark dont le timestamp est <= maintenant. Rend (prix, ts) ou (None, None) :
    un mark futur ne peut JAMAIS servir à valoriser le présent."""
    passe = [(float(m["ts_ms"]), float(m["px"])) for m in (marks or [])
             if _fini(m.get("ts_ms")) and _fini(m.get("px")) and float(m["ts_ms"]) <= float(maintenant_ms)]
    if not passe:
        return None, None
    ts, px = max(passe)
    return px, ts


def valoriser(position: dict, marks, *, maintenant_ms: float) -> dict:
    """IDEA-39 — valorise UNE position au dernier mark causal. Sans mark disponible : statut UNMEASURABLE
    et `pnl_latent=None` (surtout pas 0, qui ferait croire à une position neutre)."""
    px, ts = mark_causal(marks, maintenant_ms=maintenant_ms)
    entry = float(position.get("entry_px") or 0.0)
    notional = float(position.get("notional") or 0.0)
    sens = 1 if int(position.get("sens", 1)) >= 0 else -1
    if px is None or entry <= 0:
        return {"statut": UNMEASURABLE, "pnl_latent": None, "mark_px": None, "mark_ts_ms": None,
                "motif": "aucun mark causal disponible (<= maintenant)"}
    latent = sens * (px - entry) / entry * notional
    return {"statut": OK, "pnl_latent": round(latent, 6), "mark_px": px, "mark_ts_ms": ts}


class SuiviDrawdown:
    """IDEA-40 — drawdown recalculé à CHAQUE mark. Un pic atteint puis perdu ENTRE deux trades est capté ;
    un drawdown calculé seulement aux OPEN/CLOSE sous-estime systématiquement le risque réel."""

    def __init__(self, equity_initiale: float):
        self.pic = float(equity_initiale)
        self.dd_max = 0.0
        self.n_marks = 0
        self.historique = []

    def marquer(self, equity: float, *, ts_ms: float | None = None) -> dict:
        e = float(equity)
        self.n_marks += 1
        self.pic = max(self.pic, e)
        dd = self.pic - e
        self.dd_max = max(self.dd_max, dd)
        point = {"ts_ms": ts_ms, "equity": round(e, 6), "pic": round(self.pic, 6),
                 "drawdown": round(dd, 6), "drawdown_max": round(self.dd_max, 6)}
        self.historique.append(point)
        return point

    def resume(self) -> dict:
        return {"n_marks": self.n_marks, "pic_equity": round(self.pic, 6),
                "drawdown_max": round(self.dd_max, 6),
                "intraposition": self.n_marks > 0}


__all__ = ["LEDGER_CORRUPTED", "UNMEASURABLE", "OK", "ROI_ON_INITIAL_CAPITAL", "ROI_ON_PEAK_MARGIN",
           "ROI_ON_AVG_MARGIN", "scanner_ledger", "valider_operation", "appliquer_si_valide",
           "roi_explicite", "mark_causal", "valoriser", "SuiviDrawdown"]
