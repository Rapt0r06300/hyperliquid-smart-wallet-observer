"""Le socle de la collecte bornee : ecriture atomique, interpreteur, PID, protocoles.

POURQUOI CE FICHIER EXISTE. `ops/bounded_collection_primitives.py` a ete extrait de
`bounded_collection.py` le 21/11/2026 (875 lignes pour un plafond de 800). L'audit l'a
aussitot signale « NOUVEAU MODULE SANS TEST », a juste titre : du code extrait reste couvert
PAR RICOCHET par les tests du parent, jamais en propre.

Ces quatre primitives decident si un collecteur est vivant et sous quel protocole. Se tromper
ici ne casse rien visiblement : ca rend un collecteur mort pour « actif », ou l'inverse.
"""
from __future__ import annotations

import json
from pathlib import Path

from hl_observer.ops.bounded_collection_primitives import (
    _active_collector_protocols,
    _atomic_write,
    _bounded_process_ids,
    resolve_project_python,
)

WRAPPER = "run_bounded_collector.py"


# --------------------------------------------------------------- ecriture atomique
def test_l_ecriture_cree_le_dossier_et_relit_le_meme_contenu(tmp_path: Path):
    cible = tmp_path / "profond" / "etat.json"
    _atomic_write(cible, {"b": 2, "a": 1})
    assert json.loads(cible.read_text(encoding="utf-8")) == {"a": 1, "b": 2}


def test_aucun_fichier_temporaire_ne_survit(tmp_path: Path):
    """Un `.tmp` oublie, c'est un etat a moitie ecrit qu'un lecteur pourra prendre pour vrai."""
    cible = tmp_path / "etat.json"
    _atomic_write(cible, {"a": 1})
    restes = [p.name for p in tmp_path.iterdir() if ".tmp" in p.name]
    assert restes == []


def test_la_reecriture_ne_laisse_jamais_le_fichier_invalide(tmp_path: Path):
    """Deux ecritures de suite : le fichier reste du JSON complet, jamais tronque."""
    cible = tmp_path / "etat.json"
    _atomic_write(cible, {"n": 1})
    _atomic_write(cible, {"n": 2, "detail": "x" * 5000})
    relu = json.loads(cible.read_text(encoding="utf-8"))
    assert relu["n"] == 2 and len(relu["detail"]) == 5000


def test_les_cles_sont_triees_donc_l_ecriture_est_deterministe(tmp_path: Path):
    """Deux etats identiques doivent donner des OCTETS identiques, sinon tout diff ment."""
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    _atomic_write(a, {"z": 1, "a": 2})
    _atomic_write(b, {"a": 2, "z": 1})
    assert a.read_bytes() == b.read_bytes()


# --------------------------------------------------------------- interpreteur du projet
def test_le_runtime_embarque_passe_avant_l_interpreteur_courant(tmp_path: Path):
    """La collecte doit rester PORTABLE : le python du projet d'abord, le systeme en dernier."""
    embarque = tmp_path / "portable_runtime" / "python" / "python.exe"
    embarque.parent.mkdir(parents=True)
    embarque.write_bytes(b"")
    assert resolve_project_python(tmp_path) == embarque.resolve()


def test_une_sauvegarde_sert_de_repli_et_la_plus_recente_gagne(tmp_path: Path):
    """Sans runtime principal, on prend la sauvegarde la PLUS RECENTE, pas n'importe laquelle."""
    for nom in ("python_backup_20260101", "python_backup_20260915"):
        chemin = tmp_path / "portable_runtime" / nom / "python.exe"
        chemin.parent.mkdir(parents=True)
        chemin.write_bytes(b"")
    choisi = resolve_project_python(tmp_path)
    assert choisi.parent.name == "python_backup_20260915"


def test_sans_runtime_embarque_on_retombe_sur_l_interpreteur_courant(tmp_path: Path):
    import sys

    assert resolve_project_python(tmp_path) == Path(sys.executable).resolve()


# --------------------------------------------------------------- PID bornes
def test_les_descendants_du_wrapper_sont_tous_repris():
    """Un PID reutilise par un enfant non reconnu, c'est un collecteur fantome declare actif."""
    processes = [
        {"pid": 10, "ppid": 1, "cmd": f"python {WRAPPER} --coin BTC"},
        {"pid": 11, "ppid": 10, "cmd": "python shim.exe"},
        {"pid": 12, "ppid": 11, "cmd": "python collector.py"},
        {"pid": 99, "ppid": 1, "cmd": "notepad.exe"},
    ]
    assert _bounded_process_ids(processes) == {10, 11, 12}


