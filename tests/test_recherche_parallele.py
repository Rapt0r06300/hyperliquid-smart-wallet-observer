"""RECHERCHE PARALLÈLE (opt-in, 22/07) — la leçon du blocage tenue par des tests.

Le pool `ProcessPoolExecutor` avait deadlocké (workers non tuables, 0 % CPU, Ctrl-C sans effet,
budget non respecté). Sa remplaçante n'a le droit d'exister QUE si elle ne peut pas rejouer ce
scénario : sous-processus ISOLÉS, sortie en FICHIERS (aucun tube partagé), tuables. Défaut
séquentiel ; le parallèle ne s'active que sur demande explicite.
"""
from __future__ import annotations

import inspect


def test_remplir_en_parallele_lance_chaque_module_et_collecte(tmp_path):
    """Chaque module part dans un VRAI sous-processus et son résultat est collecté. Sur données
    vides : statut honnête (INSUFFISANT), jamais un faux vert."""
    from hl_observer.backtesting.recherche_parallele import remplir_en_parallele
    resultats: dict = {}
    remplir_en_parallele(tmp_path, 5.0, 1, ["carry", "copy"], resultats)
    assert set(resultats) == {"carry", "copy"}
    for r in resultats.values():
        assert isinstance(r, dict) and r.get("statut") in ("INSUFFISANT", "ERREUR")


def test_JAMAIS_de_ProcessPool_dans_la_recherche_parallele():
    """Le cœur de la leçon : plus JAMAIS de ProcessPoolExecutor/multiprocessing (workers non
    tuables). Uniquement des sous-processus isolés avec leur propre session."""
    from hl_observer.backtesting import recherche_parallele as rp
    src = inspect.getsource(rp)
    # on cible l'USAGE réel (import / instanciation), pas le mot cité dans le docstring explicatif
    assert "ProcessPoolExecutor(" not in src, "aucune instanciation du pool qui deadlockait"
    assert "concurrent.futures" not in src and "import multiprocessing" not in src
    assert "Popen(" in src and "start_new_session=True" in src


def test_chercher_toutes_route_vers_le_parallele_SEULEMENT_si_arme(tmp_path, monkeypatch):
    """Le flag (env `TOUT_TESTER_RECHERCHE_PARALLELE=1` ou `parallele=True`) route vers les
    sous-processus ; sinon SÉQUENTIEL (défaut sûr, HUD en direct). On espionne l'aiguillage."""
    import hl_observer.backtesting.recherche_scenario as rs
    appels = {"n": 0}
    def _spy(root, budget, me, modules, resultats):
        appels["n"] += 1
        for m in modules:
            resultats[m] = {"statut": "INSUFFISANT", "strategie": m, "essais": []}
        return resultats
    monkeypatch.setattr(rs, "remplir_en_parallele", _spy)

    monkeypatch.setenv("TOUT_TESTER_RECHERCHE_PARALLELE", "1")
    rs.chercher_toutes(tmp_path, max_essais_par_strategie=1)
    assert appels["n"] == 1, "flag armé -> parallèle emprunté"

    monkeypatch.delenv("TOUT_TESTER_RECHERCHE_PARALLELE", raising=False)
    appels["n"] = 0
    rs.chercher_toutes(tmp_path, max_essais_par_strategie=1)
    assert appels["n"] == 0, "défaut -> séquentiel, jamais le parallèle"
