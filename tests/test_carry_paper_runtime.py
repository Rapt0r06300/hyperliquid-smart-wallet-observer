"""Carry HYPE paper v1 : refus motive sans inputs, verdict complet avec inputs MESURES,
peremption, et journal jsonl estampille session. Aucune conversion d'unite dans le module."""
from __future__ import annotations

import json

from hl_observer.funding.carry_paper_runtime import (
    ENV_ENABLED, JOURNAL_RELPATH, INPUTS_RELPATH, enabled, evaluer_et_journaliser,
)


def _lire_journal(root):
    path = root / JOURNAL_RELPATH
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_flag_defaut_off(monkeypatch):
    monkeypatch.delenv(ENV_ENABLED, raising=False)
    assert enabled() is False
    monkeypatch.setenv(ENV_ENABLED, "1")
    assert enabled() is True


def test_sans_inputs_refus_motive_et_journalise(tmp_path, monkeypatch):
    monkeypatch.delenv("HYPERSMART_SESSION_ID", raising=False)
    ligne = evaluer_et_journaliser(tmp_path, now_ms=10_000_000)
    assert ligne["decision"]["viable"] is False
    assert ligne["decision"]["motif"] == "INPUTS_SPOT_ABSENTS_NO_TRADE"
    assert ligne["real_execution"] is False and ligne["paper_only"] is True
    assert _lire_journal(tmp_path)[0]["decision"]["motif"] == "INPUTS_SPOT_ABSENTS_NO_TRADE"


def test_inputs_perimes_refuses(tmp_path):
    p = tmp_path / INPUTS_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"ts_ms": 1_000, "coin": "HYPE", "funding_bps_h": 1.0,
                             "base_bps": 0.0, "liquidite_spot_usd": 50_000.0}), encoding="utf-8")
    ligne = evaluer_et_journaliser(tmp_path, now_ms=1_000 + 901_000)   # 901 s > 900 s
    assert ligne["decision"]["motif"] == "INPUTS_SPOT_PERIMES_NO_TRADE"


def test_inputs_mesures_verdict_complet_avec_verrou(tmp_path, monkeypatch):
    """Avec des entrees completes (dont le verrou T2b), le module rend le verdict du moteur
    delta_neutral_carry — on verifie qu'il TRANSMET sans convertir ni adoucir."""
    monkeypatch.setenv("HYPERSMART_SESSION_ID", "S-CARRY")
    p = tmp_path / INPUTS_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    inputs = {"ts_ms": 100_000_000, "coin": "HYPE", "funding_bps_h": 1.2, "base_bps": 2.0,
              "liquidite_spot_usd": 80_000.0, "maker": True,
              "levier_max": 10.0, "marge_ratio": 1.06, "pire_hausse_observee": 0.956}
    p.write_text(json.dumps(inputs), encoding="utf-8")
    ligne = evaluer_et_journaliser(tmp_path, now_ms=100_060_000)   # 60 s: frais
    d = ligne["decision"]
    assert ligne["session_id"] == "S-CARRY"
    assert ligne["inputs_age_s"] == 60.0
    assert d["coin"] == "HYPE" and d["real_execution"] is False
    assert d["funding_bps_h"] == 1.2                       # transmis TEL QUEL (piege d'unite)
    assert isinstance(d["viable"], bool) and d["motif"]    # verdict rendu, jamais silencieux


# ---------- ETAPE 2 (cablage opt-in) : ouvrir REELLEMENT la position paper ----------

_INPUTS_VIABLES = {"ts_ms": 100_000_000, "coin": "HYPE", "funding_bps_h": 0.125, "base_bps": -0.68,
                   "liquidite_spot_usd": 200_000.0, "maker": True, "levier_max": 10.0,
                   "marge_ratio": 0.5, "pire_hausse_observee": 0.29, "levier_utilise": 2.0}


def _ecrire_inputs(root, inputs):
    p = root / INPUTS_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(inputs), encoding="utf-8")


def test_etape2_off_par_defaut_aucune_ouverture(tmp_path, monkeypatch):
    monkeypatch.delenv("HYPERSMART_CARRY_ETAPE2", raising=False)
    _ecrire_inputs(tmp_path, _INPUTS_VIABLES)
    ligne = evaluer_et_journaliser(tmp_path, now_ms=100_060_000)
    assert ligne["etape2"] is None                                  # flag OFF -> on n'ouvre rien
    assert not (tmp_path / "runtime" / "data" / "carry_paper_positions.json").exists()


def test_etape2_on_ouvre_la_position_et_ecrit_le_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERSMART_CARRY_ETAPE2", "1")
    _ecrire_inputs(tmp_path, _INPUTS_VIABLES)
    ligne = evaluer_et_journaliser(tmp_path, now_ms=100_060_000)
    assert ligne["decision"]["viable"] is True                      # HYPE viable a 2x
    assert ligne["etape2"]["ouvert"] is True                        # etape 2 a OUVERT
    assert ligne["real_execution"] is False                         # ... mais JAMAIS d'ordre reel
    assert (tmp_path / "runtime" / "data" / "carry_paper_positions.json").exists()
    assert (tmp_path / "runtime" / "data" / "carry_paper_ledger.jsonl").exists()


def test_etape2_erreur_ne_casse_pas_la_decision(tmp_path, monkeypatch):
    # inputs viables mais on force une erreur interne -> la decision reste journalisee, etape2 = erreur
    monkeypatch.setenv("HYPERSMART_CARRY_ETAPE2", "1")
    _ecrire_inputs(tmp_path, _INPUTS_VIABLES)
    import hl_observer.funding.carry_positions_store as store
    monkeypatch.setattr(store, "tick_sur_disque",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    ligne = evaluer_et_journaliser(tmp_path, now_ms=100_060_000)
    assert ligne["decision"]["viable"] is True                      # la decision survit
    assert ligne["etape2"]["erreur"] == "etape2_indisponible"       # l'erreur est capturee, pas propagee
