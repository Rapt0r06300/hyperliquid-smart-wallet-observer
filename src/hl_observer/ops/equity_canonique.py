"""§4.5 — équity canonique : UNE seule courbe, et l'interdiction du double comptage (lecture seule, 0 réseau).

    liquidatable_equity = capital_initial + realized_pnl + unrealized_liquidatable_pnl − fees − slippage_modelise

Trois pièges que ce module refuse par construction :

1. **Double comptage spread/slippage/VWAP.** Le spread traversé est DÉJÀ dans le prix exécutable (ask→bid).
   Le rajouter en coût le compte deux fois. Chaque composante de coût porte `included_in_price` : si c'est
   vrai, elle ne se soustrait PAS de l'équity, elle est seulement rapportée.
2. **Le mid pris pour du liquidable.** L'unrealized au mid est informatif ; seul l'unrealized au prix de
   SORTIE exécutable (bid pour un long, ask pour un short) entre dans l'équity liquidable.
3. **Une composante inconnue traitée comme 0.** Frais absents ⇒ `fees=None` propagé, et l'équity est marquée
   `PARTIELLE` : on ne prétend pas connaître un net qu'on n'a pas.

Le module publie AUSSI les grandeurs de capital séparément (marge bloquée, exposition brute/nette, pic de
marge, collatéral libre) : un ROI n'a de sens qu'avec son dénominateur nommé.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "hypersmart.equity_canonique.v1"

#: Composantes de coût connues. `included_in_price=True` ⇒ déjà dans le prix, ne pas re-soustraire.
COMPOSANTES_COUT = ("exchange_fee", "spread", "l2_slippage", "latency_adverse_selection",
                    "second_leg_slippage", "queue_opportunity_cost", "liquidation_margin_cost")


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


@dataclass
class Cout:
    """Une composante de coût. `included_in_price` empêche le double comptage."""

    nom: str
    montant_usd: float | None
    included_in_price: bool = False

    def deductible(self) -> float | None:
        """Montant réellement soustrait de l'équity. `None` si non mesuré ; 0 si déjà dans le prix."""
        if self.included_in_price:
            return 0.0
        return self.montant_usd


@dataclass
class EquityCanonique:
    """Une position paper reconstruite, avec sa décomposition d'équity."""

    capital_initial_usd: float
    realized_pnl_usd: float = 0.0
    unrealized_liquidatable_pnl_usd: float | None = None   # prix de SORTIE exécutable, jamais le mid
    unrealized_mid_pnl_usd: float | None = None            # informatif seulement
    couts: list[Cout] = field(default_factory=list)
    margin_locked_usd: float | None = None
    gross_exposure_usd: float | None = None
    net_exposure_usd: float | None = None
    venue_exposure_usd: Mapping[str, float] | None = None
    peak_margin_usd: float | None = None
    free_collateral_usd: float | None = None

    def couts_deduits(self) -> tuple[float, bool]:
        """Somme des coûts déductibles, et si un coût mesurable manque (⇒ équity partielle)."""
        total = 0.0
        partiel = False
        for c in self.couts:
            d = c.deductible()
            if d is None:
                partiel = True            # coût existant mais non mesuré : le net sera incomplet
            else:
                total += d
        return total, partiel

    def liquidatable_equity(self) -> dict[str, Any]:
        """La courbe canonique unique. `statut=PARTIELLE` si une brique manque — jamais un faux net."""
        couts, partiel_couts = self.couts_deduits()
        partiel = partiel_couts
        unreal = self.unrealized_liquidatable_pnl_usd
        if unreal is None:
            partiel = True                # position ouverte non liquidable au prix executable
            unreal_effectif = 0.0
        else:
            unreal_effectif = unreal
        equity = self.capital_initial_usd + self.realized_pnl_usd + unreal_effectif - couts
        return {
            "schema_version": SCHEMA_VERSION,
            "liquidatable_equity_usd": round(equity, 6),
            "statut": "PARTIELLE" if partiel else "COMPLETE",
            "capital_initial_usd": round(self.capital_initial_usd, 6),
            "realized_pnl_usd": round(self.realized_pnl_usd, 6),
            "unrealized_liquidatable_pnl_usd": (None if unreal is None else round(unreal, 6)),
            "unrealized_mid_pnl_usd": (None if self.unrealized_mid_pnl_usd is None
                                       else round(self.unrealized_mid_pnl_usd, 6)),
            "couts_deduits_usd": round(couts, 6),
            "couts_detail": [{"nom": c.nom, "montant_usd": c.montant_usd,
                              "included_in_price": c.included_in_price,
                              "deduit_usd": c.deductible()} for c in self.couts],
            # capital publie separement : un ROI exige son denominateur nomme
            "margin_locked_usd": _arrondi(self.margin_locked_usd),
            "gross_exposure_usd": _arrondi(self.gross_exposure_usd),
            "net_exposure_usd": _arrondi(self.net_exposure_usd),
            "venue_exposure_usd": (dict(self.venue_exposure_usd) if self.venue_exposure_usd else None),
            "peak_margin_usd": _arrondi(self.peak_margin_usd),
            "free_collateral_usd": _arrondi(self.free_collateral_usd),
            "note_partielle": (None if not partiel else
                               "une brique manque (cout non mesure ou position non liquidable) : "
                               "l'equity affichee est INCOMPLETE, pas un net reel"),
            "real_execution": False,
        }


def _arrondi(v: float | None) -> float | None:
    return None if v is None else round(float(v), 6)


def depuis_ledger_lignes(lignes: Sequence[Mapping[str, Any]], *, capital_initial_usd: float) -> EquityCanonique:
    """Construit une équity à partir de lignes de ledger : realized des CLOSE, coûts sommés, spread
    marqué `included_in_price` par défaut (il est dans le prix exécutable)."""
    realized = 0.0
    fees = 0.0
    fees_vus = False
    for ligne in lignes:
        kind = str(ligne.get("evt") or ligne.get("kind") or ligne.get("type") or "").upper()
        pnl = _num(ligne.get("realized_net_pnl_usdc") if "realized_net_pnl_usdc" in ligne
                   else ligne.get("realized_pnl_usd"))
        if kind in {"CLOSE", "REDUCE", "EXIT"} and pnl is not None:
            realized += pnl
        f = _num(ligne.get("frais_usd") or ligne.get("fee_usd"))
        if f is not None:
            fees += f
            fees_vus = True
    couts = [Cout("exchange_fee", fees if fees_vus else None, included_in_price=False),
             Cout("spread", None, included_in_price=True)]     # spread deja dans le prix executable
    return EquityCanonique(capital_initial_usd=capital_initial_usd, realized_pnl_usd=realized, couts=couts)


__all__ = ["SCHEMA_VERSION", "COMPOSANTES_COUT", "Cout", "EquityCanonique", "depuis_ledger_lignes"]
