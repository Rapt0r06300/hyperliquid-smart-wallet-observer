"""UN EDGE EST UN MOUVEMENT DE PRIX — pas un score de vote (2026-07-11).

LA CAUSE RACINE DU PnL NÉGATIF, et le test qui l'interdit désormais.

L'« edge » qui autorisait CHAQUE entrée de copie valait :

    dominance × 45 + bonus − 18          ← un score de VOTE. Jamais un prix.

Le code l'avouait : `edge_source = "CONSENSUS_VOTE_PROXY_NOT_EMPIRICAL"`, `edge_is_empirical=False`.
Le seuil `min_edge` comparait donc **une valeur inventée** à un plancher — c'est pourquoi aucun
réglage de ce seuil n'a jamais rien changé, et pourquoi le bot ouvrait ce que l'`opportunity_report`
refusait au même instant.

Règle posée, et testée ici : **un edge est mesuré, ou il n'existe pas. Pas de mesure → NO_TRADE.**

⚠️ Conséquence assumée : sans table de calibration, le moteur de copie **n'ouvre plus rien**.
C'est le résultat honnête — on a mesuré (24 133 signaux, hors échantillon) que le copy-trading n'a
pas d'edge, même à coût zéro. Un bot qui refuse de trader sans edge n'est pas cassé : il est lucide.

Aucun ordre réel.
"""
from __future__ import annotations

import json

import pytest

from hl_observer.edge.empirical_edge import (
    MIN_ECHANTILLON,
    REFUS_CALIBRATION_ABSENTE,
    REFUS_ECHANTILLON_TROP_PETIT,
    REFUS_NON_EMPIRIQUE,
    edge_from_calibration,
    empirical_edge_refusal,
    load_calibration,
    no_empirical_edge,
)


def _table(bands: list[dict]) -> dict:
    return {"source": "OUT_OF_SAMPLE_MEASUREMENT", "measured_at": "2026-07-11",
            "horizon_ms": 30_000, "bands": bands}


# --------------------------------------------------------- DENY-BY-DEFAULT

def test_without_a_measured_table_the_bot_refuses_to_trade(monkeypatch, tmp_path):
    """LE CŒUR. Aucune mesure → aucun edge → NO_TRADE. On ne fabrique plus de chiffre."""
    monkeypatch.setenv("HYPERSMART_EDGE_CALIBRATION_PATH", str(tmp_path / "absent.json"))
    edge = edge_from_calibration(signal_age_ms=1_500)
    assert edge.is_empirical is False
    assert edge.value_bps == 0.0
    assert empirical_edge_refusal(edge) == REFUS_CALIBRATION_ABSENTE


def test_an_unknown_signal_age_means_no_edge(monkeypatch, tmp_path):
    """Sans fraîcheur, l'edge de copie n'est pas mesurable — c'est même TOUT le problème du Sniper."""
    p = tmp_path / "cal.json"
    p.write_text(json.dumps(_table([
        {"age_min_ms": 0, "age_max_ms": 5_000, "edge_bps": 30.0, "sample_size": 5_000}])),
        encoding="utf-8")
    monkeypatch.setenv("HYPERSMART_EDGE_CALIBRATION_PATH", str(p))
    edge = edge_from_calibration(signal_age_ms=None)
    assert edge.is_empirical is False
    assert empirical_edge_refusal(edge) == REFUS_NON_EMPIRIQUE


def test_a_tiny_sample_is_noise_not_a_measurement(monkeypatch, tmp_path):
    """RÈGLE DURE : sous 200 observations, une « mesure » est du bruit déguisé en science."""
    p = tmp_path / "cal.json"
    p.write_text(json.dumps(_table([
        {"age_min_ms": 0, "age_max_ms": 5_000, "edge_bps": 80.0,
         "sample_size": MIN_ECHANTILLON - 1}])), encoding="utf-8")
    monkeypatch.setenv("HYPERSMART_EDGE_CALIBRATION_PATH", str(p))
    edge = edge_from_calibration(signal_age_ms=1_000)
    assert edge.is_empirical is False
    assert empirical_edge_refusal(edge) == REFUS_ECHANTILLON_TROP_PETIT


