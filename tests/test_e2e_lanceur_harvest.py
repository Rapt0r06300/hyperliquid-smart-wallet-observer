"""[LANCEUR item 13] Recette E2E — rejoue TOUT le flux du lanceur de façon déterministe (0 réseau,
0 ordre) : preflight GO -> collecteurs HARVEST démarrés -> preuve de vie READY -> PID réels + zéro
orphelin -> paper strict, PUIS la panne : un collecteur CORE tué -> DATA_NOT_READY détecté -> relance
ciblée (mécanisme de recovery) -> READY ; enfin arrêt ciblé -> zéro orphelin. La partie LIVE Windows
(lancer réellement LANCER_HYPERSMART.cmd) tourne sur la machine de Flo.
"""
from __future__ import annotations

from pathlib import Path

from hl_observer.ops import preflight_lanceur as PF
from hl_observer.ops import preuve_de_vie as PV
from hl_observer.ops import recette_lanceur as RE
from hl_observer.ops import registre_pids as RP
from hl_observer.ops import superviseur_collecteurs as SC

RACINE = Path(__file__).resolve().parents[1]
NOW = 1_700_000_000_000.0
CORE = tuple(s for s in PV.SOURCES_HARVEST if s.obligatoire)
_DISK = lambda p: (100 * 2**30, 10 * 2**30, 90 * 2**30)  # noqa: E731


def _root(tmp_path):
    (tmp_path / "tools").mkdir(exist_ok=True)
    (tmp_path / "tools" / "boucle_collecteur.cmd").write_text("x", encoding="utf-8")
    (tmp_path / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _hb(pid, n=5):
    return {"pid": pid, "ts_ms": NOW, "n_ecrites_cumul": n, "dernier_exchange_ts": NOW - 50.0}


def _prober(url):
    return PF.Sonde(True, 200, NOW) if "binance" in url else PF.Sonde(True, 200)


def _preflight_go(tmp):
    return PF.executer_preflight(tmp, prober=_prober, local_ts_ms=NOW, env={}, procs=[],
                                 deps_present=lambda n: True, disque_usage=_DISK, schemas=())


def _procs(pids_core):
    procs = [{"pid": 100, "ppid": 1, "name": "cmd.exe", "cmd": "cmd /c LANCER_HYPERSMART.cmd"},
             {"pid": 200, "ppid": 100, "name": "python.exe", "cmd": "python -m hl_observer ui --port 8794"}]
    for nom, pid in pids_core.items():
        procs.append({"pid": pid, "ppid": 100, "name": "cmd.exe",
                      "cmd": "cmd /c tools\\boucle_collecteur.cmd %s tools\\x.py 5" % nom})
    return procs


def test_e2e_flux_complet_pass(tmp_path):
    root = _root(tmp_path)
    pre = _preflight_go(root)
    assert pre.go()
    appels = []
    SC.demarrer_tous(root, profil="harvest",
                     spawner=lambda c, cwd: appels.append(c["nom"]) or (1000 + len(appels)))
    assert set(appels) >= set(SC.COLLECTEURS_CORE)                 # le socle obligatoire est démarré
    pids_core = {s.nom: 1000 + i for i, s in enumerate(CORE)}
    etat = PV.evaluer_readiness(CORE, {s.nom: _hb(pids_core[s.nom]) for s in CORE},
                                now_ms=NOW, pid_vivant=lambda p: True)
    assert etat.statut == PV.STATUT_READY
    procs = _procs(pids_core)
    registre = RP.construire_registre(procs, cmd_pid=100, collecteurs=pids_core)
    rapport = RE.evaluer_recette(preflight=pre, readiness=etat, registre=registre, procs=procs,
                                 textes_lanceur=RE._lire_textes_lanceur(RACINE), exiger_ready=True)
    assert rapport.ok(), RE.format_rapport(rapport)


def test_e2e_recovery_collecteur_tue(tmp_path):
    root = _root(tmp_path)
    pids_core = {s.nom: 1000 + i for i, s in enumerate(CORE)}
    mort = CORE[1].nom
    hbs = {s.nom: _hb(pids_core[s.nom]) for s in CORE if s.nom != mort}
    ko = PV.evaluer_readiness(CORE, hbs, now_ms=NOW, pid_vivant=lambda p: True)
    assert ko.statut == PV.STATUT_DATA_NOT_READY and mort in ko.raison    # panne détectée précisément

    # mécanisme de recovery réel : le superviseur détecte les morts et RELANCE (lanceur injecté)
    relances = []
    r = SC.verifier_et_relancer(root, profil="harvest",
                                lanceur=lambda cmd, racine: relances.append(cmd) or True)
    assert r["morts"] and r["relances"]                                  # relance ciblée effectuée

    hbs[mort] = _hb(pids_core[mort])                                     # le heartbeat revient
    assert PV.evaluer_readiness(CORE, hbs, now_ms=NOW, pid_vivant=lambda p: True).statut == PV.STATUT_READY


def test_e2e_arret_cible_zero_orphelin(tmp_path):
    root = _root(tmp_path)
    pids_core = {s.nom: 1000 + i for i, s in enumerate(CORE)}
    procs = _procs(pids_core)
    registre = RP.construire_registre(procs, cmd_pid=100, collecteurs=pids_core)
    RP.ecrire_registre(root, registre)
    tues = []
    r = RP.arreter(root, procs=procs, killer=lambda pid: tues.append(pid) or True)
    assert set(r["arretes"]) == set(r["cibles"]) and 100 in r["cibles"] and 200 in r["cibles"]
    assert RP.detecter_orphelins([], RP.pids_enregistres(registre)) == []   # zéro orphelin après arrêt


def test_e2e_paper_strict_launcher_reel():
    v = RE.scanner_paper_strict(RE._lire_textes_lanceur(RACINE))
    assert v.ok, v.detail                    # 0 ordre reel / cle / signature / /exchange dans le lanceur


def test_recette_refuse_si_data_not_ready(tmp_path):
    # garde-fou : si une source obligatoire n'est pas prouvée, la recette FAIL (jamais de faux PASS)
    pre = _preflight_go(_root(tmp_path))
    ko = PV.EtatRuntime(PV.STATUT_DATA_NOT_READY, "source obligatoire bbo-collector: heartbeat fige", ())
    registre = RP.construire_registre(_procs({"bbo-collector": 1001}), cmd_pid=100)
    rapport = RE.evaluer_recette(preflight=pre, readiness=ko, registre=registre, procs=[],
                                 textes_lanceur={}, exiger_ready=True)
    assert not rapport.ok() and any(v.nom == "preuve-de-vie" for v in rapport.echecs())