def test_un_cycle_de_parente_ne_boucle_pas_indefiniment():
    """Une table de processus incoherente ne doit jamais figer le superviseur."""
    processes = [
        {"pid": 10, "ppid": 11, "cmd": f"python {WRAPPER}"},
        {"pid": 11, "ppid": 10, "cmd": "python child"},
    ]
    assert _bounded_process_ids(processes) == {10, 11}


def test_aucun_wrapper_rend_un_ensemble_vide():
    assert _bounded_process_ids([{"pid": 5, "ppid": 1, "cmd": "notepad.exe"}]) == set()


def test_un_pid_non_entier_est_ignore_sans_lever():
    processes = [
        {"pid": None, "ppid": 1, "cmd": f"python {WRAPPER}"},
        {"pid": "7", "ppid": 1, "cmd": f"python {WRAPPER}"},
    ]
    assert _bounded_process_ids(processes) == set()


# --------------------------------------------------------------- protocoles actifs
def _poser_heartbeat(root: Path, nom: str, *, pid: int, ts_ms: int, protocol: str = "ws"):
    dossier = root / "runtime" / "research_lab" / "heartbeats"
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / f"{nom}.json").write_text(
        json.dumps({"pid": pid, "ts_ms": ts_ms, "protocol": protocol}), encoding="utf-8")


def test_un_heartbeat_ecrit_par_un_DESCENDANT_est_accepte(tmp_path: Path):
    """LE CAS QUI MOTIVE CE CODE : sous Windows, un shim s'intercale entre Popen et le collecteur.

    Refuser le heartbeat d'un petit-fils, c'est declarer mort un collecteur qui tourne.
    """
    maintenant = 1_000_000.0
    _poser_heartbeat(tmp_path, "fills", pid=12, ts_ms=int(maintenant * 1000) - 5_000)
    processes = [{"pid": 11, "ppid": 10}, {"pid": 12, "ppid": 11}]
    vus = _active_collector_protocols(tmp_path, {"fills": 10}, processes=processes,
                                      now=maintenant)
    assert vus == {"fills": "ws"}


def test_un_heartbeat_PERIME_est_refuse(tmp_path: Path):
    """Plus de 60 s : la donnee est perimee -> refus, jamais « actif par defaut »."""
    maintenant = 1_000_000.0
    _poser_heartbeat(tmp_path, "fills", pid=10, ts_ms=int(maintenant * 1000) - 61_000)
    assert _active_collector_protocols(tmp_path, {"fills": 10}, processes=[],
                                       now=maintenant) == {}


def test_un_heartbeat_DANS_LE_FUTUR_est_refuse(tmp_path: Path):
    """Un age negatif = horloge incoherente. Une donnee contradictoire ne vaut pas mieux qu'absente."""
    maintenant = 1_000_000.0
    _poser_heartbeat(tmp_path, "fills", pid=10, ts_ms=int(maintenant * 1000) + 30_000)
    assert _active_collector_protocols(tmp_path, {"fills": 10}, processes=[],
                                       now=maintenant) == {}


def test_un_heartbeat_d_un_pid_ETRANGER_est_refuse(tmp_path: Path):
    """Sans ca, un PID recycle par un processus quelconque ressusciterait un collecteur mort."""
    maintenant = 1_000_000.0
    _poser_heartbeat(tmp_path, "fills", pid=777, ts_ms=int(maintenant * 1000))
    assert _active_collector_protocols(tmp_path, {"fills": 10}, processes=[],
                                       now=maintenant) == {}


def test_un_protocole_vide_est_refuse(tmp_path: Path):
    """Un protocole vide n'est pas un protocole : il ne doit pas entrer dans l'inventaire."""
    maintenant = 1_000_000.0
    _poser_heartbeat(tmp_path, "fills", pid=10, ts_ms=int(maintenant * 1000), protocol="   ")
    assert _active_collector_protocols(tmp_path, {"fills": 10}, processes=[],
                                       now=maintenant) == {}


def test_un_heartbeat_illisible_est_ignore_sans_lever(tmp_path: Path):
    dossier = tmp_path / "runtime" / "research_lab" / "heartbeats"
    dossier.mkdir(parents=True)
    (dossier / "fills.json").write_text("{ pas du json", encoding="utf-8")
    assert _active_collector_protocols(tmp_path, {"fills": 10}, processes=[],
                                       now=1_000_000.0) == {}


def test_un_heartbeat_absent_est_ignore_sans_lever(tmp_path: Path):
    assert _active_collector_protocols(tmp_path, {"fills": 10}, processes=[],
                                       now=1_000_000.0) == {}