def test_an_age_outside_every_measured_band_is_refused(monkeypatch, tmp_path):
    """On n'EXTRAPOLE pas : hors des bandes mesurées, on ne sait pas → on ne trade pas."""
    p = tmp_path / "cal.json"
    p.write_text(json.dumps(_table([
        {"age_min_ms": 0, "age_max_ms": 2_000, "edge_bps": 25.0, "sample_size": 1_000}])),
        encoding="utf-8")
    monkeypatch.setenv("HYPERSMART_EDGE_CALIBRATION_PATH", str(p))
    edge = edge_from_calibration(signal_age_ms=60_000)     # signal vieux : hors bande
    assert edge.is_empirical is False
    assert empirical_edge_refusal(edge) == REFUS_NON_EMPIRIQUE


# --------------------------------------------------------- une mesure VALIDE passe

def test_a_real_measurement_is_accepted_and_traceable(monkeypatch, tmp_path):
    p = tmp_path / "cal.json"
    p.write_text(json.dumps(_table([
        {"age_min_ms": 0, "age_max_ms": 2_000, "edge_bps": 24.0, "sample_size": 3_000,
         "note": "mesure OOS"}])), encoding="utf-8")
    monkeypatch.setenv("HYPERSMART_EDGE_CALIBRATION_PATH", str(p))
    edge = edge_from_calibration(signal_age_ms=800)
    assert edge.is_empirical is True
    assert edge.value_bps == 24.0
    assert edge.sample_size == 3_000
    assert empirical_edge_refusal(edge) == ""
    # la PREUVE voyage : plus jamais de `null` dans le ledger
    d = edge.as_dict()
    assert d["edge_is_empirical"] is True and d["edge_sample_size"] == 3_000


def test_a_measured_negative_edge_is_reported_as_such(monkeypatch, tmp_path):
    """HONNÊTETÉ : si la mesure dit −8 bps, on le DIT. Le gate de coût fera son travail ensuite.
    On ne remplace pas une mauvaise mesure par une bonne invention."""
    p = tmp_path / "cal.json"
    p.write_text(json.dumps(_table([
        {"age_min_ms": 0, "age_max_ms": 60_000, "edge_bps": -7.97, "sample_size": 24_133,
         "note": "la vraie mesure du copy-trading, hors echantillon"}])), encoding="utf-8")
    monkeypatch.setenv("HYPERSMART_EDGE_CALIBRATION_PATH", str(p))
    edge = edge_from_calibration(signal_age_ms=30_000)
    assert edge.is_empirical is True
    assert edge.value_bps == pytest.approx(-7.97)
    assert empirical_edge_refusal(edge) == "", "le gate d'empiricité passe : c'est au COÛT de refuser"


# --------------------------------------------------------- le mode A/B ne devient jamais le défaut

def test_the_old_proxy_is_only_reachable_by_an_explicit_flag(monkeypatch, tmp_path):
    """L'ancien proxy inventé reste accessible pour COMPARER — jamais par défaut."""
    monkeypatch.setenv("HYPERSMART_EDGE_CALIBRATION_PATH", str(tmp_path / "absent.json"))
    monkeypatch.delenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", raising=False)
    assert empirical_edge_refusal(no_empirical_edge(REFUS_NON_EMPIRIQUE)) != "", (
        "par DÉFAUT le bot doit refuser un edge non empirique"
    )
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    assert empirical_edge_refusal(no_empirical_edge(REFUS_NON_EMPIRIQUE)) == ""


def test_a_missing_edge_object_is_refused():
    assert empirical_edge_refusal(None) == REFUS_NON_EMPIRIQUE


# --------------------------------------------------------- robustesse

def test_a_corrupt_calibration_file_is_treated_as_absent(monkeypatch, tmp_path):
    """Un fichier illisible n'est PAS une autorisation de trader : c'est une absence."""
    p = tmp_path / "cal.json"
    p.write_text("{ ceci n'est pas du json", encoding="utf-8")
    monkeypatch.setenv("HYPERSMART_EDGE_CALIBRATION_PATH", str(p))
    assert load_calibration() is None
    assert edge_from_calibration(signal_age_ms=500).is_empirical is False


def test_garbage_bands_never_crash_and_never_authorise(monkeypatch, tmp_path):
    p = tmp_path / "cal.json"
    p.write_text(json.dumps({"bands": [None, "x", {}, {"age_min_ms": "abc"}]}), encoding="utf-8")
    monkeypatch.setenv("HYPERSMART_EDGE_CALIBRATION_PATH", str(p))
    edge = edge_from_calibration(signal_age_ms=500)
    assert edge.is_empirical is False
    assert empirical_edge_refusal(edge) != ""
