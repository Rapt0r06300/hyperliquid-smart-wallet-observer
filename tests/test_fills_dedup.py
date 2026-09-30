"""V3 §2.3 — dédup multi-source + fusion des champs autoritatifs."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.following import fills_dedup as D  # noqa: E402


def _f(**kw):
    base = {"user": "0xaa", "coin": "BTC", "sz": 1.0, "px": 100.0, "time": 10, "side": "B",
            "source": "s1", "autoritative": True}
    base.update(kw)
    return base


def test_meme_tid_deux_sources_fusionne_les_champs_complementaires():
    a = _f(tid=42, source="vault_fills_live")
    b = _f(tid=42, start_pos=5.0, source="node_fills_by_block")
    r = D.dedup_merge([a, b])
    assert r.n_uniques == 1 and r.n_fusionnes == 1
    assert r.fills[0]["start_pos"] == 5.0 and r.fills[0]["tid"] == 42


def test_conflit_divergent_est_bloque_et_non_fusionne():
    a = _f(tid=42, source="s1")
    b = _f(tid=42, coin="ETH", source="s2")           # même tid, coin divergent
    r = D.dedup_merge([a, b])
    assert r.n_uniques == 0 and len(r.conflits) == 1
    assert "coin" in r.conflits[0]["champs_divergents"]


def test_un_scalaire_prefere_la_source_autoritative():
    a = _f(tid=7, oid=1, source="node_fills_by_block", autoritative=True)
    b = _f(tid=7, oid=2, source="miroir_non_verifie", autoritative=False)
    r = D.dedup_merge([a, b])
    assert r.n_uniques == 1 and r.fills[0]["oid"] == 1   # autoritative gagne le scalaire


def test_sans_tid_lempreinte_causale_deduplique_et_fusionne():
    a = _f(source="s1")
    b = _f(source="s2", autoritative=False, oid=7)      # même empreinte (pas de tid)
    r = D.dedup_merge([a, b])
    assert r.n_uniques == 1 and r.fills[0].get("oid") == 7


def test_deux_fills_reellement_distincts_ne_fusionnent_pas():
    a = _f(tid=1)
    b = _f(tid=2, sz=2.0, time=11)
    r = D.dedup_merge([a, b])
    assert r.n_uniques == 2 and r.n_fusionnes == 0


def test_une_cle_en_conflit_ne_promeut_plus_aucune_occurrence():
    a = _f(tid=9, source="s1")
    b = _f(tid=9, user="0xbb", source="s2")             # conflit d'identité
    c = _f(tid=9, source="s3")                          # 3e occurrence même clé
    r = D.dedup_merge([a, b, c])
    assert r.n_uniques == 0 and len(r.conflits) >= 1


def test_lordre_de_sortie_est_deterministe():
    fills = [_f(tid=3), _f(tid=1), _f(tid=2), _f(tid=1, start_pos=9.0)]
    r = D.dedup_merge(fills)
    assert [f["tid"] for f in r.fills] == [3, 1, 2]     # 1ʳᵉ apparition de chaque clé
    unifie = next(f for f in r.fills if f["tid"] == 1)
    assert unifie["start_pos"] == 9.0
