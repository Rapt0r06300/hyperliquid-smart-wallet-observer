"""Le facteur de taille (Y4/Y15/Y16) est CÂBLÉ dans l'ouverture carry : il scale le notional,
borné [0.25,2.0], absent -> 1.0 (rétro-compatible). PAPER only."""
from __future__ import annotations

from hl_observer.funding.carry_position_lifecycle import ouvrir_position

DEC = {"coin": "HYPE", "viable": True}


def _inp(**kw):
    base = {"levier_utilise": 1.5, "levier_max": 10.0, "marge_ratio": 1.0 / 1.5,
            "cout_entree_bps": 11.0, "perp_px": 40.0}
    base.update(kw)
    return base


def test_facteur_absent_taille_de_base():
    p = ouvrir_position(DEC, _inp(), now_ms=1_000)
    assert p is not None and abs(p["notional_usdt"] - 50.0 * 1.5) < 1e-6   # 75


def test_facteur_amplifie_borne():
    gros = ouvrir_position(DEC, _inp(facteur_taille=1.5), now_ms=1_000)
    assert abs(gros["notional_usdt"] - 50.0 * 1.5 * 1.5) < 1e-6            # 112.5
    plafonne = ouvrir_position(DEC, _inp(facteur_taille=99.0), now_ms=1_000)
    assert abs(plafonne["notional_usdt"] - 50.0 * 2.0 * 1.5) < 1e-6        # borné à 2×


def test_facteur_reduit_borne_plancher():
    petit = ouvrir_position(DEC, _inp(facteur_taille=0.01), now_ms=1_000)
    assert abs(petit["notional_usdt"] - 50.0 * 0.25 * 1.5) < 1e-6          # plancher 0.25×
