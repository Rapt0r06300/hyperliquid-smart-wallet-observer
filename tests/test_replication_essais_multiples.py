"""LE MEILLEUR DE 105 COMPTES N'EST PAS UN EDGE — il faut le comparer au meilleur sous placebo.

LE DÉFAUT, MESURÉ LE 17/11/2026. Le rapport de réplication 350 USD classait 105 leaders par
net/jour et affichait **+18,85 USD/jour sur 350 USD** en tête, soit **+539 bps/jour**, sans aucun
correctif d'essais multiples. Prendre le maximum de 105 comptes sur 4 jours produit un sommet élevé
même en l'absence totale de compétence ; et c'est ce sommet que l'œil retient. Une politique gelée
à partir de ce tableau aurait gelé du bruit de sélection.

LE NULL : le portefeuille EXACT du leader, confronté au chemin de prix d'un AUTRE jour. Coins,
tailles, notionnels, rotation, ordre minimal et frais sont identiques ; seul l'alignement entre les
décisions du leader et les prix réalisés est détruit. Si le meilleur de 105 sous placebo atteint le
même sommet, le sommet réel ne dit rien.

Le verdict est rendu par `overfit_selection.borne_du_hasard`, réutilisée et non réécrite — elle
compare `max_reel > p95` **quel que soit le signe**, parce qu'un seuil écrasé à zéro rendait
autrefois « bruit » mécaniquement sur des données perdantes.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import overfit_selection as OS  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "etude_copiabilite", RACINE / "tools" / "etude_copiabilite.py")
EC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(EC)

T0 = 1_790_000_000_000
HEURE = 3_600_000


def _portefeuille(n: int = 60) -> list:
    return [(T0 + i * 60_000, 1_000.0, {"BTC": 0.01, "ETH": 0.5}) for i in range(n)]


def test_le_placebo_ne_decale_que_le_TEMPS(nothing=None):
    """Si le placebo changeait les tailles, il ne mesurerait plus le même portefeuille."""
    avant = _portefeuille(5)
    apres = EC._portefeuille_decale(avant, 24 * HEURE)
    assert [t for t, _, _ in apres] == [t + 24 * HEURE for t, _, _ in avant]
    assert [v for _, v, _ in apres] == [v for _, v, _ in avant]
    assert [d for _, _, d in apres] == [d for _, _, d in avant], (
        "coins et tailles doivent etre INCHANGES : c'est tout l'interet du null")


def test_un_maximum_REEL_indiscernable_du_placebo_est_declare_BRUIT(monkeypatch):
    """Le cas dangereux : +18 USD/jour réel quand le placebo fait aussi bien."""
    nets = iter([18.0, 2.0, 1.0] * 12)      # chaque scenario de placebo atteint 18.0

    def faux_run(portefeuille, panel, half, config, *, funding_rates=None, **kw):
        return {"net_usd_per_day": next(nets), "complete_days": 4,
                "days_utc": [20_261_113, 20_261_114, 20_261_115, 20_261_116]}

    monkeypatch.setattr(EC.replication, "run_replication", faux_run)
    # +18,5 reel contre 18,0 sous placebo : 0,5 USD/jour d'ecart sur 4 jours est SOUS le bruit
    # de mesure de l'ensemble (demi-largeur de l'IC 95 % ~ 1,06 USD/jour). La marge additive
    # existe exactement pour refuser ce faux positif.
    sortie = EC.borne_du_hasard_replication(
        {f"0x{i}": _portefeuille() for i in range(3)}, panel=None, half_spreads={},
        config=None, funding={}, min_snapshots=1, max_reel=18.5, n_scenarios=105,
        marge_usd=1.06)
    v = sortie["verdict"]
    assert v["max_hasard_p95"] == 18.0
    assert sortie["marge_usd"] == 1.06
    assert v["verdict"] == OS.VERDICT_BRUIT, "un sommet reel au niveau du placebo ne doit PAS passer"
    assert v["n_scenarios"] == 105, "le nombre d'essais doit etre porte par le verdict"
    assert len(sortie["scenarios"]) == len(EC.PLACEBO_DECALAGES_H)


def test_un_maximum_REEL_bien_au_dessus_du_placebo_est_declare_SIGNAL(monkeypatch):
    def faux_run(portefeuille, panel, half, config, *, funding_rates=None, **kw):
        return {"net_usd_per_day": 1.0, "complete_days": 4, "days_utc": [20_261_113]}

    monkeypatch.setattr(EC.replication, "run_replication", faux_run)
    sortie = EC.borne_du_hasard_replication(
        {f"0x{i}": _portefeuille() for i in range(3)}, panel=None, half_spreads={},
        config=None, funding={}, min_snapshots=1, max_reel=18.5, n_scenarios=105,
        marge_usd=1.06)
    assert sortie["verdict"]["verdict"] == OS.VERDICT_SIGNAL
    assert sortie["verdict"]["ecart_vs_p95"] == 17.5


def test_un_placebo_qui_ne_mesure_RIEN_est_dit_et_non_lisse(monkeypatch):
    """Un décalage qui sort de la fenêtre de prix ne doit pas disparaître du rapport."""
    def faux_run(portefeuille, panel, half, config, *, funding_rates=None, **kw):
        return {"status": "UNMEASURABLE", "net_usd_per_day": None, "complete_days": 0}

    monkeypatch.setattr(EC.replication, "run_replication", faux_run)
    sortie = EC.borne_du_hasard_replication(
        {"0xa": _portefeuille()}, panel=None, half_spreads={}, config=None, funding={},
        min_snapshots=1, max_reel=5.0, n_scenarios=10)
    assert all("raison" in sc for sc in sortie["scenarios"])
    # aucun maximum collecte => le verdict doit etre INSUFFISANT, jamais « signal »
    assert sortie["verdict"]["n_permutations"] == 0
    assert sortie["verdict"]["verdict"] != OS.VERDICT_SIGNAL
    assert sortie["verdict"]["verdict"] == OS.VERDICT_INSUFFISANT


def test_un_leader_sous_le_minimum_d_instantanes_n_entre_pas_dans_le_null(monkeypatch):
    appels: list[int] = []

    def faux_run(portefeuille, panel, half, config, *, funding_rates=None, **kw):
        appels.append(len(portefeuille))
        return {"net_usd_per_day": 1.0, "complete_days": 1, "days_utc": [20_261_113]}

    monkeypatch.setattr(EC.replication, "run_replication", faux_run)
    EC.borne_du_hasard_replication(
        {"0xriche": _portefeuille(60), "0xpauvre": _portefeuille(3)},
        panel=None, half_spreads={}, config=None, funding={}, min_snapshots=50,
        max_reel=1.0, n_scenarios=1)
    assert appels and all(n == 60 for n in appels), (
        "le null doit porter sur les MEMES leaders que la mesure reelle")


def test_le_correctif_se_lit_AVANT_le_tableau_par_leader():
    """Mettre la correction après les chiffres tentants équivaut à l'enterrer."""
    rapport = {
        "summary": {"leader_days": 10, "distinct_days": 5, "leaders_measured": 3,
                    "net_usd_per_day": -0.2, "interval_95": (-1.0, 0.5),
                    "net_bps_per_day_on_capital": -5.3, "share_positive_days": 0.4,
                    "funding_coverage": 1.0, "mean_cost_usd_per_day": {}},
        "inputs": {"comptes": 3, "comptes_simules": 3, "prix": "prix observés",
                   "coins_avec_ecart": 10, "coins_avec_funding": 10, "panel_points": 5000},
        "config": {"capital_usd": 350.0, "rebalance_ms": 3_600_000, "reaction_ms": 60_000,
                   "min_order_usd": 10.0, "taker_fee_bps": 4.5},
        "verdicts": [{"hypothesis": "h", "status": "MORE_DATA", "reason": "5 jours"}],
        "leaders": [{"compte": "0xa", "complete_days": 4, "net_usd_per_day": 18.85, "orders": 10,
                     "orders_refused_by_venue_minimum": 1, "turnover_per_day": 1.0,
                     "mean_gross_exposure": 0.9, "untradable": 0, "cost_usd_per_day": {}}],
        "selection_vs_hasard": {
            "null": "portefeuille exact confronte a un autre jour",
            "decalages_h": [-24, 24],
            "scenarios": [{"decalage_h": -24, "leaders": 3, "jours": 4, "max_usd_par_jour": 17.9,
                           "median_usd_par_jour": 1.0, "min_usd_par_jour": -3.0}],
            "verdict": {"max_reel": 18.85, "max_hasard_moyen": 16.0, "max_hasard_p95": 17.9,
                        "ecart_vs_p95": 0.95, "ratio": 1.05, "n_permutations": 2,
                        "n_scenarios": 105, "verdict": OS.VERDICT_BRUIT},
        },
        "caveats": [], "paper_read_only": True, "real_execution": False,
    }
    texte = EC.render_replication_report(rapport, {"experiment_id": "x", "corpus_sha256": "y" * 64,
                                                   "code_head": "abc123"})
    assert "Essais multiples" in texte
    assert texte.index("Essais multiples") < texte.index("Par leader"), (
        "la correction doit PRECEDER le tableau qui tente l'oeil")
    assert OS.VERDICT_BRUIT in texte
    assert "105 comptes" in texte


