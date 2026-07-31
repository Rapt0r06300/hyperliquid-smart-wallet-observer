"""ALPHA FIX-36 — Deflated Sharpe Ratio : un Sharpe choisi parmi beaucoup d'essais doit être déflaté."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import deflated_sharpe as D  # noqa: E402


def test_phi_inv_quantiles_connus():
    assert abs(D._phi_inv(0.975) - 1.959964) < 1e-3       # z_{0.975}
    assert abs(D._phi_inv(0.5)) < 1e-6


def test_sharpe_max_croit_avec_le_nombre_dessais():
    s10 = D.sharpe_max_attendu(10, var_sr_trials=0.25)
    s1000 = D.sharpe_max_attendu(1000, var_sr_trials=0.25)
    assert 0 < s10 < s1000                                # plus on teste, plus le max sous H0 derive
    assert D.sharpe_max_attendu(1, 0.25) == 0.0           # 1 essai = pas de selection


def test_dsr_deflate_un_sharpe_choisi_parmi_beaucoup():
    seul = D.deflated_sharpe(0.5, n_trials=1, var_sr_trials=0.0, n_obs=100)
    beaucoup = D.deflated_sharpe(0.5, n_trials=1000, var_sr_trials=0.25, n_obs=100)
    assert seul["dsr"] > 0.99                             # SR=0.5, 1 essai -> significatif
    assert beaucoup["dsr"] < 0.5                          # meme SR parmi 1000 essais -> insignifiant
    assert beaucoup["sr_max_attendu"] > 0.5              # la barre de selection depasse le SR observe


def test_dsr_entrees_insuffisantes_none():
    assert D.deflated_sharpe(1.0, n_trials=1, var_sr_trials=0.1, n_obs=1) is None   # <2 obs -> None


def test_sharpe_depuis_votes():
    assert D.sharpe_depuis_votes([1.0]) is None                     # <2 votes
    assert D.sharpe_depuis_votes([5.0, 5.0, 5.0]) is None           # dispersion nulle -> non defini
    sr = D.sharpe_depuis_votes([2.0, 0.0, 2.0, 0.0])
    assert sr is not None and sr > 0
