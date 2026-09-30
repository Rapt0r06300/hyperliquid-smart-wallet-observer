"""G3 — conditionnement session/heure (UTC)."""
from __future__ import annotations

from datetime import datetime, timezone

from hl_observer.signals.session_conditioning import contexte_temporel, autorise_session


def _ts(y, mo, d, h):
    return int(datetime(y, mo, d, h, tzinfo=timezone.utc).timestamp() * 1000)


def test_session_us_en_semaine():
    ctx = contexte_temporel(_ts(2026, 1, 5, 15))       # lundi 15h UTC
    assert ctx["session"] == "US" and ctx["weekend"] is False and ctx["heures_bureau"] is True


def test_session_asie_tot():
    assert contexte_temporel(_ts(2026, 1, 5, 3))["session"] == "ASIE"


def test_weekend_detecte():
    ctx = contexte_temporel(_ts(2026, 1, 3, 10))       # samedi
    assert ctx["weekend"] is True


def test_autorise_par_defaut_tout():
    assert autorise_session(_ts(2026, 1, 3, 10)) is True


def test_bloque_weekend_si_demande():
    assert autorise_session(_ts(2026, 1, 3, 10), autoriser_weekend=False) is False
    assert autorise_session(_ts(2026, 1, 5, 10), autoriser_weekend=False) is True   # lundi ok


def test_filtre_sessions_autorisees():
    assert autorise_session(_ts(2026, 1, 5, 3), sessions_autorisees={"US"}) is False  # ASIE bloquee
    assert autorise_session(_ts(2026, 1, 5, 15), sessions_autorisees={"US"}) is True
