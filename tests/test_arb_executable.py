"""ARBITRAGE AU PRIX EXÉCUTABLE (Levier 3) — le modèle conservateur de coût d'exécution. On
VERROUILLE : 4 franchissements de spread comptés, deny-by-default LARGE, et un verdict honnête
(net ≤ 0 => le mid était une illusion). Aucune donnée réseau, aucun ordre."""
from __future__ import annotations

from hl_observer.funding import arb_executable as X


def test_le_cout_executable_compte_4_franchissements_de_spread():
    # 13 frais + 2*(1.5+0.75) spread + 2 impact = 19.5
    assert X.cout_executable_bps() == 19.5


def test_spread_inconnu_prend_une_hypothese_LARGE_deny_by_default():
    # un demi-spread None retombe sur le defaut conservateur, jamais 0
    assert X.cout_executable_bps(half_spread_hl_bps=None) == X.cout_executable_bps()


def test_une_petite_convergence_MEURT_a_l_execution():
    # entre a 20, sort a 15 : capture 5 bps < cout 19.5 -> net negatif
    assert X.net_executable_bps(20.0, 15.0) == round(5.0 - 19.5, 4)


def test_une_grosse_convergence_survit():
    assert X.net_executable_bps(40.0, 2.0) > 0        # capture 38 > 19.5


def test_population_qui_ne_survit_pas_le_dit_honnetement():
    # des ecarts qui convergent peu (5 bps) : sous le seuil 19 -> ignores ; ceux au-dessus meurent
    signaux = [(25.0, 22.0), (30.0, 26.0), (28.0, 24.0)]   # captures 3-4 bps << 19.5
    r = X.verdict_population(signaux, seuil_bps=19.0)
    assert r["signaux"] == 3 and r["net_total_usd"] < 0
    assert "NE" in r["verdict"] and "survit" in r["verdict"] and r["real_execution"] is False


def test_population_franchement_positive_est_encourageante():
    signaux = [(50.0, 2.0), (45.0, 1.0)]              # captures ~48 bps >> 19.5
    r = X.verdict_population(signaux, seuil_bps=19.0)
    assert r["net_total_usd"] > 0 and "POSITIVE" in r["verdict"]


def test_seuil_ecarte_les_signaux_trop_petits():
    r = X.verdict_population([(10.0, 2.0)], seuil_bps=19.0)     # 10 < 19 -> rien a juger
    assert r["signaux"] == 0 and "rien a juger" in r["verdict"]


def test_un_ecart_ABSURDE_est_ecarte_pas_capture_comme_edge():
    """🔴 Sur donnee reelle, un |ecart| de 1 670 616 bps (mauvais appariement) gonflait le net.
    Un tel ecart est ECARTE (m, pas capture) : on ne fabrique pas un edge avec une aberration."""
    signaux = [(1_670_616.0, 2.0), (40.0, 2.0)]   # 1 aberrant, 1 vrai
    r = X.verdict_population(signaux, seuil_bps=19.0)
    assert r["ecartes_aberrants"] == 1 and r["signaux"] == 1   # seul le vrai est juge
