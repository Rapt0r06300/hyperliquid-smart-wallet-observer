"""REGISTRE UNIQUE des collecteurs + arrêt CIBLÉ (25/07, Fix 4 & 5) — prouvé sans Windows.

Prouve : (1) une seule source de 17 collecteurs avec métadonnées cohérentes ; (2) démarrage enregistre
les PID ; (3) enregistrer_pids mappe par signature ; (4) status_detaille rend 17 composants ;
(5) arrêt CIBLÉ ne vise QUE les PID enregistrés + signés registre + enfants + port + verrou — et NE TUE
JAMAIS un process étranger (même s'il contient « hl_observer » dans sa ligne de commande).
"""
from __future__ import annotations

import json
from pathlib import Path

from hl_observer.ops import superviseur_collecteurs as SC


def test_registre_19_coherent():
    assert len(SC.REGISTRE) == 19
    noms = [c["nom"] for c in SC.REGISTRE]
    assert len(set(noms)) == len(noms), "noms uniques"
    for c in SC.REGISTRE:                       # limite > 1,5x cadence (règle anti-relance d'un vivant)
        assert c["limite_minutes"] * 60.0 > c["intervalle_s"] * 1.5, c["nom"]
    # les 17 scripts existent sur le disque
    root = Path(__file__).resolve().parents[1]
    for c in SC.REGISTRE:
        assert (root / c["script"]).exists(), c["script"]


def _root(tmp_path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "boucle_collecteur.cmd").write_text("x", encoding="utf-8")
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    return tmp_path


def test_demarrer_tous_enregistre_les_pids(tmp_path):
    root = _root(tmp_path)
    r = SC.demarrer_tous(
        root,
        run_id="run-X",
        profil="all",
        spawner=lambda c, cwd: 1000 + SC.REGISTRE.index(c),
    )
    assert len(r["pids"]) == len(SC.REGISTRE) and r["run_id"] == "run-X"
    reg = json.loads((root / SC.PIDS_RELPATH).read_text(encoding="utf-8"))
    assert reg["run_id"] == "run-X" and len(reg["pids"]) == len(SC.REGISTRE)
    assert reg["pids"]["bbo-collector"] and reg["pids"]["userfills-live"]


def test_demarrer_tous_par_defaut_ne_lance_que_le_core(tmp_path):
    root = _root(tmp_path)
    appels = []
    r = SC.demarrer_tous(
        root,
        run_id="run-core",
        spawner=lambda c, cwd: appels.append(c["nom"]) or (2000 + len(appels)),
    )
    assert r["profil"] == "core"
    assert set(appels) == set(SC.COLLECTEURS_CORE)
    assert r["selectionnes"] == len(SC.COLLECTEURS_CORE)
    assert set(r["pids"]) == set(SC.COLLECTEURS_CORE)


def test_demarrer_tous_reutilise_un_collecteur_deja_vivant(tmp_path):
    root = _root(tmp_path)
    appels = []
    procs = [
        {
            "pid": 321,
            "ppid": 1,
            "name": "python.exe",
            "cmd": "python tools\\collecter_bbo.py",
        }
    ]
    r = SC.demarrer_tous(
        root,
        run_id="run-dedupe",
        profil="core",
        procs=procs,
        spawner=lambda c, cwd: appels.append(c["nom"]) or 999,
    )
    assert r["pids"]["bbo-collector"] == 321
    assert r["reutilises"] == ["bbo-collector"]
    assert appels == ["allmids-collector"]


def test_un_profil_ne_fait_pas_oublier_les_autres_pids_vivants(tmp_path):
    root = _root(tmp_path)
    procs = [
        {
            "pid": 321,
            "ppid": 1,
            "name": "python.exe",
            "cmd": "python tools\\collecter_bbo.py",
        },
        {
            "pid": 654,
            "ppid": 1,
            "name": "python.exe",
            "cmd": "python tools\\ecrire_copy_whitelist.py",
        },
    ]
    SC.demarrer_tous(
        root,
        run_id="run-preserve",
        profil="core",
        procs=procs,
        spawner=lambda c, cwd: 999,
    )
    stored = json.loads((root / SC.PIDS_RELPATH).read_text(encoding="utf-8"))
    assert stored["pids"]["bbo-collector"] == 321
    assert stored["pids"]["copy-whitelist"] == 654
    assert stored["pids"]["allmids-collector"] == 999


