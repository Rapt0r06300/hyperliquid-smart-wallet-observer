"""[LANCEUR item 1] Barrière READY_CORE **bloquante** avec warmup borné. Prouve, sans temps réel
(horloge/dormir injectés), que : l'attente rend la main dès que le niveau est atteint ; elle expire
proprement si le CORE ne prouve jamais sa vie ; le CLI sort non-zero (DATA_NOT_READY) sinon 0 ; et que
le lanceur .cmd appelle bien la barrière AVANT le moteur/UI. 0 réseau.
"""
from __future__ import annotations

from pathlib import Path

from hl_observer.ops import preuve_de_vie as PV
from hl_observer.ops.preuve_de_vie import EtatRuntime

RACINE = Path(__file__).resolve().parents[1]
CMD = RACINE / "LANCER_HYPERSMART.cmd"


def _etat(ready_core, niveau=None):
    niveau = niveau or (PV.HARVEST_COMPLET if ready_core else PV.STATUT_DATA_NOT_READY)
    st = PV.STATUT_READY if ready_core else PV.STATUT_DATA_NOT_READY
    return EtatRuntime(st, "test", (), ready_core=ready_core, ready_harvest=(niveau == PV.HARVEST_COMPLET),
                       causes=(), niveau_harvest=niveau)


def test_attente_rend_la_main_des_que_core_prouve():
    # CORE malade aux 2 premières passes, puis vivant : l'attente doit s'arrêter à la 3e (pas de timeout).
    suite = [_etat(False), _etat(False), _etat(True), _etat(True)]
    appels = {"n": 0}

    def lecteur():
        e = suite[min(appels["n"], len(suite) - 1)]
        appels["n"] += 1
        return e

    horloge = {"t": 0.0}
    etat = PV.evaluer_avec_attente(lecteur, niveau="core", timeout_s=100.0, intervalle_s=3.0,
                                   horloge=lambda: horloge.__setitem__("t", horloge["t"] + 1) or horloge["t"],
                                   dormir=lambda _s: None)
    assert etat.ready_core is True
    assert appels["n"] == 3          # s'est arrêtée dès la preuve, n'a pas épuisé le budget


def test_attente_expire_si_core_jamais_pret():
    def lecteur():
        return _etat(False)          # CORE jamais prêt
    ticks = {"t": 0.0}

    def horloge():
        ticks["t"] += 5.0            # chaque passe consomme 5 s de budget
        return ticks["t"]
    etat = PV.evaluer_avec_attente(lecteur, niveau="core", timeout_s=12.0, intervalle_s=1.0,
                                   horloge=horloge, dormir=lambda _s: None)
    assert etat.ready_core is False and etat.niveau_harvest == PV.STATUT_DATA_NOT_READY


def test_niveau_ok_core_vs_harvest():
    assert PV._niveau_ok(_etat(True), "core") is True
    assert PV._niveau_ok(_etat(False), "core") is False
    # harvest : DEGRADE_DOCUMENTE passe (CORE vivant), DATA_NOT_READY échoue.
    assert PV._niveau_ok(_etat(True, PV.HARVEST_DEGRADE), "harvest") is True
    assert PV._niveau_ok(_etat(False, PV.STATUT_DATA_NOT_READY), "harvest") is False


def test_cli_core_sort_non_zero_sur_racine_vide(tmp_path):
    # aucune source vivante -> READY_CORE faux -> exit 2 (le .cmd ne demarrera pas le moteur).
    code = PV.main([str(tmp_path), "--niveau", "core"])
    assert code == 2


def test_le_cmd_appelle_la_barriere_bloquante_avant_le_moteur():
    txt = CMD.read_text(encoding="utf-8", errors="ignore")
    # La barrière core bloque avec un code non nul, mais passe par :fin afin que le
    # double-clic reste ouvert et affiche la cause au lieu de disparaître.
    assert "--niveau core --attendre" in txt
    bloc = txt.split("DATA_NOT_READY : allMids/BBO/userFills", 1)[1].split("[READY_CORE] OK", 1)[0]
    assert "call :stop_impl" in bloc
    assert 'set "RC=4"' in bloc
    assert "goto :fin" in bloc
    # elle est AVANT le demarrage du moteur/UI (start_hypersmart_simulation.ps1).
    i_barriere = txt.index("--niveau core --attendre")
    i_moteur = txt.index("start_hypersmart_simulation.ps1", i_barriere)
    assert i_barriere < i_moteur
    # ... et l'ancien appel informatif nu (sans --niveau) n'est plus le dernier mot avant le moteur.
    assert "if errorlevel 1 (" in txt[i_barriere:i_moteur]
