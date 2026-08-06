"""[Bloc 39-40/46/71 / AUD-071,084,094] Moteur economique UNIQUE paper.

PaperIntent -> ordre paper -> fill (avec frais + slippage mesures) -> ledger -> equity, avec une
ENVELOPPE GLOBALE unique de 1000 USD partagee par TOUTES les lanes/familles (AUD-094/084) : un intent
qui ferait depasser l'exposition brute totale est REFUSE (jamais silencieusement tronque a moitie).
Un seul moteur (AUD-071) : toutes les familles passent par ici. 0 ordre reel, 0 cle, capital fictif.
"""
from __future__ import annotations

from typing import Optional


class PaperIntent:
    def __init__(self, famille: str, venue: str, symbole: str, side: str, notionnel_usd: float,
                 prix_ref: float, ts: float) -> None:
        assert side in ("buy", "sell"), "side invalide: %s" % side
        self.famille = famille
        self.venue = venue
        self.symbole = symbole
        self.side = side
        self.notionnel_usd = float(notionnel_usd)
        self.prix_ref = float(prix_ref)
        self.ts = ts


class MoteurPaper:
    def __init__(self, capital_usd: float = 1000.0) -> None:
        self.capital_usd = float(capital_usd)
        self.enveloppe_usd = float(capital_usd)
        self.fills = []
        self.ledger = []
        self.frais_cumules = 0.0
        self._expo_par_cle = {}  # (venue,symbole) -> notionnel signe

    def exposition_brute(self) -> float:
        return sum(abs(v) for v in self._expo_par_cle.values())

    def soumettre(self, intent: PaperIntent, *, cout_bps: float = 5.0, slippage_bps: float = 2.0) -> dict:
        """Refuse si l'exposition brute totale depasserait l'enveloppe 1000 USD (AUD-094). Sinon fill."""
        if self.exposition_brute() + intent.notionnel_usd > self.enveloppe_usd + 1e-9:
            rej = {"accepte": False, "raison": "enveloppe_1000_depassee",
                   "expo_brute": self.exposition_brute(), "demande": intent.notionnel_usd}
            self.ledger.append({"type": "REFUS", **rej, "famille": intent.famille})
            return rej
        signe = 1.0 if intent.side == "buy" else -1.0
        prix_exec = intent.prix_ref * (1.0 + signe * slippage_bps / 1e4)
        frais = intent.notionnel_usd * cout_bps / 1e4
        self.frais_cumules += frais
        cle = (intent.venue, intent.symbole)
        self._expo_par_cle[cle] = self._expo_par_cle.get(cle, 0.0) + signe * intent.notionnel_usd
        fill = {"famille": intent.famille, "venue": intent.venue, "symbole": intent.symbole,
                "side": intent.side, "notionnel": intent.notionnel_usd, "prix_exec": prix_exec,
                "frais": frais, "ts": intent.ts}
        self.fills.append(fill)
        self.ledger.append({"type": "FILL", **fill})
        return {"accepte": True, "fill": fill}

    def equity(self, marks: Optional[dict] = None) -> dict:
        """equity = capital - frais + PnL non realise (marks par (venue,symbole)). Sans mark -> 0 non
        realise pour cette cle (jamais invente)."""
        marks = marks or {}
        non_realise = 0.0
        for (venue, sym), notion in self._expo_par_cle.items():
            m = marks.get((venue, sym))
            if m is None:
                continue
            # approx : notion deja en USD au prix ref ; PnL = notion_signe * (mark/ref - 1) non dispo ici,
            # on expose le notionnel net marque comme variation relative fournie par l'appelant
            non_realise += notion * float(m)
        eq = self.capital_usd - self.frais_cumules + non_realise
        return {"equity": eq, "capital": self.capital_usd, "frais": self.frais_cumules,
                "non_realise": non_realise, "expo_brute": self.exposition_brute()}
