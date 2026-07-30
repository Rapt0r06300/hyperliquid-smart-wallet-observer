"""B2 (V3-G) — le sharding CI couvre TOUTE la suite, sous-dossiers compris (dydx_v4/, ui/).

Avant : `base.glob` (non récursif) + reconstruction sur `f.name` → les 54 fichiers `tests/dydx_v4/`
et `tests/ui/` n'étaient dans AUCUN shard (jamais lancés en CI), et deux fichiers homonymes de
dossiers différents se masquaient. Après : `rglob` + chemin relatif préservé.
"""

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import ci_shard as CS  # noqa: E402


def test_couvre_les_sous_dossiers():
    fichiers = CS.fichiers_de_test()
    assert any(f.startswith("tests/dydx_v4/") for f in fichiers), "dydx_v4 doit être shardé"
    assert any(f.startswith("tests/ui/") for f in fichiers), "ui doit être shardé"


def test_partition_reste_valide_et_complete():
    fichiers = CS.fichiers_de_test()
    v = CS.verifier_partition(fichiers, 6)
    assert v["partition_valide"] is True
    # ~1032 fichiers avec les sous-dossiers, contre 977 avant (racine seule)
    assert v["n_fichiers"] >= 1000


def test_aucun_chemin_perdu_ni_aplati():
    fichiers = CS.fichiers_de_test()
    assert len(fichiers) == len(set(fichiers))               # pas de doublon
    assert all(f.startswith("tests/") and f.endswith(".py") for f in fichiers)
