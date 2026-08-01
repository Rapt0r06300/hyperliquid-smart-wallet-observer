"""[LANCEUR items 1,2] Preuve de vie : deux niveaux READY_CORE/READY_HARVEST + taxonomie de cause
(panne technique ≠ marché calme ≠ quota ≠ donnée absente ≠ source non implémentée). Câble la protection
canonique etat_ingestion (IDEA-79). 0 réseau.
"""
from __future__ import annotations

from hl_observer.ops import preuve_de_vie as PV
from hl_observer.ops.preuve_de_vie import SourceAttendue

NOW = 1_700_000_000_000.0
CORE = tuple(s for s in PV.SOURCES_HARVEST if s.obligatoire)


def _hb(pid=123, ts=NOW, n=5, ex=NOW - 100.0):
    return {"pid": pid, "ts_ms": ts, "n_ecrites_cumul": n, "dernier_exchange_ts": ex}


def _vivant(pid):
    return pid == 123


def test_ready_core_et_ready_harvest_quand_tout_sain():
    srcs = CORE + (SourceAttendue("carnet-collector", "HYPERLIQUID", "l2Book", False),)
    hbs = {s.nom: _hb() for s in srcs}
    etat = PV.evaluer_readiness(srcs, hbs, now_ms=NOW, pid_vivant=_vivant)
    assert etat.ready_core is True and etat.ready_harvest is True
    assert all(c["cause"] == PV.CAUSE_OK for c in etat.causes)


def test_source_non_implementee_ne_bloque_pas_harvest():
    srcs = CORE + (SourceAttendue("bybit-x", "BYBIT", "trades", False, non_implementee=True),)
    hbs = {s.nom: _hb() for s in CORE}                       # bybit sans heartbeat mais déclarée indispo
    etat = PV.evaluer_readiness(srcs, hbs, now_ms=NOW, pid_vivant=_vivant)
    assert etat.ready_core is True and etat.ready_harvest is True
    assert any(c["cause"] == PV.CAUSE_NON_IMPLEMENTEE for c in etat.causes)


def test_panne_technique_bloque_core_et_harvest():
    hbs = {s.nom: _hb() for s in CORE}
    hbs["bbo-collector"] = _hb(ts=NOW - 120_000)            # heartbeat figé -> panne
    etat = PV.evaluer_readiness(CORE, hbs, now_ms=NOW, pid_vivant=_vivant)
    assert etat.ready_core is False and etat.ready_harvest is False
    causes = {c["source"]: c["cause"] for c in etat.causes}
    assert causes["bbo-collector"] == PV.CAUSE_PANNE_TECHNIQUE


def test_marche_calme_n_est_pas_une_panne():
    # collecteur vivant, heartbeat frais, ACK, mais 0 écriture nouvelle -> MARCHE_CALME (via etat_ingestion)
    src = SourceAttendue("carnet-collector", "HYPERLIQUID", "l2Book", False)
    hb = {"pid": 123, "ts_ms": NOW, "n_ecrites_cumul": 0, "dernier_exchange_ts": NOW - 10, "souscription_ack": True}
    p = PV.preuve_source(src, hb, now_ms=NOW, pid_vivant=_vivant)
    c = PV.cause_source(src, p, ecrites=0, ecrites_precedentes=0, heartbeat_present=True)
    assert c["cause"] == PV.CAUSE_MARCHE_CALME and c["sante"] == "VERTE"


def test_gap_critique_et_carnet_desync_rendent_non_sain():
    src = SourceAttendue("bbo-collector", "HYPERLIQUID", "bbo", True)
    p_gap = PV.preuve_source(src, _hb(), now_ms=NOW, pid_vivant=_vivant, gaps_critiques=3)
    p_desync = PV.preuve_source(src, _hb(), now_ms=NOW, pid_vivant=_vivant, carnet_desync=True)
    assert not p_gap.sain and "gap" in p_gap.raison
    assert not p_desync.sain and "desync" in p_desync.raison


def test_quota_detecte_sur_reconnexions_repetees():
    src = SourceAttendue("bbo-collector", "HYPERLIQUID", "bbo", True)
    # process vivant + heartbeat frais mais flux ne grossit pas -> non sain ; reconnexions massives -> QUOTA
    hb = {"pid": 123, "ts_ms": NOW, "n_ecrites_cumul": 5, "dernier_exchange_ts": NOW - 10}
    p = PV.preuve_source(src, hb, now_ms=NOW, pid_vivant=_vivant, ecrites_precedentes=5)  # flux figé -> non sain
    c = PV.cause_source(src, p, ecrites=5, ecrites_precedentes=5, reconnexions=50, heartbeat_present=True)
    assert c["cause"] == PV.CAUSE_QUOTA
