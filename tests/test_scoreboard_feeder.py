"""Jalon 1 — le scoreboard alimenté par le ledger SCELLÉ réel (vérité PnL, deny-by-default).

Les ledgers de test sont scellés par `ledger_integrity` (vraie chaîne de hash) et jugés par le
vrai `audit_paper_ledger` : on teste l'INTÉGRATION, pas un mock.
"""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.simulation import ledger_integrity as LI          # noqa: E402
from hl_observer.simulation import scoreboard_feeder as F          # noqa: E402
from hl_observer.simulation.paper_event import PaperEventType as ET  # noqa: E402

OPEN = ET.POSITION_OPENED.value
CLOSE = ET.POSITION_CLOSED.value


def _ev(eid, etype, **kw):
    base = {"event_id": eid, "event_type": etype, "timestamp_ms": 0}
    base.update(kw)
    return base


def _seal(raw):
    return list(LI.seal_chain(raw, session_id="S-test"))


def _episode(pid, coin, side, oid, cid, realized, strat, qty=1.0):
    refs = {"position_id": pid}
    if strat is not None:
        refs["strategy"] = strat
    return [
        _ev(oid, OPEN, coin=coin, side=side, quantity=qty, price=100.0, refs=dict(refs)),
        _ev(cid, CLOSE, coin=coin, side=side, quantity=qty, price=110.0,
            realized_pnl_usdc=realized, refs=dict(refs)),
    ]


def _par_strat(res):
    return {row.strategy: row for row in res.rows}


# --- cœur : ledger TRUSTED, PnL par stratégie, N = épisodes clos -------------
def test_ledger_trusted_regroupe_pnl_par_strategie_et_compte_les_episodes():
    raw = (
        _episode("p1", "BTC", "LONG", "o1", "c1", 10.0, "copy_vault")
        + _episode("p2", "BTC", "LONG", "o2", "c2", -4.0, "copy_vault")
        + _episode("p3", "ETH", "SHORT", "o3", "c3", 3.0, "lead_lag")
    )
    r = F.lignes_depuis_ledger(_seal(raw))
    assert r.status == "TRUSTED" and r.n_episodes_clos == 2
    by = _par_strat(r)
    assert set(by) == {"copy_vault"}

    assert by["copy_vault"].n_independent == 2          # 2 épisodes clos, pas 4 fills
    assert by["copy_vault"].pnl_usd == 6.0
    assert by["copy_vault"].profit_factor == round(10.0 / 4.0, 6)
    assert by["copy_vault"].hit_rate == 0.5
    assert by["copy_vault"].max_drawdown_usd == 4.0
    assert by["copy_vault"].expected_shortfall_usd == -4.0

    assert r.identite_couverture["n_episodes"] == 3
    assert r.identite_couverture["n_episodes_exclus_scope"] == 1
    assert r.identite_couverture["episodes_exclus_par_famille"] == {"lead_lag": 1}


def test_edge_couts_oos_forward_absents_du_ledger_restent_unmeasurable():
    raw = _episode("p1", "BTC", "LONG", "o1", "c1", 10.0, "copy_vault")
    r = F.lignes_depuis_ledger(_seal(raw))
    cv = _par_strat(r)["copy_vault"]
    # Le ledger ne porte NI edge brut NI bps de coût NI OOS/forward → net incalculable, jamais PROMOTE.
    assert cv.gross_edge_bps is None and cv.costs_bps is None and cv.net_bps is None
    assert cv.oos_net_bps is None and cv.forward_net_bps is None
    assert cv.verdict == "MORE_DATA"
    for champ in ("net_bps", "costs_bps", "gross_edge_bps", "oos_net_bps", "forward_net_bps"):
        assert champ in r.manques_globaux


def test_seule_copy_vault_est_listee_dans_le_scoreboard_economique():
    raw = _episode("p1", "BTC", "LONG", "o1", "c1", 10.0, "copy_vault")
    r = F.lignes_depuis_ledger(_seal(raw))
    by = _par_strat(r)
    assert set(by) == {"copy_vault"}


