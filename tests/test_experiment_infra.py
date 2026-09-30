from hl_observer.research.experiment_infra import (
    RegistreExperiencesSQLite, recompute_descendant, map_deterministe,
    reduce_hors_memoire, CacheNoeudDag)


def test_registre_sqlite_persiste_apres_reouverture(tmp_path):
    p = tmp_path / "essais.db"
    r = RegistreExperiencesSQLite(p)
    r.enregistrer("t1", {"lr": 0.1}, {"pnl": 12.0})
    r.enregistrer("t1", {"lr": 0.1}, {"pnl": 15.0})   # idempotent (remplace)
    r.fermer()
    r2 = RegistreExperiencesSQLite(p)                 # REOUVERTURE
    assert r2.compter() == 1 and r2.lire("t1")["metriques"]["pnl"] == 15.0


def test_recompute_descendant_transitif():
    dep = {"b": ["a"], "c": ["b"], "d": ["a"], "e": ["x"]}
    assert set(recompute_descendant(dep, "a")) == {"b", "c", "d"}


def test_map_deterministe_preserve_l_ordre():
    assert map_deterministe(lambda x: x * x, [1, 2, 3, 4, 5]) == [1, 4, 9, 16, 25]


def test_reduce_hors_memoire_streaming():
    r = reduce_hors_memoire((i for i in range(1000)), lambda acc, m: acc + m, 0)
    assert r["resultat"] == sum(range(1000)) and r["morceaux_traites"] == 1000


def test_cache_noeud_dag_hit():
    c = CacheNoeudDag()
    assert c.obtenir("n1", {"x": 1}) is None
    c.poser("n1", {"x": 1}, 42)
    assert c.obtenir("n1", {"x": 1}) == 42 and c.obtenir("n1", {"x": 2}) is None
