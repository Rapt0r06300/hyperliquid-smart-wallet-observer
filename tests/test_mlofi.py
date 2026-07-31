"""ALPHA — MLOFI multi-niveaux : OFI par niveau, vecteur, intégré, depth slope/convexity, expérience."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import mlofi as M  # noqa: E402


def _book(bp, bs, ap, as_, n=5):
    return {"bids": [[bp - i * 0.01, bs] for i in range(n)],
            "asks": [[ap + i * 0.01, as_] for i in range(n)]}


def test_ofi_niveau_signe():
    prev = _book(100.0, 5, 101.0, 5)
    cur = _book(100.5, 7, 101.5, 5)      # bid monte + grossit, ask monte -> pression acheteuse
    assert M.ofi_niveau(prev, cur, 0) > 0


def test_mlofi_vecteur_longueur():
    prev = _book(100.0, 5, 101.0, 5)
    cur = _book(100.0, 8, 101.0, 5)      # même prix, bid grossit -> OFI L1 = +3
    v = M.mlofi(prev, cur, niveaux=5)
    assert len(v) == 5 and v[0] == 3.0


def test_mlofi_integre_pondere():
    v = [10.0, 4.0, 3.0, None, None]
    # poids par défaut 1, 1/2, 1/3 -> 10 + 2 + 1 = 13
    assert abs(M.mlofi_integre(v) - 13.0) < 1e-9


def test_depth_slope_positive_et_convexity():
    # profondeur cumulée croissante et linéaire -> pente > 0, convexité ~ 0
    book = {"bids": [[100 - i * 0.01, 10] for i in range(5)], "asks": [[100 + i * 0.01, 10] for i in range(5)]}
    assert M.depth_slope(book) > 0
    assert abs(M.convexity(book)) < 1e-6


def test_experience_more_data_si_petit():
    books = [_book(100.0, 5, 101.0, 5) for _ in range(10)]
    assert M.experience_mlofi(books)["verdict"] == "MORE_DATA"


def test_experience_rend_les_cles_attendues():
    books = []
    bs = 10.0
    for i in range(200):
        bs = 15.0 if i % 2 == 0 else 8.0     # taille bid oscille -> OFI L1 non nul
        books.append(_book(100.0, bs, 100.02, 10.0))
    r = M.experience_mlofi(books, niveaux=5, horizon_pas=1, fee_bps=9.0)
    assert "net_oos_MLOFI" in r and "net_oos_L1" in r and "increment_multiniveaux_bps" in r
    assert r["verdict"] in ("KILL", "MORE_DATA", "OOS_POSITIF_A_FORWARD")
