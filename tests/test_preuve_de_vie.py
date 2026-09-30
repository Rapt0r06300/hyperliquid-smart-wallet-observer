"""[LANCEUR item 7] Preuve de vie par source — 0 réseau (heartbeats/PID/horloge injectés).

On prouve : READY seulement si toutes les OBLIGATOIRES saines ; DATA_NOT_READY (raison PRÉCISE : source,
canal, contrôle) sinon ; DEGRADED si une secondaire est muette ; chaque contrôle unitaire (process,
heartbeat frais, ACK inféré du flux, événement, croissance du flux, horodatage exchange+réception) ;
et l'attente bornée (devient READY / rend la dernière raison au timeout).
"""
from __future__ import annotations

from hl_observer.ops import preuve_de_vie as PV

NOW = 1_700_000_000_000.0
CORE = tuple(s for s in PV.SOURCES_HARVEST if s.obligatoire)   # allmids, bbo, userfills


def _hb(pid=123, ts=NOW, n=5, ex=NOW - 100.0, **extra):
    d = {"pid": pid, "ts_ms": ts, "n_ecrites_cumul": n, "dernier_exchange_ts": ex}
    d.update(extra)
    return d


def _vivant(pid):
    return pid == 123


def test_ready_quand_toutes_obligatoires_saines():
    hbs = {s.nom: _hb() for s in CORE}
    etat = PV.evaluer_readiness(CORE, hbs, now_ms=NOW, pid_vivant=_vivant)
    assert etat.statut == PV.STATUT_READY and etat.ready()
    assert all(p.sain for p in etat.preuves)


def test_data_not_ready_si_source_obligatoire_sans_heartbeat():
    hbs = {"allmids-collector": _hb(), "bbo-collector": _hb()}   # userfills-live absent
    etat = PV.evaluer_readiness(CORE, hbs, now_ms=NOW, pid_vivant=_vivant)
    assert etat.statut == PV.STATUT_DATA_NOT_READY
    assert "userfills-live" in etat.raison and "userFills" in etat.raison


def test_data_not_ready_precise_le_controle_echoue():
    hbs = {s.nom: _hb() for s in CORE}
    hbs["bbo-collector"] = _hb(ts=NOW - 120_000)                 # 120 s > seuil 60 s -> figé
    etat = PV.evaluer_readiness(CORE, hbs, now_ms=NOW, pid_vivant=_vivant)
    assert etat.statut == PV.STATUT_DATA_NOT_READY
    assert "bbo-collector" in etat.raison and "fige" in etat.raison


def test_degraded_si_secondaire_muette_mais_core_sain():
    srcs = CORE + (PV.SourceAttendue("carnet-collector", "HYPERLIQUID", "l2Book", False),)
    hbs = {s.nom: _hb() for s in CORE}                           # carnet muet
    etat = PV.evaluer_readiness(srcs, hbs, now_ms=NOW, pid_vivant=_vivant)
    assert etat.statut == PV.STATUT_DEGRADED and "carnet-collector" in etat.raison


def test_preuve_source_exige_exchange_et_reception_ts():
    src = PV.SourceAttendue("bbo-collector", "HYPERLIQUID", "bbo", True)
    p = PV.preuve_source(src, _hb(ex=None), now_ms=NOW, pid_vivant=_vivant)
    assert not p.sain and not p.horodatages_presents           # ts exchange manquant
    p2 = PV.preuve_source(src, _hb(), now_ms=NOW, pid_vivant=_vivant)
    assert p2.sain and p2.souscription_ack                     # ACK inféré du flux réel


def test_flux_grossit_via_baseline_ecrites():
    src = PV.SourceAttendue("allmids-collector", "HYPERLIQUID", "allMids", True)
    p = PV.preuve_source(src, _hb(n=5), now_ms=NOW, pid_vivant=_vivant, ecrites_precedentes=5)
    assert not p.flux_grossit and not p.sain                   # compteur figé
    p2 = PV.preuve_source(src, _hb(n=8), now_ms=NOW, pid_vivant=_vivant, ecrites_precedentes=5)
    assert p2.flux_grossit and p2.sain


def test_process_mort_echoue():
    src = PV.SourceAttendue("allmids-collector", "HYPERLIQUID", "allMids", True)
    p = PV.preuve_source(src, _hb(pid=999), now_ms=NOW, pid_vivant=_vivant)
    assert not p.process_actif and not p.sain and "process" in p.raison


def test_attendre_readiness_devient_ready_apres_quelques_passes():
    etats = [PV.EtatRuntime(PV.STATUT_DATA_NOT_READY, "attente", ()),
             PV.EtatRuntime(PV.STATUT_DATA_NOT_READY, "attente", ()),
             PV.EtatRuntime(PV.STATUT_READY, "ok", ())]
    seq = {"i": 0}
    horloge_t = {"t": 0.0}

    def lecteur(_now_ms):
        i = min(seq["i"], len(etats) - 1)
        seq["i"] += 1
        return etats[i]

    final = PV.attendre_readiness(lecteur, timeout_s=100, intervalle_s=1,
                                  horloge=lambda: horloge_t["t"],
                                  dormir=lambda s: horloge_t.__setitem__("t", horloge_t["t"] + s))
    assert final.ready() and seq["i"] == 3


def test_attendre_readiness_timeout_rend_derniere_raison():
    ko = PV.EtatRuntime(PV.STATUT_DATA_NOT_READY, "source obligatoire X: heartbeat fige", ())
    horloge_t = {"t": 0.0}
    final = PV.attendre_readiness(lambda _n: ko, timeout_s=3, intervalle_s=1,
                                  horloge=lambda: horloge_t["t"],
                                  dormir=lambda s: horloge_t.__setitem__("t", horloge_t["t"] + s))
    assert final.statut == PV.STATUT_DATA_NOT_READY and "heartbeat fige" in final.raison
