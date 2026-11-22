"""La mesure de stabilité doit savoir dire STABLE, INSTABLE, et « rien à mesurer ».

Un instrument qui rend toujours le même verdict ne mesure rien. On lui donne donc des
couvertures FABRIQUÉES dont on connaît la réponse, y compris les deux cas où se cachent les
faux succès : une couverture parfaite (ne doit pas crier au loup) et une absence de données
(ne doit pas être lue comme une couverture nulle).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _chemin in (ROOT / "src", ROOT / "tools"):
    if str(_chemin) not in sys.path:
        sys.path.insert(0, str(_chemin))

import stabilite_couverture_carnets as S  # noqa: E402


def _couverture(tailles: list[int]) -> dict[int, set]:
    """Une couverture synthétique : `tailles[i]` coins distincts à la minute `i`."""
    return {i: {f"COIN{j}" for j in range(t)} for i, t in enumerate(tailles)}


def test_une_couverture_PLATE_est_stable() -> None:
    bilan = S.mesurer(_couverture([70] * 200))
    assert bilan["verdict"] == "STABLE", bilan
    assert bilan["creux"]["nombre"] == 0


def test_un_creux_PLUS_LONG_que_l_horizon_est_nomme() -> None:
    """Le cas qui tue un épisode entier : 90 minutes creuses pour un horizon de 60."""
    bilan = S.mesurer(_couverture([70] * 100 + [5] * 90 + [70] * 100), horizon_min=60)
    assert bilan["verdict"] == "CREUX_PLUS_LONG_QUE_L_HORIZON", bilan
    assert bilan["creux"]["plus_longs_que_l_horizon"] == 1
    assert bilan["creux"]["duree_max_min"] == 90


def test_des_creux_COURTS_donnent_INSTABLE_et_non_le_pire() -> None:
    """Un trou de 20 min sur un horizon de 60 gêne sans avaler un épisode entier."""
    bilan = S.mesurer(_couverture([70] * 100 + [5] * 20 + [70] * 100), horizon_min=60)
    assert bilan["verdict"] == "INSTABLE", bilan
    assert bilan["creux"]["plus_longs_que_l_horizon"] == 0


def test_AUCUNE_minute_nest_pas_une_couverture_nulle() -> None:
    """Le refus qui compte : pas de données ≠ couverture de zéro coin."""
    bilan = S.mesurer({})
    assert bilan["verdict"] == "RIEN_A_MESURER"
    assert "absence de mesure" in bilan["pourquoi"]
    assert "coins_par_minute" not in bilan, "ne pas publier de statistique sans donnee"


def test_la_part_sous_la_moitie_est_chiffree() -> None:
    bilan = S.mesurer(_couverture([100] * 50 + [10] * 50))
    assert bilan["minutes_sous_la_moitie_du_median"] == 50
    assert bilan["part_sous_la_moitie_pct"] == 50.0


def test_le_verdict_dit_ce_quil_ne_prouve_PAS() -> None:
    limite = str(S.mesurer(_couverture([70] * 50)).get("ce_que_ca_ne_prouve_pas") or "")
    assert "verdict economique" in limite.casefold(), limite
    assert "interdit" in limite.casefold(), "dire qu'une couverture trouee INTERDIT le verdict"


def test_les_coins_gardent_leur_identite_NATIVE() -> None:
    """`kPEPE` et `xyz:XYZ100` ne doivent jamais etre mis en majuscules."""
    # ⚠️ Première version AVEUGLE À L'ENVERS : elle cherchait « .upper() » dans tout le corps
    # et attrapait le COMMENTAIRE qui interdit justement l'usage
    # (« identite NATIVE, jamais .upper() »). Le filtre se prenait lui-même — le piège que ce
    # dépôt nomme ailleurs. On lit donc le CODE seul, commentaires retirés.
    import io
    import tokenize

    source = ROOT / "tools" / "stabilite_couverture_carnets.py"
    texte = source.read_text(encoding="utf-8")
    code_seul: list[str] = []
    for jeton in tokenize.generate_tokens(io.StringIO(texte).readline):
        if jeton.type in (tokenize.COMMENT, tokenize.STRING):
            continue                      # ni commentaires, ni docstrings : l'avertissement y vit
        code_seul.append(jeton.string)
    assert "upper" not in code_seul, "une majuscule inventerait des marches inexistants"
