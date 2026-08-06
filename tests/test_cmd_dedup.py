"""[Bloc 8] Dedup des 2 CMD d'analyse : bloc d'environnement partage unique, plus de duplication."""
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _read(f): return open(os.path.join(ROOT, f), encoding="utf-8", errors="replace").read()
def test_shared_env_existe():
    assert os.path.exists(os.path.join(ROOT, "tools", "hyperlab_env.cmd"))
def test_les_deux_cmd_appellent_le_partage():
    for f in ("ANALYSER_BACKTESTS_REPLAYS.cmd", "ANALYSE_HISTORIQUE_COMPLETE.cmd"):
        assert "hyperlab_env.cmd" in _read(f)
def test_plus_de_bloc_duplique():
    dup = 'set "HL_ENABLE_MAINNET_EXECUTION=0"'
    for f in ("ANALYSER_BACKTESTS_REPLAYS.cmd", "ANALYSE_HISTORIQUE_COMPLETE.cmd"):
        assert _read(f).count(dup) == 0
