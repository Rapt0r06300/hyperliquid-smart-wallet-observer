"""La baseline et le candidat se comparent sur le segment le plus profond COMMUN.

LE DEFAUT (20/11/2026). La comparaison appelait `_latest_daily` de CHAQUE cote,
independamment : chacun rendait son segment le plus profond mesure, dans l'ordre
`forward > oos > validation > train`. Deux consequences :

  * un candidat evalue jusqu'au `forward` face a une baseline arretee a `validation` etait
    declare **NON COMPARABLE** -- alors que les deux portaient un chiffre de `validation`
    parfaitement comparable. Le refus n'etait pas prudent, il etait aveugle ;
  * le recu publiait alors `baseline_daily_net_usd` et `candidate_daily_net_usd` issus de
    segments DIFFERENTS, avec un `comparison_segment` qui ne nommait que celui du candidat.
    Deux montants incomparables presentes cote a cote : pire qu'une absence.

CE QUE CA NE CHANGE PAS. L'etat actuel du labo est `CANDIDATE_FROZEN_NOT_COMPARABLE` sur les
9 recus de `HISTORY.jsonl` (25/10/2026), mais pour une AUTRE raison, verifiee : les deux
montants y sont `None` -- aucun segment ne porte de `daily_mean_net_pnl_usd`. Ce correctif ne
rendra donc pas `economically_proven` vrai a lui seul, et il ne le pretend pas.
"""
from __future__ import annotations

from hl_observer.backtesting import copy_vault_local_lab as L


def _segment(valeur):
    return {"daily_mean_net_pnl_usd": valeur}


def test_deux_profondeurs_differentes_se_comparent_sur_le_commun() -> None:
    baseline = {"validation": _segment(1.0), "train": _segment(9.0)}
    candidat = {"forward": _segment(5.0), "validation": _segment(2.0), "train": _segment(8.0)}
    segment, b, c = L._segment_commun_le_plus_profond(baseline, candidat)
    assert segment == "validation", f"segment retenu : {segment}"
    assert (b, c) == (1.0, 2.0), (b, c)


def test_le_plus_profond_commun_est_prefere() -> None:
    baseline = {"oos": _segment(1.0), "validation": _segment(0.5)}
    candidat = {"forward": _segment(9.0), "oos": _segment(2.0), "validation": _segment(0.7)}
    segment, b, c = L._segment_commun_le_plus_profond(baseline, candidat)
    assert segment == "oos", f"`forward` n'est pas commun : {segment}"
    assert (b, c) == (1.0, 2.0)


def test_sans_segment_commun_on_refuse_de_comparer() -> None:
    """La moitie qui compte : ne JAMAIS inventer une comparaison."""
    baseline = {"validation": _segment(1.0)}
    candidat = {"forward": _segment(5.0)}
    assert L._segment_commun_le_plus_profond(baseline, candidat) == (None, None, None)


def test_une_valeur_absente_ou_non_finie_ne_compte_pas() -> None:
    """Fail-closed : `None`, `NaN` et l'infini ne sont pas des mesures."""
    assert L._daily_du_segment({"oos": _segment(None)}, "oos") is None
    assert L._daily_du_segment({"oos": _segment(float("nan"))}, "oos") is None
    assert L._daily_du_segment({"oos": _segment(float("inf"))}, "oos") is None
    assert L._daily_du_segment({"oos": _segment("abc")}, "oos") is None
    assert L._daily_du_segment({}, "oos") is None
    assert L._daily_du_segment({"oos": _segment(0.0)}, "oos") == 0.0


def test_un_zero_mesure_reste_une_mesure() -> None:
    """Un PnL journalier de 0 est un RESULTAT, pas une absence : il doit se comparer."""
    baseline = {"oos": _segment(0.0)}
    candidat = {"oos": _segment(0.0)}
    segment, b, c = L._segment_commun_le_plus_profond(baseline, candidat)
    assert segment == "oos" and (b, c) == (0.0, 0.0)
