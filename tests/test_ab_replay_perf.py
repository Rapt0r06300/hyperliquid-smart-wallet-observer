"""LE REPLAY A/B — vitesse ET justesse. Les deux ont ete corrigees le 2026-07-19.

CE QUI N'ALLAIT PAS. `_evaluate_arm` faisait, POUR CHAQUE candidat, une boucle sur TOUS les
marks du coin afin de nourrir l'estimateur de volatilite.

  * VITESSE : O(candidats x marks). Sur les vraies donnees (331 366 candidats, 109 192 marks),
    le replay tournait plus de 5 minutes sans rendre un resultat. Notre seule mesure neuve
    etait, de fait, inutilisable.

  * MESURE — et c'est le plus grave : le meme mark etait re-enregistre a chaque candidat. Sur
    un coin a 1 000 candidats, chaque prix entrait 1 000 fois dans l'estimateur. Une volatilite
    calculee sur des doublons n'est pas une volatilite ; et c'est elle qui pilote les barrieres
    SL/TP du bras B. On comparait donc deux bras dont l'un etait regle par un chiffre fausse.

Une optimisation qui change un resultat n'est pas une optimisation, c'est un bug. Ces tests
verrouillent les deux proprietes : le prix n'entre qu'UNE fois, et le PnL ne bouge pas.
"""
from __future__ import annotations

import time
from pathlib import Path

from hl_observer.backtesting.ab_flag_replay import (
    SLTPConfig,
    build_analysis_cache_key,
    load_cached_report,
    marks_by_coin,
    net_baseline_seul,
    run_ab_replay,
    simulate_exit_on_path,
    write_cached_report,
)


def _marks(coin: str, n: int, t0: float = 1000.0, px: float = 100.0) -> list[dict]:
    return [{"coin": coin, "ts": t0 + i * 60.0, "mid": px * (1.0 + 0.0001 * (i % 7 - 3))}
            for i in range(n)]


# ═══════════ 22/07 : le raccourci du CRIBLE doit donner EXACTEMENT le bras A ═══════════

def test_net_baseline_seul_EGALE_le_bras_A_de_run_ab_replay():
    """« Améliore notre façon de faire » — le crible ne lit que le net du bras A. `net_baseline_seul`
    le calcule sans le bras B / vetos / estimateur (plus rapide). Une optimisation qui CHANGE un
    résultat serait un bug : on VERROUILLE l'égalité au centime, sur données variées."""
    import random
    rng = random.Random(1234)
    marks: list[dict] = []
    for coin, px in (("BTC", 100.0), ("ETH", 50.0), ("SOL", 12.0), ("ARB", 3.0)):
        base = _marks(coin, 300, t0=1000.0, px=px)
        for r in base:                                   # un peu de vraie amplitude -> vrais exits
            r["mid"] *= (1.0 + 0.01 * rng.uniform(-1, 1))
        marks += base
    cands: list[dict] = []
    for _i in range(120):
        coin, px = rng.choice([("BTC", 100.0), ("ETH", 50.0), ("SOL", 12.0), ("ARB", 3.0)])
        cands.append({"coin": coin, "direction": rng.choice(["LONG", "SHORT"]),
                      "current_mid": px * (1.0 + 0.002 * rng.uniform(-1, 1)),
                      "recorded_at": 1000.0 + rng.uniform(0, 15000.0),
                      "leader_notional_usdt": rng.choice([0, 50.0, 200.0])})
    for cfg in (SLTPConfig(stop_loss_bps=40.0, take_profit_bps=70.0),
                SLTPConfig(stop_loss_bps=20.0, take_profit_bps=150.0),
                SLTPConfig(stop_loss_bps=90.0, take_profit_bps=100.0)):
        for h in (30.0, 120.0, 240.0):
            plein = run_ab_replay(cands, marks, base_config=cfg, horizon_min=h)["arm_a"]
            rapide = net_baseline_seul(cands, marks, base_config=cfg, horizon_min=h)["arm_a"]
            # rapport COMPLET identique (net, profit factor, win rate, drawdown, comptes) — pas juste
            # le net : la vectorisation sert AUSSI l'évaluation complète, qui lit PF et drawdown.
            assert rapide == plein, (
                f"cfg={cfg} h={h} :\n  rapide {rapide}\n  bras A {plein}"
            )


