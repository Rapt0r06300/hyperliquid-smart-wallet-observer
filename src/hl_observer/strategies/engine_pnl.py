"""DEUX MOTEURS, DEUX PnL — attribution séparée depuis le ledger (2026-07-11).

POURQUOI CE MODULE EXISTE (pistes 12 à 20 du brief).

`strategy_mode.py` étiquette chaque décision. Mais tant que le PnL reste **un seul chiffre**, les
deux moteurs restent confondus dans la seule mesure qui compte. Or ils n'ont RIEN en commun :

  * le GRINDER fait beaucoup d'opérations à petit objectif : il meurt des **frais**. Un coût de
    13 bps sur un objectif de 30 bps mange 43 % de la cible avant même de savoir si on a raison.
  * le SNIPER fait peu d'opérations sur un signal rare : il meurt de la **fraîcheur**. Un signal
    vieux de 60 s n'a plus d'edge, quels que soient les frais.

Additionner leurs PnL, c'est mélanger deux maladies et n'en soigner aucune. Pire : un moteur qui
gagne peut **masquer** un moteur qui saigne. C'est exactement ce qui s'est passé — sauf qu'ici le
Grinder ne tradait pas du tout, ce que personne n'avait vu.

CE QUE CE MODULE FAIT — et rien de plus :
  * il relit le ledger et rend, PAR MOTEUR : PnL net, PnL brut, frais, funding, nombre de trades,
    winrate, profit factor, courbe d'équité.
  * il attribue à `UNKNOWN_LEGACY` tout ce qu'il ne sait pas classer. **Jamais de devinette.**
  * il ne juge pas, il ne décide pas, il n'ouvre rien. Fonction PURE, sans I/O, sans réseau.

RÈGLE DURE : un moteur sans trade rend un bilan VIDE et HONNÊTE (zéro trade, PnL 0), jamais une
absence silencieuse. « Le Grinder n'apparaît pas dans le rapport » et « le Grinder n'a rien fait »
doivent être deux affirmations impossibles à confondre.

Aucun ordre réel. Lecture seule.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from hl_observer.strategies.strategy_mode import (
    GRINDER,
    SNIPER,
    UNKNOWN_LEGACY,
    classify_event,
)

TOUS_LES_MOTEURS = (GRINDER, SNIPER, UNKNOWN_LEGACY)

# Le funding-arb n'ecrit pas des OPEN/CLOSE mais des FUNDING_ARB_*. Un rapport qui ne
# connait que OPEN/CLOSE est AVEUGLE au Grinder -- l'erreur a deja ete commise une fois.
_ACTIONS_CLOTURE = ("CLOSE", "FUNDING_ARB_CLOSE", "FUNDING_ARB_ACCRUAL")


def _cle_position(event: Mapping[str, Any]) -> str:
    """Identifiant de la position portee par un evenement (entree comme sortie)."""
    cle = str(event.get("matched_position_key") or "").strip()
    if cle:
        return cle
    wallet = str(event.get("wallet_address") or "").strip()
    coin = str(event.get("coin") or "").strip()
    side = str(event.get("leader_side") or "").strip()
    return f"{wallet}|{coin}|{side}" if (wallet and coin and side) else ""


def _f(value: Any, defaut: float = 0.0) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return defaut
    return x if math.isfinite(x) else defaut


@dataclass(slots=True)
class BilanMoteur:
    """Le bilan d'UN moteur. Vide et honnête si le moteur n'a rien fait."""

    moteur: str
    trades: int = 0
    gagnants: int = 0
    perdants: int = 0
    pnl_net_usdc: float = 0.0
    pnl_brut_usdc: float = 0.0
    frais_usdc: float = 0.0
    funding_usdc: float = 0.0
    gains_usdc: float = 0.0            # somme des trades gagnants (pour le profit factor)
    pertes_usdc: float = 0.0           # somme |trades perdants|
    courbe_equity: list[float] = field(default_factory=list)

    @property
    def winrate(self) -> float | None:
        """None si aucun trade : on ne rend pas « 0 % » là où il n'y a RIEN à mesurer."""
        return (self.gagnants / self.trades) if self.trades else None

    @property
    def profit_factor(self) -> float | None:
        """Le juge de paix (cf. CLAUDE.md : juger au profit factor, pas au winrate brut).

        None = non mesurable (aucune perte, ou aucun trade). Un PF « infini » sur 1 trade
        gagnant serait un mensonge statistique : on rend None.
        """
        if not self.trades or self.pertes_usdc <= 0.0:
            return None
        return self.gains_usdc / self.pertes_usdc

    @property
    def frais_en_part_du_brut(self) -> float | None:
        """Le diagnostic du GRINDER : quelle fraction du brut les frais dévorent-ils ?

        > 1 signifie que les frais mangent tout le mouvement : la stratégie ne peut pas gagner,
        quelle que soit la qualité du signal.
        """
        if abs(self.pnl_brut_usdc) < 1e-9:
            return None
        return self.frais_usdc / abs(self.pnl_brut_usdc)

    def as_dict(self) -> dict[str, Any]:
        return {
            "moteur": self.moteur,
            "trades": self.trades,
            "gagnants": self.gagnants,
            "perdants": self.perdants,
            "pnl_net_usdc": round(self.pnl_net_usdc, 6),
            "pnl_brut_usdc": round(self.pnl_brut_usdc, 6),
            "frais_usdc": round(self.frais_usdc, 6),
            "funding_usdc": round(self.funding_usdc, 6),
            "winrate": (round(self.winrate, 4) if self.winrate is not None else None),
            "profit_factor": (round(self.profit_factor, 4)
                              if self.profit_factor is not None else None),
            "frais_en_part_du_brut": (round(self.frais_en_part_du_brut, 4)
                                      if self.frais_en_part_du_brut is not None else None),
            "courbe_equity": [round(x, 6) for x in self.courbe_equity],
        }


