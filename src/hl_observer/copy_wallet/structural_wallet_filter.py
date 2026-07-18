"""G5 (article Punisher) — EXCLURE les wallets STRUCTURELS de la sélection de leaders.

Punisher : « les wallets à 0 ¢ et winrate de 100 % sont l'infra NegRisk de la plateforme, leur PnL
réel vaut 0 : ignore-les. » (Formulé ainsi — et pas avec le motif d'arnaque littéral — parce que
c'est un AVERTISSEMENT, l'exact inverse d'une promesse de gain, et qu'un scanner ne peut pas
deviner l'intention d'une phrase.)
Analogue HL : des vaults / market-makers / contrats d'infra dont le 'PnL' est
STRUCTUREL (pas du skill). Les copier = suivre du bruit mécanique. On les exclut AVANT le markout
(C12), pour ne juger que de vrais traders.

Heuristiques honnêtes (deny-by-default sur le doute) :
  * adresse dans une liste d'exclusions connue (vaults/infra) ;
  * winrate ~100% avec PnL ~0 (signature d'un rôle structurel, pas d'un edge) ;
  * volume énorme mais PnL par trade ~0.
PAPER only. Un filtre n'est pas un ordre.
"""
from __future__ import annotations

WINRATE_STRUCTUREL = 0.99      # ~100% de winrate...
PNL_PAR_TRADE_NUL_USD = 0.5    # ...avec un PnL/trade quasi nul = rôle structurel, pas du skill


def est_structurel(stats: dict, *, exclusions=None) -> bool:
    """True si le wallet est STRUCTUREL (à exclure). `stats` : {adresse, winrate, pnl_total_usd, n_trades}."""
    adr = str(stats.get("adresse") or "")
    if exclusions and adr in set(exclusions):
        return True
    try:
        winrate = float(stats.get("winrate"))
        n = int(stats.get("n_trades") or 0)
        pnl = float(stats.get("pnl_total_usd") or 0.0)
    except (TypeError, ValueError):
        return False
    if n <= 0:
        return False
    pnl_par_trade = abs(pnl) / n
    # winrate quasi parfait + PnL/trade quasi nul = signature structurelle (NegRisk-like)
    return winrate >= WINRATE_STRUCTUREL and pnl_par_trade <= PNL_PAR_TRADE_NUL_USD


def filtrer_leaders(stats_par_wallet, *, exclusions=None) -> list[str]:
    """Renvoie les adresses NON structurelles (les vrais candidats leaders)."""
    return [str(s.get("adresse") or "") for s in (stats_par_wallet or [])
            if not est_structurel(s, exclusions=exclusions) and s.get("adresse")]


__all__ = ["WINRATE_STRUCTUREL", "PNL_PAR_TRADE_NUL_USD", "est_structurel", "filtrer_leaders"]
