"""[AUD-222] Le CMD lance bien la SUITE d'analyse historique (historical_analysis_suite), avec le
meme Python portable, en PAPER STRICT, apres bootstrap portable_env. La preuve PROCESSUS Windows
(double-clic) reste un artefact CI windows-latest ; ici on prouve le CABLAGE + l'entrypoint reel."""
from __future__ import annotations

from pathlib import Path

from hl_observer.ops import historical_analysis_suite as HAS

RACINE = Path(__file__).resolve().parents[1]
CMD = RACINE / "ANALYSE_HISTORIQUE_COMPLETE.cmd"


def test_entrypoint_suite_runnable():
    args = HAS.build_parser().parse_args(["--root", ".", "--full"])
    assert args.root == "." and args.full is True
    assert callable(HAS.main) and callable(HAS.run_suite)


def test_le_cmd_lance_la_suite_apres_portable_env_en_paper_strict():
    assert CMD.is_file(), "le lanceur ANALYSE_HISTORIQUE_COMPLETE.cmd doit exister"
    txt = CMD.read_text(encoding="utf-8", errors="ignore")
    i_env = txt.find("portable_env.cmd")
    i_suite = txt.find("-m hl_observer.ops.historical_analysis_suite")
    assert i_env != -1 and i_suite != -1
    assert i_env < i_suite                                   # bootstrap AVANT le lancement
    assert "HL_ENABLE_MAINNET_EXECUTION=0" in txt            # paper strict
    assert "/exchange" not in txt                            # aucun endpoint d'ordre reel
    assert "%HYPERSMART_PYTHON%" in txt                      # meme Python portable que le runtime


def test_le_cmd_propage_le_code_de_sortie():
    txt = CMD.read_text(encoding="utf-8", errors="ignore")
    assert "exit /b %RC%" in txt
