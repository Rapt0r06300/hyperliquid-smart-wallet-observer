"""Un zéro favorable n'est pas une mesure : la couverture des leaders doit REFUSER si elle ne lit pas.

MESURE DU 22/11/2026. `runtime/data/explorer_users_decouverts.json` (schéma
`hypersmart.explorer_users.v1`) déclare `n_users_vus: 430` et porte les 430 adresses sous la clé
**`top_actifs`** (un dict d'adresses `0x…`). Or `_charger_users_explorer` ne cherchait que
`users`, `users_actifs` et `decouverts` : aucune n'existe dans ce schéma. Il rendait donc un
ensemble VIDE, et le rapport affichait :

    "leaders_actifs_vus": 0,  "leaders_actifs_sans_fill": 0,  "echantillon_sans_fill": []

Trois zéros rassurants qui cachaient 430 leaders — et qui, lus comme une mesure, auraient fait
conclure « aucun leader actif n'est sans fill », soit l'inverse exact de ce qu'on ignorait.

Le contrat l'interdit nommément : « Toute donnée absente, périmée ou contradictoire doit
déclencher un refus sûr, jamais un zéro favorable. »
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _chemin in (ROOT / "src", ROOT / "tools"):
    if str(_chemin) not in sys.path:
        sys.path.insert(0, str(_chemin))

import reconcilier_sources as R  # noqa: E402


def test_le_schema_reel_top_actifs_est_lu(tmp_path: Path) -> None:
    """La clé que le dépôt écrit vraiment doit être comprise."""
    p = tmp_path / "users.json"
    p.write_text(json.dumps({
        "schema": "hypersmart.explorer_users.v1", "n_users_vus": 3,
        "top_actifs": {"0xAAA": {"n": 5}, "0xbbb": {"n": 2}, "0xCcC": {"n": 1}},
    }), encoding="utf-8")
    assert R._charger_users_explorer(p) == {"0xaaa", "0xbbb", "0xccc"}


def test_les_clefs_HISTORIQUES_restent_lues(tmp_path: Path) -> None:
    """On ajoute une clé, on n'en retire aucune : d'anciens artefacts existent encore."""
    for clef in ("users", "users_actifs", "decouverts"):
        p = tmp_path / f"{clef}.json"
        p.write_text(json.dumps({clef: ["0xAAA", "0xBBB"]}), encoding="utf-8")
        assert R._charger_users_explorer(p) == {"0xaaa", "0xbbb"}


def test_un_schema_INCONNU_est_REFUSE_et_jamais_rendu_vide(tmp_path: Path) -> None:
    """Le cœur de la leçon : ne pas savoir lire doit se DIRE, pas se taire.

    Un ensemble vide se propage en « 0 leader actif, 0 sans fill » — une affirmation. Le refus,
    lui, nomme les clés trouvées pour qu'on puisse corriger.
    """
    p = tmp_path / "inconnu.json"
    p.write_text(json.dumps({"schema": "autre.v9", "leaders": ["0xAAA"]}), encoding="utf-8")
    with pytest.raises(R.SchemaUsersInconnu) as capture:
        R._charger_users_explorer(p)
    assert "leaders" in str(capture.value), "le refus doit nommer les clefs trouvees"


def test_un_fichier_ABSENT_reste_un_ensemble_vide_sans_refus(tmp_path: Path) -> None:
    """Nuance : « pas de fichier » n'est pas « fichier illisible ».

    Ne pas fournir l'artefact est un choix de l'appelant (la couverture leaders est optionnelle).
    Fournir un artefact qu'on ne sait pas lire est un défaut. Les deux ne doivent pas se
    confondre — c'est la distinction entre une absence et une négation, que ce dépôt applique
    partout ailleurs.
    """
    assert R._charger_users_explorer(tmp_path / "jamais_ecrit.json") == set()


def test_un_JSON_casse_est_REFUSE(tmp_path: Path) -> None:
    p = tmp_path / "casse.json"
    p.write_text("{ ceci n'est pas du json", encoding="utf-8")
    with pytest.raises(R.SchemaUsersInconnu):
        R._charger_users_explorer(p)


def test_le_vrai_artefact_du_depot_est_lisible() -> None:
    """La garde qui aurait attrapé le défaut : lire le fichier RÉEL, pas un double."""
    reel = ROOT / "runtime" / "data" / "explorer_users_decouverts.json"
    if not reel.is_file():
        pytest.skip("artefact explorer absent de ce poste")
    users = R._charger_users_explorer(reel)
    assert users, "le vrai artefact ne doit jamais rendre un ensemble vide"
    declare = json.loads(reel.read_text(encoding="utf-8")).get("n_users_vus")
    if isinstance(declare, int) and declare > 0:
        assert len(users) == declare, "autant d'adresses lues que le fichier en declare"
