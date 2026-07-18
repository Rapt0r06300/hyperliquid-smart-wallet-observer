"""#50 — CRITÈRE D'ARRÊT EXPLICITE : décider À FROID, maintenant, ce qui nous fera conclure
« c'est validé » ou « on arrête ». Sans ce critère, on peut tourner des mois en espérant.

Trois verdicts, aucun n'est une promesse :
  * VALIDE       : assez de jours ET PnL net > 0 ET bat le benchmark passif (vault HLP).
  * A_POURSUIVRE : pas encore assez de données pour trancher (on continue de mesurer).
  * ARRETER      : assez de données ET le résultat est <= 0 ou dominé par le passif.
« Dominé par le passif » = même un simple dépôt HLP aurait fait mieux -> notre travail n'ajoute rien.
100 % lecture/calcul. Aucun ordre. Ne promet aucun PnL.
"""
from __future__ import annotations

from dataclasses import dataclass

JOURS_MIN_POUR_TRANCHER = 14.0     # sous 2 semaines, on ne conclut pas (le carry met 3-4 j à rembourser)
TRADES_MIN_POUR_TRANCHER = 20      # et il faut un minimum d'événements


@dataclass(frozen=True)
class VerdictArret:
    verdict: str                    # VALIDE | A_POURSUIVRE | ARRETER
    raison: str
    jours: float
    pnl_net_usd: float
    benchmark_passif_usd: float
    bat_le_passif: bool

    def as_dict(self) -> dict:
        return {"verdict": self.verdict, "raison": self.raison, "jours": self.jours,
                "pnl_net_usd": self.pnl_net_usd, "benchmark_passif_usd": self.benchmark_passif_usd,
                "bat_le_passif": self.bat_le_passif, "promesse": "aucune", "real_execution": False}


def evaluer(*, jours_ecoules: float, pnl_net_usd: float, n_trades: int,
            capital_usd: float, apr_passif_pct: float = 2.0,
            jours_min: float = JOURS_MIN_POUR_TRANCHER,
            trades_min: int = TRADES_MIN_POUR_TRANCHER) -> VerdictArret:
    """Le benchmark passif = ce qu'aurait rapporté un simple dépôt (vault HLP) sur la même durée."""
    j = max(0.0, float(jours_ecoules))
    passif = float(capital_usd) * (float(apr_passif_pct) / 100.0) * (j / 365.0)
    bat = float(pnl_net_usd) > passif
    if j < float(jours_min) or int(n_trades) < int(trades_min):
        return VerdictArret("A_POURSUIVRE",
                            "pas encore assez de donnees (%.1f j / %d trades ; il faut >= %.0f j et >= %d)"
                            % (j, n_trades, jours_min, trades_min), round(j, 2),
                            round(float(pnl_net_usd), 4), round(passif, 4), bat)
    if float(pnl_net_usd) > 0 and bat:
        return VerdictArret("VALIDE", "PnL net positif ET superieur au depot passif", round(j, 2),
                            round(float(pnl_net_usd), 4), round(passif, 4), True)
    if float(pnl_net_usd) <= 0:
        return VerdictArret("ARRETER", "assez de donnees et PnL net <= 0", round(j, 2),
                            round(float(pnl_net_usd), 4), round(passif, 4), False)
    return VerdictArret("ARRETER", "positif mais DOMINE par un simple depot passif (on n'ajoute rien)",
                        round(j, 2), round(float(pnl_net_usd), 4), round(passif, 4), False)


__all__ = ["VerdictArret", "evaluer", "JOURS_MIN_POUR_TRANCHER", "TRADES_MIN_POUR_TRANCHER"]
