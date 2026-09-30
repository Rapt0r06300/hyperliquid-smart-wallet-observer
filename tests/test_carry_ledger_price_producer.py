"""Producteur carry : le prix DOIT arriver au ledger quand il existe.

Défaut mesuré au bloc 18 : `carry_paper_ledger.jsonl` = 190 lignes, **0 épisode exploitable**, parce que
100 % des ouvertures portaient `price: None`. La position contenait pourtant `prix_perp_entree` et
`entry_perp_px` — personne ne les transmettait au journal. Un épisode sans prix est économiquement mort
dès l'écriture : aucun replay ne peut le ressusciter.

Ces tests verrouillent les deux moitiés de la règle : un prix connu arrive au ledger ; un prix absent
reste `None` (jamais 0, jamais un mid de confort).

Paper only : 0 réseau, 0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.funding.carry_position_lifecycle import _prix_journal  # noqa: E402
from hl_observer.paper_trading.journal import PaperTradeJournal  # noqa: E402


# ═══════════════ le sélecteur de prix ═══════════════
def test_le_premier_prix_positif_est_retenu():
    assert _prix_journal(None, 0.0, 42.5, 99.0) == 42.5


def test_aucun_prix_exploitable_reste_none():
    assert _prix_journal() is None
    assert _prix_journal(None, None) is None


def test_un_prix_nul_ou_negatif_nest_jamais_un_prix():
    assert _prix_journal(0.0) is None
    assert _prix_journal(-3.0) is None
    assert _prix_journal(0.0, -1.0, 7.0) == 7.0        # on saute les invalides, on ne les corrige pas


def test_un_booleen_nest_pas_un_prix():
    assert _prix_journal(True) is None                  # True vaut 1 en Python : piège classique
    assert _prix_journal(False, 12.0) == 12.0


def test_un_nan_nest_jamais_un_prix():
    assert _prix_journal(float("nan")) is None


def test_une_chaine_nest_pas_convertie_en_silence():
    assert _prix_journal("100.0") is None               # une chaîne n'est pas une mesure


# ═══════════════ le journal transporte bien le prix ═══════════════
def test_le_journal_conserve_le_prix_transmis():
    j = PaperTradeJournal()
    ligne = j.record(kind="OPEN", coin="HYPE", side="CARRY", notional_usdt=100.0,
                     price=_prix_journal(38.42), reason="CARRY_NEUTRE_OUVERTURE", now_ms=1)
    assert ligne["price"] == 38.42
    assert ligne["not_an_order"] is True and ligne["simulation_only"] is True


def test_le_journal_garde_none_quand_le_prix_est_inconnu():
    j = PaperTradeJournal()
    ligne = j.record(kind="OPEN", coin="HYPE", side="CARRY", notional_usdt=100.0,
                     price=_prix_journal(None), reason="CARRY_NEUTRE_OUVERTURE", now_ms=1)
    assert ligne["price"] is None                       # honnête : inconnu, pas 0


# ═══════════════ l'appelant transmet réellement (anti-régression du défaut) ═══════════════
def test_les_trois_ecritures_carry_transmettent_un_prix():
    """OPEN, CLOSE et RENFORT doivent tous passer `price=` — c'est l'oubli qui a tue 190 lignes."""
    src = (RACINE / "src" / "hl_observer" / "funding" / "carry_position_lifecycle.py").read_text(
        encoding="utf-8")
    debut = 0
    for kind in ("OPEN", "CLOSE", "RENFORT"):
        marque = 'kind="%s"' % kind
        i = src.find(marque, debut)
        assert i > 0, "ecriture %s introuvable" % kind
        bloc = src[i:i + 420]
        fin = bloc.find(")\n")
        assert "price=" in bloc[:fin if fin > 0 else len(bloc)], \
            "l'ecriture %s du ledger carry ne transmet pas de prix" % kind


def test_un_episode_avec_prix_devient_mesurable_de_bout_en_bout():
    """Preuve economique : avec prix, l'episode est apparie et son PnL calculable."""
    from hl_observer.ops.economic_revalidation import normaliser_episodes

    j = PaperTradeJournal()
    j.record(kind="OPEN", coin="HYPE", side="CARRY", notional_usdt=1_000.0,
             price=_prix_journal(40.0), reason="CARRY_NEUTRE_OUVERTURE", now_ms=1)
    j.record(kind="CLOSE", coin="HYPE", side="CARRY", notional_usdt=1_000.0,
             price=_prix_journal(40.4), realized_net_pnl_usdc=0.0, reason="SORTIE", now_ms=2)
    lignes = [{**r, "sens": 1, "notional_usd": r["notional_usdt"],
               "prix_entree": r["price"], "prix_sortie": r["price"], "ts_ms": r["recorded_at_ms"]}
              for r in j.rows()]
    r = normaliser_episodes(lignes, strategie="carry")
    assert r["n_episodes"] == 1
    assert round(r["episodes"][0].pnl_net_usd(), 6) == 10.0     # +1 % sur 1 000 $
