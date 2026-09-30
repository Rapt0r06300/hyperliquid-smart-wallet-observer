"""[LANCEUR item 10] Registre PID RÉEL — arrêt ciblé, zéro orphelin. Prouvé sans Windows (process
injectés). On enregistre les VRAIS PID par signature (cmd/ui/poller/stream), on relit, on détecte les
orphelins d'un run précédent, et on n'arrête QUE les cibles + enfants vérifiés — jamais un étranger.
"""
from __future__ import annotations

from hl_observer.ops import registre_pids as RP


def _procs():
    return [
        {"pid": 100, "ppid": 1, "name": "cmd.exe", "cmd": "cmd /c C:\\x\\LANCER_HYPERSMART.cmd"},
        {"pid": 200, "ppid": 100, "name": "python.exe",
         "cmd": "python -m hl_observer ui --host 127.0.0.1 --port 8794"},
        {"pid": 300, "ppid": 100, "name": "python.exe",
         "cmd": "python -m hl_observer.runtime.persistent_poll_runner"},
        {"pid": 400, "ppid": 100, "name": "powershell.exe", "cmd": "powershell tools\\stream_loop.ps1"},
        {"pid": 500, "ppid": 200, "name": "python.exe", "cmd": "ui worker child"},   # enfant vérifié
        {"pid": 999, "ppid": 1, "name": "python.exe", "cmd": "python C:\\autre\\hl_observer_clone.py"},  # ÉTRANGER
    ]


def test_construire_registre_trouve_les_vrais_pids():
    reg = RP.construire_registre(_procs(), cmd_pid=100, run_id="r1", collecteurs={"bbo-collector": 777})
    comp = reg["composants"]
    assert comp["cmd"]["pid"] == 100 and comp["ui"]["pid"] == 200
    assert comp["poller"]["pid"] == 300 and comp["stream"]["pid"] == 400
    assert reg["collecteurs"]["bbo-collector"] == 777


def test_ecrire_puis_lire_round_trip(tmp_path):
    reg = RP.construire_registre(_procs(), cmd_pid=100, run_id="r2")
    assert RP.ecrire_registre(tmp_path, reg) is True
    relu = RP.lire_registre(tmp_path)
    assert relu["run_id"] == "r2" and relu["composants"]["ui"]["pid"] == 200
    assert (tmp_path / RP.REGISTRE_RELPATH).is_file()


def test_detecter_orphelins_un_collecteur_dun_run_precedent():
    procs = _procs() + [{"pid": 888, "ppid": 1, "name": "cmd.exe",
                         "cmd": "cmd /c tools\\boucle_collecteur.cmd bbo-collector tools\\collecter_bbo.py 5"}]
    reg = RP.construire_registre(procs, cmd_pid=100)            # collecteurs vide -> 888 inconnu
    pids_orph = {o["pid"] for o in RP.detecter_orphelins(procs, RP.pids_enregistres(reg))}
    assert 888 in pids_orph and 999 not in pids_orph           # 999 étranger ne porte pas notre signature


def test_cibles_incluent_enfants_verifies_pas_les_etrangers():
    reg = RP.construire_registre(_procs(), cmd_pid=100)
    cibles = RP.cibles_arret(reg, _procs())
    assert {100, 200, 300, 400, 500}.issubset(cibles)          # composants + enfant vérifié (500<-200)
    assert 999 not in cibles                                   # étranger : jamais


def test_arreter_ne_tue_que_les_cibles(tmp_path):
    RP.ecrire_registre(tmp_path, RP.construire_registre(_procs(), cmd_pid=100))
    tues: list[int] = []
    r = RP.arreter(tmp_path, procs=_procs(), killer=lambda pid: tues.append(pid) or True)
    assert 999 not in tues and 999 not in r["cibles"]
    assert set(r["arretes"]) == set(r["cibles"])
    assert 200 in tues and 500 in tues                         # UI + son enfant vérifié
