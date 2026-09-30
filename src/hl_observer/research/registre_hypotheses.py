"""#36 — REGISTRE DES HYPOTHÈSES TESTÉES : ne jamais re-tester ce qui est déjà MORT, et ne jamais
« redécouvrir » une idée réfutée. Chaque entrée porte son verdict et sa preuve chiffrée.
100 % lecture/mémoire. Aucun ordre.
"""
from __future__ import annotations

# Verdicts mesurés du projet (chiffres réels, pas des impressions).
REGISTRE: dict[str, dict] = {
    "copy_trading": {"verdict": "MORT", "preuve": "-7,97 bps OOS sur 24 133 signaux, meme a cout zero",
                     "detail": "le leader est CONTRARIEN : probleme de CONTENU, pas de vitesse"},
    "market_making": {"verdict": "MORT", "preuve": "0/29 configs positives a 100% de fill (borne haute)",
                      "detail": "le prix bouge 5-30x le spread : le spread est le PRIX du risque"},
    "funding_perp_perp_meme_venue": {"verdict": "MORT", "preuve": "0/120",
                                     "detail": "pas de dispersion exploitable sur la meme venue"},
    "lead_lag_btc_alts": {"verdict": "MORT", "preuve": "0/66 ; corr(0)=+0,83 vs corr(2h)=-0,03",
                          "detail": "les alts bougent AVEC BTC, ils ne le SUIVENT pas"},
    "carry_delta_neutre": {"verdict": "VIVANT", "preuve": "~2% APR mesure, seul resultat positif",
                           "detail": "break-even ~76-88 h : il faut TENIR, pas churner"},
    "liquidations": {"verdict": "NON_TESTE", "preuve": "mesure prete (liquidation_edge_measure)",
                     "detail": "meilleure piste restante : le liquide est FORCE, il ne choisit pas"},
}


def verdict(hypothese: str) -> dict | None:
    """Verdict connu d'une hypothese. None = jamais testee (donc testable)."""
    return REGISTRE.get(str(hypothese).strip().lower())


def est_morte(hypothese: str) -> bool:
    """True si l'hypothese a deja ete REFUTEE avec preuve -> ne pas la re-tester sans element neuf."""
    v = verdict(hypothese)
    return bool(v and v.get("verdict") == "MORT")


def pistes_ouvertes() -> list[str]:
    """Ce qui reste honnetement a explorer (ni mort, ni deja valide)."""
    return sorted(k for k, v in REGISTRE.items() if v.get("verdict") == "NON_TESTE")


__all__ = ["REGISTRE", "verdict", "est_morte", "pistes_ouvertes"]