# ───────── 17/11 : LA CAPACITÉ, CONFRONTÉE AU VOLUME RÉELLEMENT RÉPLIQUÉ ─────────
#
# Mesure : volume répliqué 366 192 USD sur 99 coins ; 2,8 % sur des coins étroits (une minute
# médiane de marché échange moins que l'ordre), 0,6 % de capacité inconnue, 96,7 % mesurée
# suffisante. Le seuil de 1 × est indulgent : l'étude publie aussi 10 × et 100 ×, et le volume
# par coin, pour qu'un autre seuil se recalcule sans rejouer 45 minutes.
def test_la_capacite_est_agregee_sur_le_VOLUME_et_publiee_a_trois_seuils():
    par_leader = {
        "0xa": {"full": {"volume_usd_par_coin": {"BTC": 900.0, "PETIT": 100.0}}},
        "0xb": {"full": {"volume_usd_par_coin": {"BTC": 0.0, "MOYEN": 1_000.0}}},
        "0xc": {"full": {}},                                   # leader sans ordre : ne pese rien
    }
    capacite = {"coins": 3, "multiple_median": 5.0,
                "par_coin": {"BTC": {"multiple_de_l_ordre": 5_000.0},
                             "MOYEN": {"multiple_de_l_ordre": 5.0},
                             "PETIT": {"multiple_de_l_ordre": 0.5}}}
    r = EC.resumer_la_capacite(par_leader, capacite)
    assert r["volume_total_usd"] == 2_000.0
    assert r["coins_traites"] == 3
    assert r["part_du_volume_par_seuil"] == {
        "moins_de_1x": 0.05,          # PETIT seul
        "moins_de_10x": 0.55,         # PETIT + MOYEN
        "moins_de_100x": 0.55,
    }
    assert r["volume_usd_par_coin"] == {"BTC": 900.0, "MOYEN": 1_000.0, "PETIT": 100.0}
    assert "optimiste" in r["portee"]
