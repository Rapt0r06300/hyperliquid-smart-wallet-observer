"""LA PROFONDEUR DU CARNET — *le prix AFFICHE n'est pas le prix qu'on OBTIENT.*

═══════════════════════════════════════════════════════════════════════════════════════════════
POURQUOI CE MODULE EXISTE
═══════════════════════════════════════════════════════════════════════════════════════════════

Le bot ouvre 3 carrys : PURR (+11,31 %) · PUMP (+5,23 %) · HYPE (+4,48 %), **au net des frais**.

Mais ces APR supposent qu'on achete le spot **au prix affiche**.

    ***Ce sont de PETITS marches. Leur funding est eleve PRECISEMENT parce que les detenir est
    dangereux et que peu de gens veulent le faire.*** Le funding EST le prix de ce risque.

Si le carnet est mince, le **slippage** mange l'edge -- et il le mange **QUATRE fois** :
spot achat + spot vente + perp vente + perp achat. *Un carry a 4,48 % d'APR ne survit pas a
50 bps de slippage aller-retour.*

═══════════════════════════════════════════════════════════════════════════════════════════════
LA REGLE DURE
═══════════════════════════════════════════════════════════════════════════════════════════════

  🔒 **ON MARCHE DANS LE CARNET, NIVEAU PAR NIVEAU.** On ne prend jamais le meilleur prix et
     on ne suppose jamais qu'il tient pour toute la taille. *C'est exactement l'illusion qui a
     fabrique un faux edge de +31 bps dans T1 (le bid-ask bounce).*

  🔒 **CARNET TROP MINCE -> `rempli=False`.** Jamais un prix moyen calcule sur une taille qu'on
     n'aurait pas obtenue. **Ne pas savoir n'est pas une permission.**

PUR : arithmetique sur un carnet. Aucun reseau. Aucun ordre reel. Paper-only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

# Au-dela, le carnet ne paie plus : *un edge sur un carnet de 3 $ n'existe pas.*
SLIPPAGE_ABSURDE_BPS = 500.0


@dataclass(frozen=True, slots=True)
class Marche:
    """Le resultat d'une marche dans le carnet, niveau par niveau."""
    rempli: bool
    prix_moyen: float
    prix_reference: float
    slippage_bps: float
    notionnel_obtenu: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "rempli": self.rempli,
            "prix_moyen": self.prix_moyen,
            "prix_reference": self.prix_reference,
            "slippage_bps": round(self.slippage_bps, 3),
            "notionnel_obtenu": round(self.notionnel_obtenu, 2),
            "real_execution": False,
        }


@dataclass(frozen=True, slots=True)
class VerdictProfondeur:
    slippage_total_bps: float
    apr_apres_slippage: float
    survit: bool
    verdict: str


def niveaux(book: Any, cote: int) -> list[tuple[float, float]]:
    """`(px, sz)` depuis un carnet L2 HL. Liste **VIDE** si illisible -- jamais un prix invente.

    cote 0 = bids (on VEND dedans) · cote 1 = asks (on ACHETE dedans).
    """
    lv = book.get("levels") if isinstance(book, Mapping) else None
    if not isinstance(lv, (list, tuple)) or len(lv) != 2:
        return []
    cote_lv = lv[cote]
    if not isinstance(cote_lv, (list, tuple)):
        return []
    out: list[tuple[float, float]] = []
    for n in cote_lv:
        try:
            px, sz = float(n["px"]), float(n["sz"])
        except (KeyError, TypeError, ValueError):
            continue                       # DENY-BY-DEFAULT : un niveau illisible est ECARTE
        if px > 0 and sz > 0:
            out.append((px, sz))
    return out


def marcher_dans_le_carnet(lv: Sequence[tuple[float, float]], notionnel_usd: float) -> Marche:
    """🔑 **On MARCHE dans le carnet.** *Le meilleur prix ne tient pas pour toute la taille.*

    Renvoie `rempli=False` si la profondeur ne suffit pas -- **jamais un prix moyen fantome.**
    """
    if not lv or notionnel_usd <= 0:
        return Marche(False, 0.0, 0.0, 0.0, 0.0)

    ref = lv[0][0]                     # le meilleur prix : la REFERENCE, pas le prix obtenu
    reste = float(notionnel_usd)
    cout = 0.0
    qte = 0.0

    for px, sz in lv:
        dispo = px * sz
        if dispo <= 0:
            continue
        pris = min(reste, dispo)
        cout += pris
        qte += pris / px
        reste -= pris
        if reste <= 1e-9:
            break

    if reste > 1e-9 or qte <= 0:
        # 🔒 CARNET TROP MINCE. *Ne pas savoir n'est pas une permission.*
        return Marche(False, 0.0, ref, 0.0, cout)

    moyen = cout / qte
    slip = abs(moyen - ref) / ref * 1e4 if ref > 0 else 0.0
    return Marche(True, moyen, ref, slip, cout)


def verdict_carry(apr_net: float, spot_achat: Marche, spot_vente: Marche,
                  perp_vente: Marche, perp_achat: Marche,
                  *, horizon_heures: float = 720.0) -> VerdictProfondeur:
    """L'edge survit-il au carnet REEL ? **Les 4 jambes, pas une seule.**

    Le slippage est un cout d'**ENTREE/SORTIE** : il se paie une fois, puis s'amortit sur
    l'horizon de detention -- exactement comme les frais. *On ne le compte donc pas en APR
    perpetuel : on l'amortit honnetement.*
    """
    jambes = (spot_achat, spot_vente, perp_vente, perp_achat)

    if not all(j.rempli for j in jambes):
        return VerdictProfondeur(
            0.0, 0.0, False,
            "🔴 **CARNET TROP MINCE POUR NOTRE TAILLE.** *Un edge sur un carnet de 3 $ n'existe "
            "pas.* -> **NO_TRADE**, et ce n'est pas une panne : c'est le systeme qui refuse.",
        )

    total = sum(j.slippage_bps for j in jambes)
    if total >= SLIPPAGE_ABSURDE_BPS:
        return VerdictProfondeur(
            total, 0.0, False,
            "🔴 **SLIPPAGE ABSURDE (%.0f bps).** Le carnet ne paie pas. **NO_TRADE.**" % total,
        )

    # amorti sur l'horizon, comme les frais -- puis reparti sur les DEUX jambes de capital
    cout_annualise_bps = total * (24 * 365 / horizon_heures) / 2.0
    apr_apres = apr_net - cout_annualise_bps / 1e4

    if apr_apres <= 0:
        return VerdictProfondeur(
            total, apr_apres, False,
            "🔴 **LE SLIPPAGE MANGE TOUT L'EDGE** (%.2f bps -> APR %+.2f %%). **NO_TRADE.**"
            % (total, apr_apres * 100),
        )
    return VerdictProfondeur(
        total, apr_apres, True,
        "✅ l'edge survit au carnet reel : **%+.2f %% APR** apres %.2f bps de slippage. "
        "⚠️ *Mesure sur un instantane du carnet -- il peut etre plus mince au moment d'entrer.*"
        % (apr_apres * 100, total),
    )


__all__ = [
    "SLIPPAGE_ABSURDE_BPS", "Marche", "VerdictProfondeur",
    "marcher_dans_le_carnet", "niveaux", "verdict_carry",
]
