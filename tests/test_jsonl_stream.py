"""FIX-53 — lecture JSONL streaming + comptage mmap + cache par identité de fichier (invalidation sur changement)."""

import json
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import jsonl_stream as JS   # noqa: E402


def _ecrire(p, records):
    p.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")


def test_stream_jsonl_est_paresseux_et_ignore_le_malforme(tmp_path):
    p = tmp_path / "d.jsonl"
    p.write_text('{"a":1}\n\nPAS_DU_JSON\n{"a":2}\n', encoding="utf-8")
    it = JS.stream_jsonl(str(p))
    assert next(it) == {"a": 1}                          # 1er élément sans lire tout le fichier (générateur)
    assert list(it) == [{"a": 2}]                        # vide + ligne malformée ignorées, jamais exploitées
    # reduce_stream replie sans matérialiser
    somme = JS.reduce_stream(str(p), lambda acc, r: acc + r["a"], 0)
    assert somme == 3


def test_compter_lignes_mmap(tmp_path):
    p = tmp_path / "c.jsonl"
    _ecrire(p, [{"i": i} for i in range(7)])             # 7 enregistrements, pas de \n final
    assert JS.compter_lignes(str(p)) == 7
    (tmp_path / "vide.jsonl").write_text("", encoding="utf-8")
    assert JS.compter_lignes(str(tmp_path / "vide.jsonl")) == 0


def test_cache_par_fichier_hit_puis_invalidation(tmp_path):
    p = tmp_path / "f.jsonl"
    _ecrire(p, [{"i": i} for i in range(3)])
    cache = JS.CacheParFichier()
    calls = {"n": 0}

    def calcul():
        calls["n"] += 1
        return JS.compter_lignes(str(p))
    assert cache.obtenir(str(p), "compte", calcul) == 3 and cache.miss == 1
    assert cache.obtenir(str(p), "compte", calcul) == 3 and cache.hits == 1    # fichier inchangé -> pas de recalcul
    assert calls["n"] == 1
    # modifier le fichier -> empreinte différente -> invalidation + recalcul (jamais une valeur périmée)
    time.sleep(0.01)
    _ecrire(p, [{"i": i} for i in range(5)])
    assert cache.obtenir(str(p), "compte", calcul) == 5
    assert cache.invalidations == 1 and calls["n"] == 2
