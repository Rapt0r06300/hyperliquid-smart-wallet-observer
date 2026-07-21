"""ARBITRAGE DE DISLOCATION paper v1 (21/07) — les portes dures avant tout.

L'edge est positif A L'ENTREE par construction (35 bps d'ecart >= 22 de couts + 13 de
marge). Deny-by-default : mesure vieille (>15 min) = pas de decision ; 2 positions max ;
le realise part dans LE MEME ledger que le carry -> PnL unifie sans code de plus.
"""
from __future__ import annotations

import json
from pathlib import Path

from hl_observer.funding.arb_dislocation_paper import (
    COUT_AR_BPS, MAX_POSITIONS, NOTIONAL_USD, SEUIL_OUVERTURE_BPS, tick)


def _venue(root: Path, rows):
    p = root / "runtime" / "data" / "dispersion_venues.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _ledger_rows(root: Path):
    p = root / "runtime" / "data" / "carry_paper_ledger.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_ouverture_seulement_au_dela_de_35_bps_et_2_positions_max(tmp_path):
    _venue(tmp_path, [
        {"ts": 1000.0, "coin": "BTC", "ecart_prix_bps": 40.0},
        {"ts": 1000.0, "coin": "ETH", "ecart_prix_bps": -50.0},
        {"ts": 1000.0, "coin": "SOL", "ecart_prix_bps": 60.0},    # 3e : refusee (max 2)
        {"ts": 1000.0, "coin": "XPL", "ecart_prix_bps": 20.0},    # sous le seuil
    ])
    evts = tick(tmp_path, now=1010.0, session_id="S-TEST")
    opens = [e for e in evts if e["type"] == "OPEN"]
    assert len(opens) == MAX_POSITIONS
    assert {e["coin"] for e in opens} <= {"BTC", "ETH", "SOL"}
    assert all(r.get("real_execution") is False for r in _ledger_rows(tmp_path))


def test_mesure_perimee_aucune_decision_deny_by_default(tmp_path):
    _venue(tmp_path, [{"ts": 1000.0, "coin": "BTC", "ecart_prix_bps": 80.0}])
    assert tick(tmp_path, now=1000.0 + 1200.0) == []      # 20 min > 15 min de fraicheur


def test_convergence_capturee_le_realise_paie_les_couts_et_va_au_ledger_unifie(tmp_path):
    _venue(tmp_path, [{"ts": 1000.0, "coin": "BTC", "ecart_prix_bps": 40.0}])
    tick(tmp_path, now=1010.0, session_id="S-TEST")
    _venue(tmp_path, [{"ts": 2000.0, "coin": "BTC", "ecart_prix_bps": 2.0}])   # convergee
    evts = tick(tmp_path, now=2010.0, session_id="S-TEST")
    close = next(e for e in evts if e["type"] == "CLOSE")
    # capture 40->2 = 38 bps - 22 de couts = 16 bps x 50$ = +0.08 $
    assert abs(close["realized"] - (38.0 - COUT_AR_BPS) / 1e4 * NOTIONAL_USD) < 1e-9
    rows = _ledger_rows(tmp_path)
    fermeture = next(r for r in rows if r.get("kind") == "CLOSE")
    assert fermeture["strategie"] == "arbitrage" and fermeture["session_id"] == "S-TEST"
    assert fermeture["mode"] == "LIVE", "sans mode, le resume unifie FILTRE la ligne (PnL rate)"
    # LA PREUVE du PnL unifie : le resume carry compte le realise arbitrage
    from hl_observer.funding.carry_positions_store import resume_depuis_ledger
    r = resume_depuis_ledger(tmp_path, session_id="S-TEST")
    assert abs(r["realized_net_pnl_usdc_session"] - close["realized"]) < 1e-9
    assert fermeture["reason"] == "ARB_CONVERGENCE_CAPTUREE"


def test_age_max_sans_convergence_ferme_et_paie_ses_couts_honnetement(tmp_path):
    _venue(tmp_path, [{"ts": 1000.0, "coin": "BTC", "ecart_prix_bps": 40.0}])
    tick(tmp_path, now=1010.0, session_id="S-TEST")
    # 5 h plus tard, mesure fraiche au meme ecart : capture 0 - couts = perte assumee
    _venue(tmp_path, [{"ts": 19000.0, "coin": "BTC", "ecart_prix_bps": 40.0}])
    evts = tick(tmp_path, now=19010.0, session_id="S-TEST")
    close = next(e for e in evts if e["type"] == "CLOSE")
    assert close["realized"] < 0, "pas de convergence = les couts sont PAYES, jamais caches"


def test_le_cablage_lanceur_et_runtime_existe():
    lanceur = open("LANCER_HYPERSMART.cmd", encoding="utf-8", errors="replace").read()
    runtime = open("src/hl_observer/funding/carry_paper_runtime.py", encoding="utf-8").read()
    assert 'HYPERSMART_ARB_DISLOCATION_PAPER=1' in lanceur
    assert "arb_dislocation_paper import tick" in runtime
