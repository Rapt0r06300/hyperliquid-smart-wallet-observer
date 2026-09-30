"""#583 (`position_stacking`) + #325 (baseline IMMUABLE) — **le backtest ment-il ?**

═══════════════════════════════════════════════════════════════════════════════════════════════
#583 — `position_stacking` : LE BACKTEST EMPILE-T-IL CE QUE LE LIVE REFUSE ?
═══════════════════════════════════════════════════════════════════════════════════════════════

En backtest, rien n'empêche d'ouvrir **10 positions sur BTC** parce que le signal s'est répété
10 fois. En live, le RiskEngine en refuse 9 (cap par coin, cap d'exposition nette, marge).

    ***Un backtest qui empile ce que le live refuse ne mesure pas la même stratégie.***
    Il mesure une stratégie **plus grosse, plus concentrée, plus risquée** — et il l'appelle
    « notre stratégie ».

C'est exactement la famille de bugs de ce projet : *une contrainte présente d'un côté, absente de
l'autre, et personne qui se plaint.* On a déjà eu **deux tables d'edge** et **la coupe train/test
qui fuyait**.

Le module **applique au backtest EXACTEMENT les mêmes limites que le live** et **COMPTE ce que ça
refuse**. Si le compte est élevé, le backtest était un mensonge.

═══════════════════════════════════════════════════════════════════════════════════════════════
#325 — LA BASELINE IMMUABLE
═══════════════════════════════════════════════════════════════════════════════════════════════

    ***On ne peut pas mesurer une amélioration sans un point de départ FIGÉ.***

Sans baseline scellée, chaque « amélioration » se compare à un passé qui a bougé — et on finit
par croire qu'on progresse. La baseline porte une **empreinte** : si les données ou la config
changent, **elle le crie** au lieu de se laisser comparer en silence.

PUR : aucun appel réseau. Aucun ordre réel.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

# Les MÊMES limites que le live. Si elles divergent, le backtest ment.
MAX_POSITIONS_PAR_COIN = 1
MAX_POSITIONS_TOTAL = 5
MAX_EXPOSITION_NETTE = 1.0        # 100 % du capital
MAX_PART_PAR_COIN = 0.60          # 60 % max sur un seul coin

MOTIF_DEJA_UNE_POSITION = "DEJA_UNE_POSITION_SUR_CE_COIN_LE_LIVE_REFUSERAIT"
MOTIF_TROP_DE_POSITIONS = "TROP_DE_POSITIONS_OUVERTES"
MOTIF_EXPOSITION = "EXPOSITION_NETTE_DEPASSEE"
MOTIF_CONCENTRATION = "TROP_CONCENTRE_SUR_UN_COIN"
MOTIF_OK = "ACCEPTE"

MOTIF_BASELINE_CHANGEE = "LA_BASELINE_A_CHANGE_TOUTE_COMPARAISON_EST_INVALIDE"


@dataclass(slots=True)
class CompteurRefus:
    """🔴 **Ce que le live aurait refusé, et que le backtest prenait quand même.**"""
    acceptes: int = 0
    refus_deja_une_position: int = 0
    refus_trop_de_positions: int = 0
    refus_exposition: int = 0
    refus_concentration: int = 0

    @property
    def refuses(self) -> int:
        return (self.refus_deja_une_position + self.refus_trop_de_positions
                + self.refus_exposition + self.refus_concentration)

    @property
    def part_empilee(self) -> float:
        """La fraction des trades du backtest que le LIVE n'aurait **jamais** pris."""
        t = self.acceptes + self.refuses
        return (self.refuses / t) if t else 0.0

    def as_dict(self) -> dict[str, Any]:
        p = self.part_empilee
        return {
            "acceptes": self.acceptes, "refuses": self.refuses,
            "refus_deja_une_position": self.refus_deja_une_position,
            "refus_trop_de_positions": self.refus_trop_de_positions,
            "refus_exposition": self.refus_exposition,
            "refus_concentration": self.refus_concentration,
            "part_empilee": round(p, 4),
            "verdict": (
                "🔴 **LE BACKTEST MENTAIT** : %.0f %% de ses trades n'auraient JAMAIS existe en "
                "live. Il mesurait une strategie **plus grosse et plus concentree** que la notre."
                % (p * 100) if p > 0.10 else
                "Backtest et live prennent essentiellement les memes trades (%.1f %% d'ecart)."
                % (p * 100)
            ),
            "real_execution": False,
        }


@dataclass(frozen=True, slots=True)
class Position:
    coin: str
    notionnel: float
    long: bool


