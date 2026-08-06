"""[Bloc 39-40/46/38-45] Moteur paper unique + enveloppe 1000 USD + les 3 familles -> PaperIntent."""
from hl_observer.hyperlab.paper_engine import MoteurPaper, PaperIntent
from hl_observer.hyperlab.strategies import CopyVault, CrossVenue, LeadLag


def test_fill_frais_et_ledger():
    m = MoteurPaper(1000.0)
    r = m.soumettre(PaperIntent("copy_vault", "bybit", "BTCUSDT", "buy", 100.0, 60000.0, 1.0),
                    cout_bps=5.0, slippage_bps=2.0)
    assert r["accepte"] and len(m.fills) == 1
    assert abs(m.frais_cumules - 100.0 * 5 / 1e4) < 1e-9
    assert r["fill"]["prix_exec"] > 60000.0   # buy -> slippage positif


def test_enveloppe_1000_partagee_refuse():
    m = MoteurPaper(1000.0)
    assert m.soumettre(PaperIntent("copy_vault", "v", "S", "buy", 400.0, 100.0, 1.0))["accepte"]
    assert m.soumettre(PaperIntent("lead_lag", "v", "T", "buy", 400.0, 100.0, 1.0))["accepte"]
    r = m.soumettre(PaperIntent("cross_venue", "v", "U", "buy", 400.0, 100.0, 1.0))
    assert r["accepte"] is False and r["raison"] == "enveloppe_1000_depassee"
    assert m.exposition_brute() <= 1000.0 + 1e-9


def test_copyvault_miroir():
    intents = CopyVault().generer_intents(
        {"venue": "bybit", "symbole": "BTCUSDT", "side": "sell", "prix_ref": 60000.0, "poids": 0.5},
        notionnel_usd=200.0, ts=1.0)
    assert len(intents) == 1 and intents[0].side == "sell" and intents[0].notionnel_usd == 100.0


def test_leadlag_ofi_signe():
    prev = {"bid": 100, "bid_sz": 5, "ask": 101, "ask_sz": 5}
    cur = {"bid": 100, "bid_sz": 9, "ask": 101, "ask_sz": 5}   # pression bid en hausse -> buy
    intents = LeadLag().generer_intents(prev, cur, venue="bybit", symbole="BTCUSDT",
                                        notionnel_usd=100.0, ts=1.0)
    assert len(intents) == 1 and intents[0].side == "buy"
    # pas de changement -> pas de signal
    assert LeadLag().generer_intents(prev, prev, venue="b", symbole="s", notionnel_usd=100, ts=1) == []


def test_crossvenue_deux_jambes():
    a = {"mid": 60000.0, "venue": "bybit"}
    b = {"mid": 60100.0, "venue": "okx"}
    intents = CrossVenue().generer_intents(a["mid"], b["mid"], venue_a="bybit", venue_b="okx",
                                           symbole="BTCUSDT", notionnel_usd=100.0, ts=1.0, seuil_bps=5)
    sides = {(i.venue, i.side) for i in intents}
    assert len(intents) == 2 and ("bybit", "buy") in sides and ("okx", "sell") in sides
    # ecart trop faible -> rien
    assert CrossVenue().generer_intents(60000.0, 60000.5, venue_a="a", venue_b="b", symbole="s",
                                        notionnel_usd=100, ts=1, seuil_bps=5) == []
