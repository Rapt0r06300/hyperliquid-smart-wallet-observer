"""[LANCEUR item 12] Tableau de santé LIVE — une ligne par source, zone dynamique compacte + journal
horodaté. Prouvé sans réseau. events/s : EN CALIBRATION à la 1re passe, calculé à la 2e.
"""
from __future__ import annotations

from hl_observer.ops import tableau_sante_collecteurs as TS
from hl_observer.ops.preuve_de_vie import SourceAttendue

NOW = 1_700_000_000_000.0
SRCS = (SourceAttendue("bbo-collector", "HYPERLIQUID", "bbo", True),
        SourceAttendue("carnet-collector", "HYPERLIQUID", "l2Book", False))


def _hb(pid=123, ts=NOW, n=10, ex=NOW - 50.0):
    return {"pid": pid, "ts_ms": ts, "n_ecrites_cumul": n, "dernier_exchange_ts": ex}


def _vivant(pid):
    return pid == 123


def test_tableau_une_ligne_par_source_avec_metriques():
    metr = {"bbo-collector": {"gaps": 2, "doublons": 1, "reconnects": 3, "stale_events": 0,
                              "octets": 4096, "chemin": "runtime/data/bbo.jsonl"}}
    t = TS.construire_tableau(SRCS, {"bbo-collector": _hb()}, {"bbo-collector": 123}, metr,
                              now_ms=NOW, pid_vivant=_vivant, horodatage="H1")
    assert len(t.lignes) == 2
    bbo = t.lignes[0]
    assert bbo.etat == "SAIN" and bbo.pid == 123 and bbo.gaps == 2 and bbo.doublons == 1
    assert bbo.reconnexions == 3 and bbo.octets_ecrits == 4096 and bbo.chemin_sortie.endswith("bbo.jsonl")
    assert t.lignes[1].etat == "MUET"                          # carnet secondaire sans heartbeat


def test_events_par_s_calibration_puis_calcule():
    t1 = TS.construire_tableau(SRCS[:1], {"bbo-collector": _hb(n=10)}, {}, {}, now_ms=NOW, pid_vivant=_vivant)
    assert t1.lignes[0].events_par_s is None                  # EN CALIBRATION (1re passe)
    t2 = TS.construire_tableau(SRCS[:1], {"bbo-collector": _hb(n=30)}, {}, {}, now_ms=NOW + 2000.0,
                               pid_vivant=_vivant, precedent=t1.snapshot)
    assert t2.lignes[0].events_par_s == 10.0                   # 20 events / 2 s


def test_etat_manque_pour_obligatoire_absente():
    t = TS.construire_tableau(SRCS[:1], {}, {}, {}, now_ms=NOW, pid_vivant=_vivant)
    assert t.lignes[0].etat == "MANQUE"                        # obligatoire sans preuve


def test_format_compact_pas_des_milliers_de_lignes():
    t = TS.construire_tableau(SRCS, {"bbo-collector": _hb()}, {"bbo-collector": 123}, {},
                              now_ms=NOW, pid_vivant=_vivant, horodatage="H2")
    lignes = TS.format_tableau(t).splitlines()
    assert len(lignes) == 2 + len(SRCS)                        # en-tête + colonnes + 1 ligne/source
    assert "TABLEAU DE SANTE" in lignes[0] and "1/2 sains" in lignes[0]


def test_ligne_journal_horodatee():
    t = TS.construire_tableau(SRCS, {"bbo-collector": _hb()}, {"bbo-collector": 123}, {},
                              now_ms=NOW, pid_vivant=_vivant, horodatage="2026-08-01T12:00:00Z")
    j = TS.ligne_journal(t)
    assert j.startswith("[2026-08-01T12:00:00Z]") and "sains=1/2" in j