def le_live_accepterait(
    coin: str,
    notionnel: float,
    *,
    long: bool,
    positions_ouvertes: Sequence[Position],
    capital: float,
    max_par_coin: int = MAX_POSITIONS_PAR_COIN,
    max_total: int = MAX_POSITIONS_TOTAL,
    max_exposition: float = MAX_EXPOSITION_NETTE,
    max_part_coin: float = MAX_PART_PAR_COIN,
) -> tuple[bool, str]:
    """***Les MÊMES limites que le live. Aucune indulgence pour le backtest.***"""
    if capital <= 0:
        return False, "capital nul : rien ne peut etre ouvert"

    sur_ce_coin = [p for p in positions_ouvertes if p.coin == coin]
    if len(sur_ce_coin) >= max_par_coin:
        return False, MOTIF_DEJA_UNE_POSITION

    if len(positions_ouvertes) >= max_total:
        return False, MOTIF_TROP_DE_POSITIONS

    # 🔴 exposition NETTE (le gate historique ne voyait que le BRUT)
    net = sum((p.notionnel if p.long else -p.notionnel) for p in positions_ouvertes)
    net_futur = net + (notionnel if long else -notionnel)
    if abs(net_futur) / capital > max_exposition:
        return False, MOTIF_EXPOSITION

    # 🔴 BUG TROUVE PAR UN TEST ROUGE (2026-07-14) : je mesurais la concentration contre le LIVRE
    # COURANT (`brut_futur`), pas contre le CAPITAL. Consequence : la **toute premiere** position
    # est 100 % du livre -> **TOUJOURS refusee**. Le bot n'aurait jamais ouvert un seul trade.
    # *Un garde-fou qui refuse TOUT n'est pas prudent : il est CASSE.*
    # (On a deja eu 3 verrous MORTS qui garantissaient 0 trade par arithmetique.)
    part = (sum(p.notionnel for p in sur_ce_coin) + notionnel) / capital
    if part > max_part_coin:
        return False, MOTIF_CONCENTRATION

    return True, MOTIF_OK


def rejouer_sans_empilement(
    signaux: Iterable[tuple[str, float, bool]],   # (coin, notionnel, long)
    *,
    capital: float,
) -> CompteurRefus:
    """Rejoue les signaux du backtest **avec les limites du LIVE**, et compte ce qui saute.

    ⚠️ Ce module ne ferme jamais de position (il ne connaît pas les sorties) : il mesure donc une
    **BORNE HAUTE** de l'empilement. **On le dit** plutôt que de faire croire à une simulation
    complète.
    """
    c = CompteurRefus()
    ouvertes: list[Position] = []
    for coin, notionnel, long in signaux:
        ok, motif = le_live_accepterait(coin, notionnel, long=long,
                                        positions_ouvertes=ouvertes, capital=capital)
        if ok:
            c.acceptes += 1
            ouvertes.append(Position(coin, notionnel, long))
            continue
        if motif == MOTIF_DEJA_UNE_POSITION:
            c.refus_deja_une_position += 1
        elif motif == MOTIF_TROP_DE_POSITIONS:
            c.refus_trop_de_positions += 1
        elif motif == MOTIF_EXPOSITION:
            c.refus_exposition += 1
        elif motif == MOTIF_CONCENTRATION:
            c.refus_concentration += 1
    return c


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# #325 — LA BASELINE IMMUABLE
# ═══════════════════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class Baseline:
    """***On ne peut pas mesurer une amélioration sans un point de départ FIGÉ.***"""
    empreinte: str
    metriques: Mapping[str, float] = field(default_factory=dict)
    scellee_le: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"empreinte": self.empreinte, "metriques": dict(self.metriques),
                "scellee_le": self.scellee_le, "real_execution": False}


def empreinte(donnees: Any, config: Mapping[str, Any]) -> str:
    """L'empreinte des DONNÉES et de la CONFIG. Si l'une bouge, la comparaison est invalide."""
    payload = json.dumps({"donnees": donnees, "config": dict(config)},
                         sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def sceller(donnees: Any, config: Mapping[str, Any], metriques: Mapping[str, float],
            *, le: str) -> Baseline:
    return Baseline(empreinte=empreinte(donnees, config),
                    metriques=dict(metriques), scellee_le=le)


def comparer(baseline: Baseline, donnees: Any, config: Mapping[str, Any],
             metriques: Mapping[str, float]) -> dict[str, Any]:
    """🔴 **Si les données ou la config ont changé, la baseline CRIE** au lieu de se laisser
    comparer en silence.

    *Sans ça, chaque « amélioration » se compare à un passé qui a bougé — et on finit par croire
    qu'on progresse.*
    """
    e = empreinte(donnees, config)
    if e != baseline.empreinte:
        return {
            "valide": False, "motif": MOTIF_BASELINE_CHANGEE,
            "detail": ("empreinte %s != %s. **Les donnees ou la config ont CHANGE.** Toute "
                       "comparaison avec cette baseline est INVALIDE -- on ne compare pas une "
                       "strategie a un passe qui a bouge." % (e, baseline.empreinte)),
            "real_execution": False,
        }
    deltas = {k: round(float(metriques.get(k, 0.0)) - float(v), 6)
              for k, v in baseline.metriques.items()}
    return {"valide": True, "deltas": deltas, "empreinte": e, "real_execution": False}


__all__ = [
    "MAX_EXPOSITION_NETTE", "MAX_PART_PAR_COIN", "MAX_POSITIONS_PAR_COIN", "MAX_POSITIONS_TOTAL",
    "MOTIF_BASELINE_CHANGEE", "MOTIF_CONCENTRATION", "MOTIF_DEJA_UNE_POSITION",
    "MOTIF_EXPOSITION", "MOTIF_OK", "MOTIF_TROP_DE_POSITIONS",
    "Baseline", "CompteurRefus", "Position",
    "comparer", "empreinte", "le_live_accepterait", "rejouer_sans_empilement", "sceller",
]
