import pytest

from hl_observer.research.experiment_infra import (
    RegistreExperiencesSQLite, recompute_descendant, map_deterministe,
    reduce_hors_memoire, CacheNoeudDag)


def test_registre_sqlite_persiste_apres_reouverture(tmp_path):
    p = tmp_path / "essais.db"
    r = RegistreExperiencesSQLite(p)
    first = r.enregistrer("t1", {"lr": 0.1}, {"pnl": 12.0})
    second = r.enregistrer("t1", {"lr": 0.1}, {"pnl": 15.0})
    duplicate = r.enregistrer("t1", {"lr": 0.1}, {"pnl": 15.0})
    assert first["version"] == 1 and second["version"] == 2
    assert duplicate["deduplicated"] is True
    assert [row["version"] for row in r.historique("t1")] == [1, 2]
    assert r.verifier_integrite() == {"ok": True, "checked": 1, "problems": []}
    r.fermer()
    r2 = RegistreExperiencesSQLite(p)                 # REOUVERTURE
    assert r2.compter() == 1 and r2.lire("t1")["metriques"]["pnl"] == 15.0


def test_registre_sqlite_refuse_nan_et_objets_non_json(tmp_path):
    r = RegistreExperiencesSQLite(tmp_path / "essais.db")
    with pytest.raises(ValueError, match="finite JSON"):
        r.enregistrer("nan", {"lr": float("nan")}, {"pnl": 1.0})
    with pytest.raises(ValueError, match="finite JSON"):
        r.enregistrer("object", {"lr": object()}, {"pnl": 1.0})


def test_recompute_descendant_transitif():
    dep = {"b": ["a"], "c": ["b"], "d": ["a"], "e": ["x"]}
    assert set(recompute_descendant(dep, "a")) == {"b", "c", "d"}


def test_map_deterministe_preserve_l_ordre():
    assert map_deterministe(lambda x: x * x, [1, 2, 3, 4, 5]) == [1, 4, 9, 16, 25]


def test_map_deterministe_refuse_un_budget_workers_ambigu():
    with pytest.raises(ValueError, match="positive integer"):
        map_deterministe(lambda x: x, [1], workers=0)
    with pytest.raises(ValueError, match="positive integer"):
        map_deterministe(lambda x: x, [1], workers=True)


def test_cache_dag_refuse_cles_non_reproductibles():
    with pytest.raises(ValueError, match="node_id"):
        CacheNoeudDag.cle("", {"x": 1})
    with pytest.raises(TypeError, match="finite JSON"):
        CacheNoeudDag.cle("n", {"x": float("nan")})


def test_reduce_hors_memoire_streaming():
    r = reduce_hors_memoire((i for i in range(1000)), lambda acc, m: acc + m, 0)
    assert r["resultat"] == sum(range(1000)) and r["morceaux_traites"] == 1000


def test_cache_noeud_dag_hit():
    c = CacheNoeudDag()
    assert c.obtenir("n1", {"x": 1}) is None
    c.poser("n1", {"x": 1}, 42)
    assert c.obtenir("n1", {"x": 1}) == 42 and c.obtenir("n1", {"x": 2}) is None