def test_enregistrer_pids_mappe_par_signature(tmp_path):
    root = _root(tmp_path)
    procs = [
        {"pid": 100, "ppid": 1, "name": "cmd.exe", "cmd": "cmd /c tools\\boucle_collecteur.cmd bbo-collector tools\\collecter_bbo.py 5"},
        {"pid": 200, "ppid": 1, "name": "python.exe", "cmd": "python tools\\collecter_userfills_vaults.py"},
    ]
    r = SC.enregistrer_pids(root, run_id="run-Y", procs=procs)
    assert r["pids"]["bbo-collector"] == 100
    assert r["pids"]["userfills-live"] == 200


def test_status_detaille_rend_tout_le_registre(tmp_path):
    root = _root(tmp_path)
    st = SC.status_detaille(root)
    assert len(st) == len(SC.REGISTRE)
    assert all(set(s) >= {"nom", "pid_enregistre", "instances", "age_log_min", "etat"} for s in st)


def test_persistant_vivant_par_heartbeat_meme_si_log_fige(tmp_path):
    """FAUX STALL corrigé : un collecteur PERSISTANT (bbo/userfills) écrit la DATA en continu mais pas un
    log par seconde. Sa vie se mesure au HEARTBEAT frais, PAS au log figé -> jamais de faux mort (sinon le
    watchdog dupliquerait un collecteur vivant)."""
    import os
    import time
    (tmp_path / "runtime" / "logs").mkdir(parents=True)
    (tmp_path / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    c = {"nom": "bbo-collector", "limite_minutes": 5.0, "heartbeat": "runtime/data/bbo_heartbeat.json"}
    # log VIEUX (20 min) mais heartbeat FRAIS -> vivant
    log = tmp_path / "runtime" / "logs" / "bbo-collector.log"
    log.write_text("x", encoding="utf-8")
    vieux = time.time() - 20 * 60
    os.utime(log, (vieux, vieux))
    (tmp_path / "runtime" / "data" / "bbo_heartbeat.json").write_text("{}", encoding="utf-8")   # frais
    age = SC.age_vie_minutes(tmp_path, c)
    assert age is not None and age < 1.0, "la vie = heartbeat frais, pas le log fige"
    # heartbeat absent -> repli honnete sur le log (vieux) -> mort
    (tmp_path / "runtime" / "data" / "bbo_heartbeat.json").unlink()
    age2 = SC.age_vie_minutes(tmp_path, c)
    assert age2 is not None and age2 > 15.0, "sans heartbeat, on retombe sur le log (honnete)"


def test_arret_cible_ne_tue_JAMAIS_un_process_etranger(tmp_path):
    """LE test de Fix 5 : un python étranger dont la ligne de commande contient « hl_observer »
    (l'ancien motif large l'aurait tué) N'EST PAS visé. Seuls PID enregistrés + signés + enfants +
    port 8794 + verrou userfills sont ciblés."""
    root = _root(tmp_path)
    (root / SC.PIDS_RELPATH).write_text(json.dumps({"run_id": "r", "pids": {"bbo-collector": 100}}), encoding="utf-8")
    (root / SC.LOCK_USERFILLS).write_text(json.dumps({"pid": 200}), encoding="utf-8")
    procs = [
        {"pid": 100, "ppid": 1, "name": "cmd.exe", "cmd": "cmd /c tools\\boucle_collecteur.cmd bbo-collector tools\\collecter_bbo.py 5"},
        {"pid": 101, "ppid": 100, "name": "python.exe", "cmd": "python tools\\collecter_bbo.py"},         # enfant vérifié
        {"pid": 999, "ppid": 1, "name": "python.exe", "cmd": "python C:\\autre\\hl_observer_clone.py"},   # ÉTRANGER
    ]
    tues: list[int] = []
    r = SC.arreter_cible(root, procs=procs, killer=lambda pid: tues.append(pid) or True, owner=555)
    assert 100 in r["cibles"] and 101 in r["cibles"]       # collecteur signé + son enfant
    assert 200 in r["cibles"]                              # verrou userfills
    assert 555 in r["cibles"]                              # détenteur du port 8794
    assert 999 not in r["cibles"], "un process ETRANGER (hl_observer dans la cmdline) ne doit JAMAIS etre cible"
    assert 999 not in tues
    assert set(r["arretes"]) == set(r["cibles"])           # le killer n'est appelé QUE sur les cibles