def test_strategie_attendue_hors_scope_refuse_le_scoreboard_entier():
    raw = _episode("p1", "BTC", "LONG", "o1", "c1", 10.0, "copy_vault")
    r = F.lignes_depuis_ledger(_seal(raw), strategies_attendues=("lead_lag",))
    assert r.status == "UNMEASURABLE"
    assert "DISABLED_BY_SCOPE" in (r.raison or "")
    assert r.n_episodes_clos == 0
    assert all(row.pnl_usd is None for row in r.rows)


def test_autorite_scope_absente_bloque_le_scoreboard(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "hl_observer.strategies.active_scope", None)
    raw = _episode("p1", "BTC", "LONG", "o1", "c1", 10.0, "copy_vault")
    r = F.lignes_depuis_ledger(_seal(raw))
    assert r.status == "UNMEASURABLE"
    assert "autorité active_scope indisponible" in (r.raison or "")
    assert r.n_episodes_clos == 0 and all(row.pnl_usd is None for row in r.rows)


# --- deny-by-default : un ledger contaminé ne fabrique aucun PnL ------------
def test_ledger_contamine_ne_produit_aucun_pnl():
    # CLOSE sans OPEN → l'audit contamine ; le feeder refuse tout PnL de stratégie.
    raw = [_ev("c1", CLOSE, coin="BTC", side="LONG", quantity=1.0, realized_pnl_usdc=5.0,
               refs={"position_id": "pX", "strategy": "copy_vault"})]
    r = F.lignes_depuis_ledger(_seal(raw))
    assert r.status != "TRUSTED" and r.n_episodes_clos == 0
    assert all(row.pnl_usd is None and row.net_bps is None for row in r.rows)
    assert all(row.verdict == "MORE_DATA" for row in r.rows)
    assert set(_par_strat(r)) == {"copy_vault"}
    assert "deny-by-default" in (r.raison or "")


# --- identité : tag stratégie absent rendu visible, pas caché ---------------
def test_strategie_absente_est_exclue_du_pnl_economique():
    raw = [
        _ev("o1", OPEN, coin="SOL", side="LONG", quantity=1.0, refs={"position_id": "p9"}),
        _ev("c1", CLOSE, coin="SOL", side="LONG", quantity=1.0, realized_pnl_usdc=2.0,
            refs={"position_id": "p9"}),
    ]
    r = F.lignes_depuis_ledger(_seal(raw))
    assert r.status == "TRUSTED"
    by = _par_strat(r)
    assert set(by) == {"copy_vault"}
    assert by["copy_vault"].pnl_usd is None
    assert r.n_episodes_clos == 0
    assert r.identite_couverture["episodes_exclus_par_famille"] == {"non_attribue": 1}


# --- indépendance : 2 round-trips sur le même coin sans position_id ---------
def test_deux_round_trips_meme_coin_sans_position_id_restent_independants():
    raw = [
        _ev("o1", OPEN, coin="BTC", side="LONG", quantity=1.0, price=100.0, refs={"strategy": "lead_lag"}),
        _ev("c1", CLOSE, coin="BTC", side="LONG", quantity=1.0, price=105.0,
            realized_pnl_usdc=5.0, refs={"strategy": "lead_lag"}),
        _ev("o2", OPEN, coin="BTC", side="LONG", quantity=1.0, price=106.0, refs={"strategy": "lead_lag"}),
        _ev("c2", CLOSE, coin="BTC", side="LONG", quantity=1.0, price=113.0,
            realized_pnl_usdc=7.0, refs={"strategy": "lead_lag"}),
    ]
    r = F.lignes_depuis_ledger(_seal(raw))
    assert r.status == "TRUSTED" and r.n_episodes_clos == 0
    assert _par_strat(r)["copy_vault"].pnl_usd is None
    assert r.identite_couverture["n_episodes_exclus_scope"] == 2
    assert r.identite_couverture["episodes_exclus_par_famille"] == {"lead_lag": 2}


