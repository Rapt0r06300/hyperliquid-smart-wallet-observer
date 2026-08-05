"""[AUD-353/354/355/356/357/362] Integrite wallets/leaders : detection SYBILS & wallets MIROIRS,
exclusion des TRANSFERTS du PnL, correction SURVIVORSHIP, inclusion des wallets LIQUIDES dans les
cohortes historiques, consensus PONDERE PAR INDEPENDANCE et seuil de confiance pour reduire les FAUX
MERGES d'entites. stdlib pure, 0 reseau, 0 ordre reel."""
from __future__ import annotations

from typing import Mapping, Sequence


def detecter_sybils(correlations: Mapping[tuple, float], *, seuil: float = 0.95) -> dict:
    """Deux wallets aux trades quasi-identiques (correlation >= seuil) sont probablement un MEME acteur
    (sybil/miroir) -> compter une seule fois (sinon crowding et consensus fausses)."""
    paires = sorted(p for p, c in correlations.items() if c >= seuil)
    return {"sybils_suspects": paires, "n": len(paires)}


def transferts_hors_pnl(mouvements: Sequence[Mapping]) -> dict:
    """Un DEPOT/RETRAIT n'est PAS du PnL : on l'exclut de la performance (un virement ne doit pas
    gonfler/plomber la 'perf' d'un wallet)."""
    est_transfert = lambda t: t in ("deposit", "withdrawal", "transfer")
    pnl = sum(m.get("montant", 0.0) for m in mouvements if m.get("type") == "trade")
    transferts = sum(m.get("montant", 0.0) for m in mouvements if est_transfert(m.get("type")))
    return {"pnl": pnl, "transferts_exclus": transferts,
            "n_transferts": sum(1 for m in mouvements if est_transfert(m.get("type")))}


def correction_survivorship(cohorte_complete: Sequence[str], cohorte_survivante: Sequence[str]) -> dict:
    """Survivorship bias : ne garder que les SURVIVANTS surestime la performance. On signale les
    disparus a reintegrer pour une mesure honnete."""
    disparus = sorted(set(cohorte_complete) - set(cohorte_survivante))
    taux = len(disparus) / len(cohorte_complete) if cohorte_complete else 0.0
    return {"disparus": disparus, "taux_disparition": round(taux, 4), "biais_present": len(disparus) > 0}


def inclure_wallets_liquides(cohorte: Sequence[Mapping]) -> dict:
    """Une cohorte historique DOIT inclure les wallets LIQUIDES (sinon on ne voit que les gagnants)."""
    n_liquides = sum(1 for w in cohorte if w.get("liquide"))
    return {"n_total": len(cohorte), "n_liquides": n_liquides,
            "cohorte_suspecte": len(cohorte) > 0 and n_liquides == 0}


def consensus_pondere_independance(votes: Mapping[str, float], groupes: Mapping[str, str]) -> dict:
    """Consensus PONDERE PAR INDEPENDANCE : N wallets d'un MEME acteur (meme groupe) = UNE voix -> un
    sybil ne peut pas fabriquer un faux consensus."""
    par_groupe: dict = {}
    for wallet, vote in votes.items():
        par_groupe.setdefault(groupes.get(wallet, wallet), []).append(vote)
    voix = {g: sum(v) / len(v) for g, v in par_groupe.items()}
    return {"consensus": (sum(voix.values()) / len(voix)) if voix else 0.0,
            "n_voix_independantes": len(voix)}


def seuil_confiance_merge(liens: Sequence[Mapping], *, seuil: float = 0.8) -> dict:
    """Ne FUSIONNE deux entites que si la confiance du lien >= seuil : sous le seuil, pas de merge
    (reduit les FAUX merges qui fabriquent des acteurs fantomes)."""
    retenus = [(l["a"], l["b"]) for l in liens if l.get("confiance", 0.0) >= seuil]
    rejetes = [(l["a"], l["b"]) for l in liens if l.get("confiance", 0.0) < seuil]
    return {"merges_retenus": retenus, "merges_rejetes": rejetes}
