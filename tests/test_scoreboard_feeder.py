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
    assert r.status == "TRUSTED" and r.n_episodes_clos == 3
    by = _par_strat(r)

    assert by["copy_vault"].n_independent == 2          # 2 épisodes clos, pas 4 fills
    assert by["copy_vault"].pnl_usd == 6.0
    assert by["copy_vault"].profit_factor == round(10.0 / 4.0, 6)
    assert by["copy_vault"].hit_rate == 0.5
    assert by["copy_vault"].max_drawdown_usd == 4.0
    assert by["copy_vault"].expected_shortfall_usd == -4.0

    assert by["lead_lag"].n_independent == 1 and by["lead_lag"].pnl_usd == 3.0
    assert by["lead_lag"].profit_factor is None          # que des gains → PF non défini


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


def test_familles_actives_sans_episode_sont_listees_more_data():
    raw = _episode("p1", "BTC", "LONG", "o1", "c1", 10.0, "copy_vault")
    r = F.lignes_depuis_ledger(_seal(raw))
    by = _par_strat(r)
    # Les 3 familles ACTIVES apparaissent, même celles sans donnée (absence rendue explicite).
    assert {"copy_vault", "lead_lag", "cross_venue_dislocation"} <= set(by)
    assert by["cross_venue_dislocation"].pnl_usd is None
    assert by["cross_venue_dislocation"].n_independent is None
    assert by["cross_venue_dislocation"].verdict == "MORE_DATA"


# --- deny-by-default : un ledger contaminé ne fabrique aucun PnL ------------
def test_ledger_contamine_ne_produit_aucun_pnl():
    # CLOSE sans OPEN → l'audit contamine ; le feeder refuse tout PnL de stratégie.
    raw = [_ev("c1", CLOSE, coin="BTC", side="LONG", quantity=1.0, realized_pnl_usdc=5.0,
               refs={"position_id": "pX", "strategy": "copy_vault"})]
    r = F.lignes_depuis_ledger(_seal(raw))
    assert r.status != "TRUSTED" and r.n_episodes_clos == 0
    assert all(row.pnl_usd is None and row.net_bps is None for row in r.rows)
    assert all(row.verdict == "MORE_DATA" for row in r.rows)
    assert {"copy_vault", "lead_lag", "cross_venue_dislocation"} <= set(_par_strat(r))
    assert "deny-by-default" in (r.raison or "")


# --- identité : tag stratégie absent rendu visible, pas caché ---------------
def test_strategie_absente_est_rendue_visible():
    raw = [
        _ev("o1", OPEN, coin="SOL", side="LONG", quantity=1.0, refs={"position_id": "p9"}),
        _ev("c1", CLOSE, coin="SOL", side="LONG", quantity=1.0, realized_pnl_usdc=2.0,
            refs={"position_id": "p9"}),
    ]
    r = F.lignes_depuis_ledger(_seal(raw))
    assert r.status == "TRUSTED"
    by = _par_strat(r)
    assert F.STRAT_ABSENTE in by
    assert by[F.STRAT_ABSENTE].pnl_usd == 2.0 and by[F.STRAT_ABSENTE].n_independent == 1


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
    assert r.status == "TRUSTED" and r.n_episodes_clos == 2   # PAS 1 épisode fusionné
    ll = _par_strat(r)["lead_lag"]
    assert ll.n_independent == 2 and ll.pnl_usd == 12.0


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
