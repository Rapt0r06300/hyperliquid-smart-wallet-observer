from __future__ import annotations

import ast

import pytest

from hl_observer.testing import lookahead_detector as detector


def test_suspicion_as_dict_and_target_helpers() -> None:
    suspicion = detector.Suspicion(
        fichier="x.py",
        ligne=12,
        fonction="f",
        cible="prices",
        agregat="mean",
        motif=detector.MOTIF_AGREGAT_GLOBAL,
        extrait="prices.mean()",
    )
    payload = suspicion.as_dict()
    assert payload["fichier"] == "x.py"
    assert payload["ligne"] == 12
    assert payload["cible"] == "prices"
    assert "PAS PREUVE" in payload["avertissement"]

    assert detector._nom_de_la_cible(ast.Name(id="prices")) == "prices"
    assert detector._nom_de_la_cible(ast.Attribute(value=ast.Name(id="obj"), attr="price")) == "obj"
    assert detector._nom_de_la_cible(ast.Subscript(value=ast.Name(id="df"), slice=ast.Constant(value="px"))) == "px"
    assert detector._nom_de_la_cible(ast.Subscript(value=ast.Name(id="prices"), slice=ast.Name(id="i"))) == "prices"
    assert detector._nom_de_la_cible(ast.Call(func=ast.Name(id="prices"), args=[], keywords=[])) == "prices"
    assert detector._nom_de_la_cible(ast.Constant(value=1)) == ""
    assert detector._ressemble_a_une_serie("future_prices") is True
    assert detector._ressemble_a_une_serie("counter") is False


def test_window_detection_handles_calls_attributes_and_subscripts() -> None:
    safe_call = ast.parse("prices.rolling(20).mean()").body[0].value
    assert isinstance(safe_call, ast.Call)
    assert detector._est_deja_fenetre(safe_call.func.value) is True

    explicit_slice = ast.parse("prices[:i].mean()").body[0].value
    assert isinstance(explicit_slice, ast.Call)
    assert detector._est_deja_fenetre(explicit_slice.func.value) is True

    unsafe = ast.parse("prices.mean()").body[0].value
    assert isinstance(unsafe, ast.Call)
    assert detector._est_deja_fenetre(unsafe.func.value) is False


def test_analyser_source_flags_attribute_aggregate_but_ignores_safe_or_irrelevant() -> None:
    source = """
def bad(prices):
    return prices.mean()

def safe(prices):
    return prices[:3].mean()

def irrelevant(counter):
    return counter.mean()

async def bad_async(mid_series):
    return mid_series.std()
"""
    suspicions = detector.analyser_source(source, fichier="sample.py")
    assert [(s.fonction, s.cible, s.agregat) for s in suspicions] == [
        ("bad", "prices", "mean"),
        ("bad_async", "mid_series", "std"),
    ]
    assert all(s.fichier == "sample.py" for s in suspicions)
    assert suspicions[0].extrait == "return prices.mean()"
    assert detector.analyser_source("def broken(:", fichier="bad.py") == []


def test_analyser_fichiers_skips_missing_and_sorts(tmp_path) -> None:
    first = tmp_path / "b.py"
    second = tmp_path / "a.py"
    first.write_text("def f(prices):\n    return prices.mean()\n", encoding="utf-8")
    second.write_text("def g(mid):\n    return mid.max()\n", encoding="utf-8")
    result = detector.analyser_fichiers([first, tmp_path / "missing.py", second])
    assert [(s.fichier, s.fonction) for s in result] == [
        (str(second), "g"),
        (str(first), "f"),
    ]


def test_lit_le_futur_input_validation_and_non_testable_outputs() -> None:
    with pytest.raises(ValueError, match="serie trop courte"):
        detector.lit_le_futur(lambda x: x, [1, 2, 3])
    with pytest.raises(ValueError, match="i hors bornes"):
        detector.lit_le_futur(lambda x: x, [1, 2, 3, 4], i=4)
    with pytest.raises(TypeError, match="sortie non testable"):
        detector.lit_le_futur(lambda x: "hash", [1, 2, 3, 4])
    with pytest.raises(TypeError, match="non alignee"):
        detector.lit_le_futur(lambda x: [1], [1, 2, 3, 4])
    with pytest.raises(TypeError, match="non numerique"):
        detector.lit_le_futur(lambda x: ["x"] * len(x), [1, 2, 3, 4])
    with pytest.raises(TypeError, match="non numerique"):
        detector.lit_le_futur(lambda x: [True] * len(x), [1, 2, 3, 4])


def test_lit_le_futur_detects_change_and_respects_numeric_tolerance() -> None:
    def causal(values):
        return [sum(values[: i + 1]) / (i + 1) for i in range(len(values))]

    def future(values):
        mean = sum(values) / len(values)
        return [mean for _ in values]

    assert detector.lit_le_futur(causal, [1.0, 2.0, 3.0, 100.0], i=1) is False
    assert detector.lit_le_futur(future, [1.0, 2.0, 3.0, 100.0], i=1) is True

    def tiny(values):
        last = values[-1]
        return [float(v) + last * 1e-15 for v in values]

    assert detector.lit_le_futur(tiny, [1.0, 2.0, 3.0, 4.0], i=1) is False


def test_resume_counts_files_and_keeps_warning() -> None:
    suspicions = [
        detector.Suspicion("b.py", 2, "f", "prices", "mean", detector.MOTIF_AGREGAT_GLOBAL),
        detector.Suspicion("a.py", 1, "g", "mid", "std", detector.MOTIF_AGREGAT_GLOBAL),
        detector.Suspicion("b.py", 3, "h", "pnl", "max", detector.MOTIF_AGREGAT_GLOBAL),
    ]
    report = detector.resume(suspicions)
    assert report["n_suspicions"] == 3
    assert report["n_fichiers"] == 2
    assert report["par_fichier"] == {"b.py": 2, "a.py": 1}
    assert report["real_execution"] is False
    assert "SIGNALEMENTS, PAS PREUVES" in report["avertissement"]
