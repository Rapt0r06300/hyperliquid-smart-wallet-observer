"""IA mémoire incassable: survit au restart, dédupe, checkpoints best-only."""

from __future__ import annotations

from hl_observer.ml.memory_store import IAMemory


def test_memory_survives_reopen_simulating_server_restart(tmp_path):
    db = str(tmp_path / "ia.sqlite3")
    m = IAMemory(db)
    assert m.add_sample("d1", 1000, "LIVE", {"edge": 40}, 0.5) is True
    assert m.add_sample("d2", 1100, "SHADOW_REFUSED", {"edge": 12}, -0.3) is True
    assert m.sample_count() == 2
    del m  # ferme la connexion = simule l'arrêt du serveur
    # rouvre depuis le disque: la mémoire est intacte
    m2 = IAMemory(db)
    assert m2.sample_count() == 2


def test_samples_are_deduplicated():
    import tempfile, os
    db = os.path.join(tempfile.mkdtemp(), "ia.sqlite3")
    m = IAMemory(db)
    assert m.add_sample("same", 1, "LIVE", {"a": 1}, 0.1) is True
    assert m.add_sample("same", 2, "LIVE", {"a": 2}, 0.9) is False  # même decision_id ignoré
    assert m.sample_count() == 1


def test_checkpoints_promote_only_when_better(tmp_path):
    m = IAMemory(str(tmp_path / "ia.sqlite3"))
    r1 = m.save_checkpoint({"w": [1, 2]}, metric=0.60)
    assert r1["promoted"] is True and r1["version"] == 1
    r2 = m.save_checkpoint({"w": [1, 3]}, metric=0.55)   # pire → pas promu
    assert r2["promoted"] is False
    active = m.active_checkpoint()
    assert active["version"] == 1 and active["metric"] == 0.60  # l'ancien reste actif
    r3 = m.save_checkpoint({"w": [2, 4]}, metric=0.70)   # meilleur → promu
    assert r3["promoted"] is True
    assert m.active_checkpoint()["version"] == 3
    assert m.checkpoint_count() == 3  # historique conservé (jamais de régression)


def test_predictions_recorded_for_shadow_comparison(tmp_path):
    m = IAMemory(str(tmp_path / "ia.sqlite3"))
    m.record_prediction("d1", 1000, predicted=0.8, realized=None)   # prédiction en attente
    m.record_prediction("d1", 1000, predicted=0.8, realized=0.5)    # résultat connu plus tard
    # pas d'exception = OK; le store accumule prédiction vs réel pour l'audit IA
