"""AUD-121 — UN SEUL moteur economique dans le chemin actif ; les moteurs legacy self-gated OFF.

Le chemin actif delegue toute l'economie a PaperEngine via cohort_paper_bridge (ECONOMIC_SOURCE
canonique). Les moteurs legacy (experimental/moteur_paper via experimental_paper_tick, exploratoire
via exploratory_paper_tick) NE tournent PAS par defaut : leurs ticks sont gates par un flag explicite.
Ce test rougit si un moteur legacy devenait actif par defaut ou si la source canonique unique disparaissait.
"""
from pathlib import Path

from hl_observer.experimental import cohort_paper_bridge as B

RACINE = Path(__file__).resolve().parents[1]


def test_source_economique_canonique_unique():
    assert B.ECONOMIC_SOURCE == "PAPER_ENGINE_CANONICAL"
    assert hasattr(B, "build_engine")


def test_les_ticks_legacy_sont_self_gated_off_par_defaut():
    for tool, flag in (("experimental_paper_tick.py", "HYPERSMART_EXPERIMENTAL_PAPER"),
                       ("exploratory_paper_tick.py", "HYPERSMART_EXPLORATORY_PAPER")):
        src = (RACINE / "tools" / tool).read_text(encoding="utf-8")
        assert flag in src, "%s: flag %s absent" % (tool, flag)
        assert ('environ.get("%s", "0")' % flag) in src, (
            "%s doit etre gate OFF par defaut (defaut '0') via %s" % (tool, flag))
