"""#372 / X-11 — LA CARTE DES LIQUIDATIONS. Et la correction d'une chose que j'ai dite TROIS FOIS.

🔴 J'AI ECRIT TROIS FOIS QUE X-11 ETAIT « BLOQUE SUR UNE DONNEE QU'ON NE COLLECTE PAS ». **FAUX.**

`clearinghouseState` -- **un appel qu'on fait DEJA** -- rend `liquidationPx` pour chaque position.
Et ce mot n'apparaissait **NULLE PART** dans le code : `snapshot_service` ne garde que
`coin / szi / entryPx`.

*Ce n'etait pas une donnee manquante. C'etait une donnee RECUE ET EFFACEE.*

Aucun ordre reel.
"""
from __future__ import annotations

import pytest

from hl_observer.market.liquidation_map import (
    MIN_NOTIONNEL_GRAPPE_USD,
    MIN_WALLETS_PAR_GRAPPE,
    construire_carte,
    parser_positions,
    resume,
)


def _etat(*positions) -> dict:
    """Le format REEL de `clearinghouseState` de Hyperliquid."""
    return {"assetPositions": [{"type": "oneWay", "position": p} for p in positions]}


# ============================================================ 1. LE CHAINON QUI MANQUAIT


def test_on_LIT_ENFIN_le_liquidationPx_qu_on_recevait_deja():
    """🔴 LE POINT DE TOUTE LA TACHE."""
    pos = parser_positions("0xabc", _etat({
        "coin": "BTC", "szi": "0.5", "entryPx": "60000", "positionValue": "30000",
        "liquidationPx": "54000", "marginUsed": "3000",
    }))
    assert len(pos) == 1
    assert pos[0].liq_px == pytest.approx(54000.0)
    assert pos[0].notionnel_usd == pytest.approx(30000.0)


def test_un_LONG_liquide_provoque_une_VENTE_forcee():
    """La mecanique, pas une prediction : un long saute quand le prix DESCEND jusqu'a lui, et
    l'exchange VEND. Un short saute quand le prix MONTE, et l'exchange ACHETE."""
    lg = parser_positions("0x1", _etat({
        "coin": "ETH", "szi": "2", "entryPx": "3000", "positionValue": "6000",
        "liquidationPx": "2700",
    }))[0]
    sh = parser_positions("0x2", _etat({
        "coin": "ETH", "szi": "-2", "entryPx": "3000", "positionValue": "6000",
        "liquidationPx": "3300",
    }))[0]
    assert lg.sens_du_flux_force == "SELL"
    assert sh.sens_du_flux_force == "BUY"


# ============================================================ 2. DENY-BY-DEFAULT


def test_une_position_SANS_liquidationPx_est_ECARTEE_pas_INVENTEE():
    """*Une carte avec des prix inventes est PIRE qu'aucune carte.*"""
    for manquant in (None, "", "null"):
        pos = parser_positions("0x1", _etat({
            "coin": "SOL", "szi": "10", "entryPx": "150", "liquidationPx": manquant,
        }))
        assert pos == []


def test_une_position_de_taille_NULLE_est_ecartee():
    assert parser_positions("0x1", _etat({
        "coin": "SOL", "szi": "0", "entryPx": "150", "liquidationPx": "120",
    })) == []


def test_un_payload_CASSE_ne_fait_pas_planter_ni_inventer():
    assert parser_positions("0x1", {}) == []
    assert parser_positions("0x1", {"assetPositions": "pas une liste"}) == []
    assert parser_positions("0x1", {"assetPositions": [{"position": "casse"}]}) == []


# ============================================================ 3. LES GRAPPES


def test_UN_SEUL_wallet_ne_fait_PAS_un_flux():
    """Une position isolee n'est pas une cascade. *Un flux force, c'est un AMAS.*"""
    p = parser_positions("0x1", _etat({
        "coin": "BTC", "szi": "1", "entryPx": "60000", "positionValue": "60000",
        "liquidationPx": "54000",
    }))
    assert construire_carte(p, {"BTC": 60000.0}) == []


def test_plusieurs_wallets_au_MEME_prix_forment_une_GRAPPE():
    ps = []
    for i in range(4):
        ps += parser_positions("0x%d" % i, _etat({
            "coin": "BTC", "szi": "1", "entryPx": "60000", "positionValue": "60000",
            "liquidationPx": str(54000 + i * 10),      # tous dans 50 bps
        }))
    g = construire_carte(ps, {"BTC": 60000.0})
    assert len(g) == 1
    assert g[0].n_wallets == 4
    assert g[0].sens == "SELL"                          # des LONGS -> ventes forcees
    assert g[0].notionnel_usd == pytest.approx(240_000.0)
    assert g[0].distance_bps == pytest.approx(1e4 * (60000 - 54015) / 60000, rel=0.01)


def test_une_grappe_TROP_PETITE_en_notionnel_est_ecartee():
    ps = []
    for i in range(3):
        ps += parser_positions("0x%d" % i, _etat({
            "coin": "SOL", "szi": "1", "entryPx": "150", "positionValue": "150",
            "liquidationPx": "135",
        }))
    assert sum(p.notionnel_usd for p in ps) < MIN_NOTIONNEL_GRAPPE_USD
    assert construire_carte(ps, {"SOL": 150.0}) == []


def test_les_LONGS_et_les_SHORTS_ne_se_melangent_JAMAIS():
    """Deux flux OPPOSES au meme prix ne s'annulent pas : ils se declenchent a des moments
    differents (le prix ne peut pas monter ET descendre). Les fondre serait un mensonge."""
    ps = []
    for i in range(3):
        ps += parser_positions("0xL%d" % i, _etat({
            "coin": "ETH", "szi": "5", "entryPx": "3000", "positionValue": "15000",
            "liquidationPx": "2700",
        }))
        ps += parser_positions("0xS%d" % i, _etat({
            "coin": "ETH", "szi": "-5", "entryPx": "3000", "positionValue": "15000",
            "liquidationPx": "3300",
        }))
    g = construire_carte(ps, {"ETH": 3000.0})
    sens = {x.sens for x in g}
    assert sens == {"SELL", "BUY"}
    assert len(g) == 2


def test_sans_PRIX_COURANT_on_ne_calcule_AUCUNE_distance():
    """Deny-by-default : sans prix, pas de distance -> pas de grappe. On n'invente pas un « 0 »."""
    ps = []
    for i in range(3):
        ps += parser_positions("0x%d" % i, _etat({
            "coin": "BTC", "szi": "1", "entryPx": "60000", "positionValue": "60000",
            "liquidationPx": "54000",
        }))
    assert construire_carte(ps, {}) == []


# ============================================================ 4. L'HONNETETE DU RESUME


def test_le_resume_DIT_qu_il_ne_PROUVE_RIEN():
    """⚠️ Cette carte dit **OU** le flux forcé tombera. Elle ne dit **PAS** qu'il est rentable de
    le prendre.

    Le depassement de prix doit dominer le mouvement subi en portant l'inventaire -- **c'est
    exactement le test qui a tue le market making (T1b), et il n'est PAS fait.**

    Un module qui laisserait croire le contraire serait une promesse de PnL. Interdit.
    """
    r = resume([])
    assert "T1b" in r["avertissement"]
    assert "PAS FAIT" in r["avertissement"] or "IL N'EST PAS FAIT" in r["avertissement"]
    assert "markout" in r["mesure_manquante"]
    assert "historique" in r["mesure_manquante"].lower()
    assert r["real_execution"] is False
