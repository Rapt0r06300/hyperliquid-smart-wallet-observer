"""[pépite 265] parser golden corpus : messages rares/invalides/partiels comme non-régression du parser."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.dataset.parser_golden_corpus import CorpusGolden   # noqa: E402


def _parser_ok(brut):
    if brut == "BAD":
        return "INVALIDE"
    return {"val": int(brut)}


def test_corpus_sans_regression():
    c = CorpusGolden()
    c.ajouter_cas("normal", "42", {"val": 42})
    c.ajouter_cas("invalide_connu", "BAD", "INVALIDE")
    r = c.verifier(_parser_ok)
    assert r["sans_regression"] is True and r["total"] == 2


def test_regression_detectee():
    c = CorpusGolden()
    c.ajouter_cas("cas", "BAD", {"val": 0})        # parser rend "INVALIDE", attendu diffère
    assert c.verifier(_parser_ok)["sans_regression"] is False


def test_exception_comptee_echec():
    c = CorpusGolden()
    c.ajouter_cas("partiel", "", {"val": 0})       # int("") lève -> echec, pas succès
    assert c.verifier(_parser_ok)["echecs"][0]["obtenu"].startswith("EXCEPTION")