# --- ROI : uniquement si un dénominateur est fourni -------------------------
def test_roi_utilise_les_denominateurs_fournis():
    raw = _episode("p1", "BTC", "LONG", "o1", "c1", 10.0, "copy_vault")
    r = F.lignes_depuis_ledger(_seal(raw), roi_denominateurs={"copy_vault": 200.0})
    assert _par_strat(r)["copy_vault"].roi == 0.05


def test_roi_unmeasurable_sans_denominateur():
    raw = _episode("p1", "BTC", "LONG", "o1", "c1", 10.0, "copy_vault")
    r = F.lignes_depuis_ledger(_seal(raw))
    assert _par_strat(r)["copy_vault"].roi is None


# --- câblage réel : lecture d'un ledger scellé sur disque -------------------
def test_depuis_fichier_ledger_lit_le_ledger_scelle(tmp_path):
    raw = _episode("p1", "BTC", "LONG", "o1", "c1", 9.0, "copy_vault")
    chemin = tmp_path / "ledger.jsonl"
    LI.write_chain_atomic(chemin, raw, session_id="S-file")
    r = F.depuis_fichier_ledger(chemin)
    assert r.status == "TRUSTED" and r.n_episodes_clos == 1
    assert _par_strat(r)["copy_vault"].pnl_usd == 9.0


def test_fichier_absent_ne_fabrique_aucun_pnl(tmp_path):
    r = F.depuis_fichier_ledger(tmp_path / "nexistepas.jsonl")
    assert r.status != "TRUSTED"
    assert all(row.pnl_usd is None and row.verdict == "MORE_DATA" for row in r.rows)


def test_to_dict_marque_paper_only_et_schema():
    d = F.lignes_depuis_ledger([]).to_dict()
    assert d["paper_only"] is True and d["real_execution"] is False
    assert d["schema_version"] == F.SCHEMA_VERSION
    assert isinstance(d["rows"], list) and isinstance(d["manques_globaux"], list)


# --- P1D : identité propagée jusqu'au scoreboard feed -----------------------
def test_identite_couverture_compte_les_niveaux():
    raw = (
        _episode("p1", "BTC", "LONG", "o1", "c1", 5.0, "copy_vault")     # position_id, pas d'episode_id
        + [
            _ev("o2", OPEN, coin="ETH", side="SHORT", quantity=1.0,
                refs={"strategy": "lead_lag", "position_id": "p2", "episode_id": "E:z"}),
            _ev("c2", CLOSE, coin="ETH", side="SHORT", quantity=1.0, realized_pnl_usdc=3.0,
                refs={"strategy": "lead_lag", "position_id": "p2", "episode_id": "E:z"}),
        ]
        + [
            _ev("o3", OPEN, coin="SOL", side="LONG", quantity=1.0, refs={"strategy": "copy_vault"}),
            _ev("c3", CLOSE, coin="SOL", side="LONG", quantity=1.0, realized_pnl_usdc=1.0,
                refs={"strategy": "copy_vault"}),
        ]
    )
    r = F.lignes_depuis_ledger(_seal(raw))
    assert r.status == "TRUSTED"
    cov = r.identite_couverture
    assert cov["n_episodes"] == 3
    assert cov["n_episode_id"] == 1          # E:z
    assert cov["n_position_id"] == 1         # p1 (position_id sans episode_id)
    assert cov["n_coin_side_fallback"] == 1  # SOL (ni episode_id ni position_id → ambigu)
    assert r.to_dict()["identite_couverture"]["n_episode_id"] == 1


def test_episode_id_present_est_compte_comme_identite_reelle():
    raw = [
        _ev("o1", OPEN, coin="BTC", side="LONG", quantity=1.0,
            refs={"strategy": "copy_vault", "episode_id": "E:a"}),
        _ev("c1", CLOSE, coin="BTC", side="LONG", quantity=1.0, realized_pnl_usdc=4.0,
            refs={"strategy": "copy_vault", "episode_id": "E:a"}),
    ]
    r = F.lignes_depuis_ledger(_seal(raw))
    assert r.identite_couverture["n_episode_id"] == 1
    assert _par_strat(r)["copy_vault"].n_independent == 1


