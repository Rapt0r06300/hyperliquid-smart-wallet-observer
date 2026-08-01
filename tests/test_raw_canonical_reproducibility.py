"""[pépite 264] raw→canonical reproducibility : reparser le raw donne le même hash pour la même pipeline."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.dataset.raw_canonical_reproducibility import hash_canonique, verifier   # noqa: E402


def test_meme_pipeline_meme_hash():
    recs = [{"b": 2, "a": 1}, {"x": 9}]
    assert hash_canonique(recs, "v1") == hash_canonique([{"a": 1, "b": 2}, {"x": 9}], "v1")


def test_pipeline_differente_hash_different():
    recs = [{"a": 1}]
    assert hash_canonique(recs, "v1") != hash_canonique(recs, "v2")


def test_verifier_detecte_derive():
    recs = [{"a": 1}]
    h = hash_canonique(recs, "v1")
    assert verifier(h, recs, "v1")["reproductible"] is True
    assert verifier(h, [{"a": 2}], "v1")["reproductible"] is False