def test_net_baseline_seul_accepte_un_index_marks_deja_construit():
    """Le crible réutilise le MÊME index marks pour 5 640 configs -> on ne le reconstruit pas."""
    marks = _marks("BTC", 200)
    idx = marks_by_coin(marks)
    cfg = SLTPConfig(stop_loss_bps=40.0, take_profit_bps=70.0)
    cands = [{"coin": "BTC", "direction": "LONG", "current_mid": 100.0, "recorded_at": 1100.0}]
    via_index = net_baseline_seul(cands, idx, base_config=cfg, horizon_min=120.0)
    via_brut = net_baseline_seul(cands, marks, base_config=cfg, horizon_min=120.0)
    assert via_index == via_brut


def test_replay_peut_comparer_a_notionnel_constant():
    marks = _marks("BTC", 200)
    candidates = _cands("BTC", 4)
    small = [dict(candidate, leader_notional_usdt=50.0) for candidate in candidates]
    huge = [dict(candidate, leader_notional_usdt=50_000.0) for candidate in candidates]

    small_report = run_ab_replay(small, marks, fixed_notional_usd=50.0)
    huge_report = run_ab_replay(huge, marks, fixed_notional_usd=50.0)

    assert small_report["comparison_notional_usd"] == 50.0
    assert small_report["arm_a"] == huge_report["arm_a"]
    assert small_report["arm_b"] == huge_report["arm_b"]


def test_cache_exact_est_invalide_si_une_source_change(tmp_path: Path):
    candidates = tmp_path / "candidates.jsonl"
    marks = tmp_path / "marks.jsonl"
    candidates.write_text('{"coin":"BTC"}\n', encoding="utf-8")
    marks.write_text('{"coin":"BTC","mid":100}\n', encoding="utf-8")
    key_before = build_analysis_cache_key(
        candidates,
        marks,
        horizon_min=240.0,
        fixed_notional_usd=50.0,
    )
    cache = tmp_path / "cache.json"
    report = {"arm_a": {"trades": 1}}
    write_cached_report(cache, key_before, report)

    assert load_cached_report(cache, key_before) == report

    candidates.write_text('{"coin":"BTC"}\n{"coin":"ETH"}\n', encoding="utf-8")
    key_after = build_analysis_cache_key(
        candidates,
        marks,
        horizon_min=240.0,
        fixed_notional_usd=50.0,
    )
    assert key_after != key_before
    assert load_cached_report(cache, key_after) is None


def _cands(coin: str, n: int, t0: float = 1000.0) -> list[dict]:
    return [{"coin": coin, "direction": "LONG" if i % 2 == 0 else "SHORT",
             "current_mid": 100.0, "recorded_at": t0 + i * 60.0,
             "edge_remaining_bps": 25.0, "leader_notional_usdt": 50.0} for i in range(n)]


# ------------------------------------------------------------------ justesse

def test_la_fenetre_future_est_exacte():
    """La recherche binaire doit rendre EXACTEMENT les marks de ]entree, entree+horizon]."""
    chemin = [(float(t), 100.0 + t) for t in range(0, 100)]
    pnl = simulate_exit_on_path(side="LONG", entry_price=100.0, path=chemin, entry_ts=10.0,
                                config=SLTPConfig(stop_loss_bps=1e9, take_profit_bps=1e9),
                                horizon_min=0.5, cost_bps=0.0, notional_usd=100.0)
    # horizon 0,5 min = 30 s -> dernier mark retenu a t=40 -> prix 140
    assert pnl is not None
    assert round(pnl, 6) == round(100.0 * (140.0 - 100.0) / 100.0, 6)