# --- P2.3 : scoreboard RÉELLEMENT alimenté (mesures + porte de promotion) ----
def _ledger_n_episodes(strat, n, pnl=1.0):
    raw = []
    for i in range(n):
        pid = f"{strat}-p{i}"
        raw += [
            _ev(f"o{strat}{i}", OPEN, coin="BTC", side="LONG", quantity=1.0,
                refs={"strategy": strat, "position_id": pid}),
            _ev(f"c{strat}{i}", CLOSE, coin="BTC", side="LONG", quantity=1.0,
                realized_pnl_usdc=pnl, refs={"strategy": strat, "position_id": pid}),
        ]
    return raw


def test_sans_mesures_les_couts_restent_unmeasurable():
    raw = _episode("p1", "BTC", "LONG", "o1", "c1", 5.0, "copy_vault")
    r = F.lignes_depuis_ledger(_seal(raw))
    cv = _par_strat(r)["copy_vault"]
    assert cv.pnl_usd == 5.0 and cv.net_bps is None and cv.costs_bps is None


def test_scoreboard_alimente_calcule_net_et_promotion():
    from hl_observer.simulation.scoreboard_promotion import ScoreboardPromotionEvidence
    raw = _ledger_n_episodes("copy_vault", 25, pnl=2.0)      # 25 épisodes clos → n_independent=25
    mesures = {"copy_vault": {
        "gross_edge_bps": 25.0, "fees_bps": 1.0, "spread_bps": 2.0, "slippage_bps": 1.0,
        "latency_bps": 1.0, "capacity_usd": 5000.0, "fill_ratios": [1.0, 0.95],
        "latency_p50_ms": 100.0, "latency_p95_ms": 200.0, "oos_net_bps": 6.0,
        "forward_net_bps": 4.0, "roi_denominator_usd": 1000.0,
    }}
    evidence = {"copy_vault": ScoreboardPromotionEvidence(
        ledger_trusted=True, placebo_beaten=True, pbo_robuste=True, dsr_ok=True,
        lower_confidence_bound_bps=3.0, concentration=0.1, n_days=10, n_regimes=3, n_coins=2, min_coins=1,
    )}
    r = F.lignes_depuis_ledger(_seal(raw), mesures_par_strategie=mesures, evidence_par_strategie=evidence)
    cv = _par_strat(r)["copy_vault"]
    assert cv.net_bps == 20.0 and cv.capacity_usd == 5000.0 and cv.latency_p95_ms == 200.0
    assert r.promotions["copy_vault"]["verdict"] == "PROMOTE"     # PLOMBERIE (ledger synthétique)


def test_promotion_more_data_si_capacite_absente_des_mesures():
    from hl_observer.simulation.scoreboard_promotion import ScoreboardPromotionEvidence
    raw = _ledger_n_episodes("copy_vault", 25, pnl=2.0)
    mesures = {"copy_vault": {  # capacité OMISE
        "gross_edge_bps": 25.0, "fees_bps": 1.0, "spread_bps": 2.0, "slippage_bps": 1.0,
        "latency_bps": 1.0, "fill_ratios": [1.0], "latency_p50_ms": 100.0, "latency_p95_ms": 200.0,
        "oos_net_bps": 6.0, "forward_net_bps": 4.0,
    }}
    evidence = {"copy_vault": ScoreboardPromotionEvidence(
        ledger_trusted=True, placebo_beaten=True, pbo_robuste=True, dsr_ok=True,
        lower_confidence_bound_bps=3.0, concentration=0.1, n_days=10, n_regimes=3, n_coins=2, min_coins=1,
    )}
    r = F.lignes_depuis_ledger(_seal(raw), mesures_par_strategie=mesures, evidence_par_strategie=evidence)
    assert r.promotions["copy_vault"]["verdict"] == "MORE_DATA"
    assert "capacity_measured" in r.promotions["copy_vault"]["manquants"]
    assert r.to_dict()["promotions"]["copy_vault"]["verdict"] == "MORE_DATA"