def attribuer_pnl_par_moteur(
    ledger_events: Iterable[Mapping[str, Any]] | None,
) -> dict[str, BilanMoteur]:
    """Rend UN bilan par moteur. Les trois moteurs sont TOUJOURS présents, même à zéro.

    Un moteur absent du rapport et un moteur qui n'a rien fait ne doivent jamais se confondre :
    c'est précisément la confusion qui a laissé le Grinder éteint sans que personne le voie.
    """
    bilans: dict[str, BilanMoteur] = {m: BilanMoteur(moteur=m) for m in TOUS_LES_MOTEURS}
    if not ledger_events:
        return bilans

    events = [e for e in ledger_events if isinstance(e, Mapping)]

    # PREMIERE PASSE -- le moteur de chaque POSITION, lu sur son evenement d'ENTREE.
    #
    # Une cloture SL/TP ne porte, a elle seule, aucune trace du moteur : elle ne connait ni le
    # leader, ni la strategie, seulement "SLTP_STOP_LOSS". La classer sur son propre texte
    # renverrait UNKNOWN pour TOUT le ledger existant -- honnete, mais inutilisable.
    #
    # On applique donc au ledger la meme regle qu'en live : LA SORTIE HERITE DE L'ENTREE.
    # Ce n'est pas une devinette : le moteur vient de l'evenement d'ouverture REEL de CETTE
    # position. Si l'entree est introuvable, on reste sur UNKNOWN_LEGACY -- on n'invente rien.
    moteur_par_position: dict[str, str] = {}
    for event in events:
        action = str(event.get("paper_action_type") or "").upper()
        if action not in {"OPEN", "INCREASE"}:
            continue
        cle = _cle_position(event)
        if not cle or cle in moteur_par_position:
            continue          # une position renforcee GARDE le moteur de sa premiere entree
        moteur_par_position[cle] = classify_event(event)

    cumul: dict[str, float] = {m: 0.0 for m in TOUS_LES_MOTEURS}

    for event in events:
        action = str(event.get("paper_action_type") or "").upper()
        if action not in _ACTIONS_CLOTURE:
            continue          # seule une CLOTURE realise un PnL ; une entree n'en realise aucun

        # 1) un mode DEJA POSE fait foi (live, apres le correctif "strategy_mode a la source") ;
        # 2) sinon, on herite du moteur de l'ENTREE de cette position (ledger historique) ;
        # 3) sinon seulement : UNKNOWN_LEGACY.
        pose = str(event.get("strategy_mode") or "").upper()
        if pose in bilans:
            moteur = pose
        else:
            moteur = moteur_par_position.get(_cle_position(event) or "", "")
            if moteur not in bilans:
                moteur = classify_event(event)
        if moteur not in bilans:
            moteur = UNKNOWN_LEGACY
        b = bilans[moteur]

        net = _f(event.get("estimated_net_pnl_usdc"))
        brut = _f(event.get("gross_pnl_usdc"), net)
        # frais de SORTIE uniquement : le cout d'ENTREE est deja dans le prix d'entree
        # (fill_price_includes_spread_slippage_fee_latency). Le compter ici serait le doubler.
        frais = _f(event.get("fee_cost_usdc"))
        funding = _f(event.get("funding_cost_usdc"))

        b.trades += 1
        b.pnl_net_usdc += net
        b.pnl_brut_usdc += brut
        b.frais_usdc += frais
        b.funding_usdc += funding
        if net > 0:
            b.gagnants += 1
            b.gains_usdc += net
        elif net < 0:
            b.perdants += 1
            b.pertes_usdc += -net

        cumul[moteur] += net
        b.courbe_equity.append(cumul[moteur])

    return bilans


def rapport_par_moteur(ledger_events: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    """Rapport sérialisable, prêt pour le dashboard, l'audit ou un export."""
    bilans = attribuer_pnl_par_moteur(ledger_events)
    total_net = sum(b.pnl_net_usdc for b in bilans.values())
    return {
        "moteurs": {m: b.as_dict() for m, b in bilans.items()},
        "pnl_net_total_usdc": round(total_net, 6),
        "trades_total": sum(b.trades for b in bilans.values()),
        # Un moteur a zero trade n'est PAS un moteur sans probleme : c'est un moteur ETEINT,
        # ou dont un verrou est mort. On le dit, au lieu de le laisser passer en silence.
        "moteurs_inactifs": sorted(m for m, b in bilans.items()
                                   if b.trades == 0 and m != UNKNOWN_LEGACY),
        "paper_only": True,
        "real_execution": False,
    }


__all__ = [
    "TOUS_LES_MOTEURS",
    "BilanMoteur",
    "attribuer_pnl_par_moteur",
    "rapport_par_moteur",
]
