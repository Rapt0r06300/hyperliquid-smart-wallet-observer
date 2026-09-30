from hl_observer.research.stream_reliability import (
    liveness_vs_progression, last_useful_event_ts, seuils_stale_par_stream,
    DeadLetterQueue, RegistreMigrationsSchema, compteur_evenements_utiles)


def test_liveness_differente_de_progression():
    assert liveness_vs_progression(socket_connecte=True, dernier_event_ts=100.0, maintenant=1000.0, seuil_s=60)["vivant_utile"] is False
    assert liveness_vs_progression(socket_connecte=True, dernier_event_ts=990.0, maintenant=1000.0, seuil_s=60)["vivant_utile"] is True


def test_last_useful_event_ts_ignore_keepalive():
    evs = [{"ts": 1, "utile": False}, {"ts": 2, "utile": True}, {"ts": 3, "utile": False}]
    assert last_useful_event_ts(evs) == 2


def test_seuils_stale_par_stream():
    streams = {"orderbook": 990.0, "funding": 100.0}
    seuils = {"orderbook": 1.0, "funding": 100000.0}
    r = seuils_stale_par_stream(streams, seuils, maintenant=1000.0)
    assert r["perimes"] == ["orderbook"]


def test_dead_letter_queue():
    dlq = DeadLetterQueue()
    dlq.deposer({"x": 1}, "PARSE_ERROR")
    assert dlq.compter() == 1 and dlq.vider()[0]["raison"] == "PARSE_ERROR" and dlq.compter() == 0


def test_registre_migrations_schema():
    r = RegistreMigrationsSchema()
    r.enregistrer(2, "ajout colonne")
    r.enregistrer(1, "init")
    assert r.version_courante() == 2 and [m["version"] for m in r.plan(1)] == [2]


def test_compteur_evenements_utiles():
    r = compteur_evenements_utiles({"A": [{"utile": True}, {"utile": False}], "B": [{"utile": False}]})
    assert r["par_consommateur"]["A"] == 1 and r["consommateurs_morts"] == ["B"]
