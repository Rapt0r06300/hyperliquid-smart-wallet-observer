"""Q-268 — Tests de quarantaine (book croisé, taille invalide, message en retard).

Vérifie que les modules de quarantaine rejettent correctement
les données invalides au lieu de les traiter silencieusement.
"""
from __future__ import annotations

import math

import pytest

from hl_observer.feed_integrity.crossed_book_quarantine import verifier as verifier_crossed
from hl_observer.feed_integrity.invalid_size_quarantine import valider_niveau


class TestCrossedBookQuarantine:
    def test_normal_book_exploitable(self):
        r = verifier_crossed(100.0, 100.5)
        assert r["etat"] == "EXPLOITABLE"
        assert r["croise"] is False

    def test_crossed_book_quarantined(self):
        r = verifier_crossed(101.0, 100.0)
        assert r["etat"] == "QUARANTAINE"
        assert r["raison"] == "BID_SUPERIEUR_ASK"

    def test_crossed_explicit_valid(self):
        r = verifier_crossed(101.0, 100.0, etat_valide_explicite=True)
        assert r["etat"] == "EXPLOITABLE"

    def test_flat_book_exploitable(self):
        r = verifier_crossed(100.0, 100.0)
        assert r["etat"] == "EXPLOITABLE"

    def test_nan_quarantined(self):
        r = verifier_crossed(float("nan"), 100.0)
        assert r["etat"] == "QUARANTAINE"

    def test_inf_quarantined(self):
        r = verifier_crossed(float("inf"), 100.0)
        assert r["etat"] == "QUARANTAINE"

    def test_string_quarantined(self):
        r = verifier_crossed("bad", 100.0)
        assert r["etat"] == "QUARANTAINE"

    def test_none_quarantined(self):
        r = verifier_crossed(None, 100.0)
        assert r["etat"] == "QUARANTAINE"


class TestInvalidSizeQuarantine:
    def test_valid_level(self):
        r = valider_niveau(100.0, 5.0)
        assert r["etat"] == "VALIDE"

    def test_zero_size_is_suppression(self):
        r = valider_niveau(100.0, 0)
        assert r["etat"] == "SUPPRESSION"

    def test_negative_size_invalid(self):
        r = valider_niveau(100.0, -1.0)
        assert r["etat"] == "INVALIDE"
        assert r["raison"] == "TAILLE_IMPOSSIBLE"

    def test_zero_price_invalid(self):
        r = valider_niveau(0, 5.0)
        assert r["etat"] == "INVALIDE"
        assert r["raison"] == "PRIX_IMPOSSIBLE"

    def test_negative_price_invalid(self):
        r = valider_niveau(-1.0, 5.0)
        assert r["etat"] == "INVALIDE"

    def test_nan_size_invalid(self):
        r = valider_niveau(100.0, float("nan"))
        assert r["etat"] == "INVALIDE"

    def test_inf_price_invalid(self):
        r = valider_niveau(float("inf"), 5.0)
        assert r["etat"] == "INVALIDE"

    def test_size_exceeds_max(self):
        r = valider_niveau(100.0, 1_000_000, taille_max=100_000)
        assert r["etat"] == "INVALIDE"
        assert r["raison"] == "TAILLE_SUPERIEURE_MAX"

    def test_bool_price_invalid(self):
        r = valider_niveau(True, 5.0)
        assert r["etat"] == "INVALIDE"
