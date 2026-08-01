"""[LANCEUR item 2] E2E chemin RÉEL disque : `evaluer_depuis_disque()` charge les VRAIES métriques de
qualité écrites par les collecteurs (`heartbeat_collecteur.battre(..., metriques=...)`) et les transmet à
`evaluer_readiness()`. La règle dure prouvée ici : **un heartbeat FRAIS ne masque jamais** un gap
critique / carnet désync / séquence exchange invalide / resync en attente / stale / hors-ordre /
reconnexions excessives. 0 réseau — on écrit de vrais heartbeats sur un tmp_path et on relit du disque.
"""
from __future__ import annotations

import time

from hl_observer.ops import preuve_de_vie as PV
from tools import heartbeat_collecteur as HB

CORE = tuple(s for s in PV.SOURCES_HARVEST if s.obligatoire)


def _battre_sain(root, nom, *, metriques=None):
    """Écrit un heartbeat qui, SANS métrique dégradée, serait parfaitement sain (process vivant = ce test,
    flux non nul, horodatage exchange présent)."""
    return HB.battre(root, nom, n_ecrites=5, dernier_exchange_ts=int(time.time() * 1000) - 100,
                     metriques=metriques)


def _now_ms_apres(hb):
    return float(hb["ts_ms"]) + 200.0        # « maintenant » juste après le battement -> heartbeat frais


def test_battre_persiste_les_metriques_et_round_trip(tmp_path):
    hb = _battre_sain(tmp_path, "bbo-collector",
                      metriques={"gaps_critiques": 3, "carnet_desync": True, "reconnects": 7})
    assert hb["metriques"]["gaps_critiques"] == 3
    assert hb["metriques"]["carnet_desync"] is True
    relu = HB.lire(tmp_path, "bbo-collector")
    assert relu["metriques"]["gaps_critiques"] == 3 and relu["metriques"]["reconnects"] == 7


def test_metriques_none_conserve_l_etat_precedent(tmp_path):
    # un problème connu ne se « nettoie » pas par un simple battement sans métrique (fail-closed honnête).
    _battre_sain(tmp_path, "bbo-collector", metriques={"gaps_critiques": 2})
    hb2 = _battre_sain(tmp_path, "bbo-collector", metriques=None)
    assert hb2["metriques"]["gaps_critiques"] == 2
    # ... et une remontée EXPLICITE à zéro efface bien le problème (reprise réelle).
    hb3 = _battre_sain(tmp_path, "bbo-collector", metriques={"gaps_critiques": 0})
    assert hb3["metriques"]["gaps_critiques"] == 0


def _core_tous_sains_sauf(tmp_path, nom_degrade, metriques_degrade):
    dernier = None
    for s in CORE:
        m = metriques_degrade if s.nom == nom_degrade else None
        dernier = _battre_sain(tmp_path, s.nom, metriques=m)
    return dernier


def test_e2e_heartbeat_frais_ne_masque_pas_un_gap_critique(tmp_path):
    # LE test clé de l'item 2 : bbo-collector bat À L'INSTANT (frais, process vivant, flux non nul) MAIS
    # remonte un gap critique -> le chemin réel doit le rendre NON sain et bloquer READY_CORE.
    hb = _core_tous_sains_sauf(tmp_path, "bbo-collector", {"gaps_critiques": 4})
    etat = PV.evaluer_depuis_disque(tmp_path, sources=CORE, now_ms=_now_ms_apres(hb))
    assert etat.ready_core is False
    par_nom = {p.nom: p for p in etat.preuves}
    assert par_nom["bbo-collector"].heartbeat_frais is True      # bien FRAIS...
    assert par_nom["bbo-collector"].sain is False                # ... et pourtant NON sain (gap non masqué)
    assert "gap" in par_nom["bbo-collector"].raison
    # les deux autres sources CORE restent saines : le blocage est ciblé, pas global.
    assert par_nom["allmids-collector"].sain is True and par_nom["userfills-live"].sain is True
    causes = {c["source"]: c["cause"] for c in etat.causes}
    assert causes["bbo-collector"] == PV.CAUSE_PANNE_TECHNIQUE   # pas DONNEE_ABSENTE, pas MARCHE_CALME


def test_e2e_carnet_desync_bloque_le_core(tmp_path):
    hb = _core_tous_sains_sauf(tmp_path, "allmids-collector", {"carnet_desync": True})
    etat = PV.evaluer_depuis_disque(tmp_path, sources=CORE, now_ms=_now_ms_apres(hb))
    assert etat.ready_core is False
    par_nom = {p.nom: p for p in etat.preuves}
    assert par_nom["allmids-collector"].sain is False and "desync" in par_nom["allmids-collector"].raison


def test_e2e_sequence_invalide_resync_stale_hors_ordre_bloquent(tmp_path):
    for cle, extrait in (("sequence_invalide", "sequence"), ("resync_en_attente", "resync"),
                         ("stale", "stale"), ("hors_ordre", "hors ordre")):
        val = 3 if cle == "hors_ordre" else True
        hb = _core_tous_sains_sauf(tmp_path, "userfills-live", {cle: val})
        etat = PV.evaluer_depuis_disque(tmp_path, sources=CORE, now_ms=_now_ms_apres(hb))
        par_nom = {p.nom: p for p in etat.preuves}
        assert etat.ready_core is False, cle
        assert par_nom["userfills-live"].sain is False, cle
        assert extrait in par_nom["userfills-live"].raison, (cle, par_nom["userfills-live"].raison)


def test_e2e_reconnexions_excessives_bloquent_et_donnent_quota(tmp_path):
    hb = _core_tous_sains_sauf(tmp_path, "bbo-collector", {"reconnects": 50})
    etat = PV.evaluer_depuis_disque(tmp_path, sources=CORE, now_ms=_now_ms_apres(hb))
    assert etat.ready_core is False
    par_nom = {p.nom: p for p in etat.preuves}
    assert par_nom["bbo-collector"].sain is False
    causes = {c["source"]: c["cause"] for c in etat.causes}
    assert causes["bbo-collector"] == PV.CAUSE_QUOTA            # reconnexions massives -> quota, pas panne


def test_e2e_core_sain_sans_metrique_reste_ready(tmp_path):
    # garde-fou anti-faux-positif : sans aucune métrique dégradée, le CORE reste READY (0 blocage abusif).
    hb = None
    for s in CORE:
        hb = _battre_sain(tmp_path, s.nom)
    etat = PV.evaluer_depuis_disque(tmp_path, sources=CORE, now_ms=_now_ms_apres(hb))
    assert etat.ready_core is True and all(p.sain for p in etat.preuves)
