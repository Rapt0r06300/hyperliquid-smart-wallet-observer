"""Étape 1 du cliquet labo->moteur : écriture du champion gelé (additif, fail-soft)."""
from __future__ import annotations

import json

from hl_observer.backtesting.copy_vault_local_lab import (
    CHEMIN_CHAMPION_DEPLOYE,
    _ecrire_champion_deploye,
    charger_champion_deploye,
    seuil_overshoot_champion,
)
from hl_observer.copy_mode.wallet_mirror_runtime import (
    MirrorRuntimeConfig,
    mirror_candidate_from_delta,
)
from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.signals.leader_delta import LeaderDelta


def _best():
    return {
        "candidate_id": "cand-123",
        "candidate": {"overshoot_seuil_bps": 100.0, "daily_profit_lock_usd": 500.0},
        "score_usd_per_active_day": "12.5",
        "train": {"daily_mean_net_pnl_usd": 7.25},
        "trial_number": 42,
    }


def test_ecrit_le_champion_avec_overshoot_et_garde_paper(tmp_path):
    cible = _ecrire_champion_deploye(tmp_path, _best(), extra={"engine_source_sha256": "abc"})
    assert cible == tmp_path.joinpath(*CHEMIN_CHAMPION_DEPLOYE)
    data = json.loads(cible.read_text(encoding="utf-8"))
    assert data["candidate_id"] == "cand-123"
    assert data["overshoot_seuil_bps"] == 100.0
    assert data["params"]["daily_profit_lock_usd"] == 500.0
    # garde-fous paper : jamais d'exécution réelle, jamais appliqué sans opt-in
    assert data["paper_read_only"] is True
    assert data["real_execution"] is False
    assert data["applique_par_defaut"] is False
    assert data["engine_source_sha256"] == "abc"


def test_fail_soft_si_best_invalide(tmp_path):
    assert _ecrire_champion_deploye(tmp_path, {"candidate_id": "x"}) is None  # pas de candidate
    assert _ecrire_champion_deploye(tmp_path, "pas un mapping") is None
    # aucun fichier écrit
    assert not tmp_path.joinpath(*CHEMIN_CHAMPION_DEPLOYE).exists()


def test_loader_respecte_opt_in(tmp_path, monkeypatch):
    _ecrire_champion_deploye(tmp_path, _best())
    # sans opt-in -> rien (garde-fou : pas d'application sans décision humaine)
    monkeypatch.delenv("HL_APPLY_CHAMPION", raising=False)
    assert charger_champion_deploye(tmp_path) is None
    assert seuil_overshoot_champion(tmp_path) is None
    # avec opt-in -> champion lu, seuil overshoot renvoyé
    monkeypatch.setenv("HL_APPLY_CHAMPION", "1")
    assert charger_champion_deploye(tmp_path)["candidate_id"] == "cand-123"
    assert seuil_overshoot_champion(tmp_path) == 100.0


def test_seuil_off_quand_valeur_grande(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_APPLY_CHAMPION", "1")
    best = _best()
    best["candidate"]["overshoot_seuil_bps"] = 1_000_000.0  # valeur « off »
    _ecrire_champion_deploye(tmp_path, best)
    assert seuil_overshoot_champion(tmp_path) is None


def _delta_entree():
    return LeaderDelta(
        delta_id="d1", wallet="0xABC", coin="BTC", action=LifecycleAction.OPEN_LONG,
        previous_size=0.0, current_size=1.0, delta_size=1.0, observed_at_ms=2000,
        leader_event_time_ms=2000, source="test", confidence=0.9,
    )


def test_porte_overshoot_bloque_la_copie():
    cfg = MirrorRuntimeConfig(min_wallet_score=0.0, min_copyability_score=0.0, overshoot_seuil_bps=100.0)
    base = dict(delta=_delta_entree(), leader_price=100.0, observed_time_ms=2000,
                wallet_score=1.0, copyability_score=1.0, config=cfg)
    # overshoot 150 >= seuil 100 -> bloqué
    bloque = mirror_candidate_from_delta(**base, overshoot_bps=150.0)
    assert "MIRROR_OVERSHOOT_BLOCKED" in bloque.reason_codes
    # overshoot 40 < seuil -> pas bloqué ; overshoot absent -> pas bloqué
    assert "MIRROR_OVERSHOOT_BLOCKED" not in mirror_candidate_from_delta(**base, overshoot_bps=40.0).reason_codes
    assert "MIRROR_OVERSHOOT_BLOCKED" not in mirror_candidate_from_delta(**base).reason_codes
    # seuil None (porte off) -> jamais bloqué même avec gros overshoot
    cfg_off = MirrorRuntimeConfig(min_wallet_score=0.0, min_copyability_score=0.0)
    sans = mirror_candidate_from_delta(delta=_delta_entree(), leader_price=100.0, observed_time_ms=2000,
                                       wallet_score=1.0, copyability_score=1.0, config=cfg_off, overshoot_bps=999.0)
    assert "MIRROR_OVERSHOOT_BLOCKED" not in sans.reason_codes


def test_ecriture_atomique_remplace_ancien(tmp_path):
    _ecrire_champion_deploye(tmp_path, _best())
    best2 = _best()
    best2["candidate_id"] = "cand-999"
    _ecrire_champion_deploye(tmp_path, best2)
    data = json.loads(tmp_path.joinpath(*CHEMIN_CHAMPION_DEPLOYE).read_text(encoding="utf-8"))
    assert data["candidate_id"] == "cand-999"
    # pas de .tmp résiduel
    assert not any(p.suffix == ".tmp" for p in tmp_path.joinpath("runtime").iterdir())