def test_un_candidat_sans_futur_est_NON_MESURABLE():
    """Deny-by-default : sans prix APRES, on ne fabrique pas un PnL."""
    chemin = [(float(t), 100.0) for t in range(0, 10)]
    assert simulate_exit_on_path(side="LONG", entry_price=100.0, path=chemin, entry_ts=50.0,
                                 config=SLTPConfig(), horizon_min=30.0, cost_bps=0.0) is None


def test_chemin_vide_ou_prix_absurde():
    assert simulate_exit_on_path(side="LONG", entry_price=100.0, path=[], entry_ts=1.0,
                                 config=SLTPConfig()) is None
    assert simulate_exit_on_path(side="LONG", entry_price=0.0, path=[(1.0, 2.0)], entry_ts=0.0,
                                 config=SLTPConfig()) is None


def test_chaque_mark_n_entre_QU_UNE_FOIS_dans_l_estimateur(monkeypatch):
    """LE BUG DE MESURE. Avant : 1 mark x N candidats. Maintenant : 1 mark, 1 fois."""
    vus = []
    import hl_observer.paper_trading.vol_adjusted_barriers as vab

    class Espion(vab.MidVolEstimator):
        def record(self, coin, mid, ts=None):  # noqa: D102
            vus.append((coin, round(float(mid), 6), float(ts or 0)))
            return super().record(coin, mid, ts=ts)

    monkeypatch.setattr(vab, "MidVolEstimator", Espion)
    run_ab_replay(_cands("BTC", 40), _marks("BTC", 60),
                  arm_b_env={"HYPERSMART_V26_VOL_BARRIERS": "1"})
    assert vus, "l'estimateur n'a jamais ete alimente"
    # `run_ab_replay` evalue DEUX bras, chacun avec son estimateur ISOLE (aucune fuite d'etat
    # entre A et B). Chaque mark doit donc etre vu EXACTEMENT deux fois : une par bras.
    # Au-dela, ce sont des doublons DANS un bras -- le bug qu'on vient de corriger.
    from collections import Counter
    par_mark = Counter(vus)
    pire = max(par_mark.values())
    assert pire == 2, (
        f"un mark est enregistre {pire} fois (attendu : 2, une par bras). "
        "Au-dela, la volatilite "
        "est calculee sur des DOUBLONS -- et c'est elle qui regle les barrieres SL/TP du bras B."
    )


def test_le_resultat_ne_depend_PAS_de_l_ordre_des_candidats():
    """Le replay doit etre DETERMINISTE : melanger l'ordre d'entree ne change rien, puisqu'on
    trie chronologiquement. Sans ce tri, l'estimateur recevait des prix dans le desordre --
    c'est-a-dire qu'il « savait » des choses hors de leur instant."""
    c, mk = _cands("ETH", 30), _marks("ETH", 50)
    r1 = run_ab_replay(list(c), mk)
    r2 = run_ab_replay(list(reversed(c)), mk)
    assert r1["arm_a"]["net_total_usd"] == r2["arm_a"]["net_total_usd"]
    assert r1["arm_b"]["net_total_usd"] == r2["arm_b"]["net_total_usd"]


# ------------------------------------------------------------------ vitesse

def test_le_replay_tient_l_echelle():
    """GARDE-FOU DE COMPLEXITE. 3 000 candidats x 4 000 marks = 12 M de paires si l'on repart
    en O(n x m). Avec curseur + bisect, c'est lineaire et ca doit passer en quelques secondes.
    Si ce test devient lent, quelqu'un a reintroduit un balayage complet."""
    debut = time.time()
    r = run_ab_replay(_cands("SOL", 3000), _marks("SOL", 4000))
    duree = time.time() - debut
    assert r["arm_a"]["trades"] > 0
    assert duree < 20.0, (
        f"le replay met {duree:.1f} s sur 3 000 candidats x 4 000 marks : "
        "la complexite est repartie "
        "en quadratique. Sur les vraies donnees (331 k x 109 k) il ne rendra JAMAIS de "
        "resultat."
    )
