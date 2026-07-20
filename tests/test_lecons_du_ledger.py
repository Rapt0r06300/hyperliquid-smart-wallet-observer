"""LEÇONS DU LEDGER — la boucle « perte → leçon → règle » ne laisse rien passer.

Les trois verdicts possibles d'une perte, et le piège que chacun ferme :
  * EXPLIQUÉE   : cause connue, économie normale — pas d'alarme pour rien ;
  * RÉGRESSION  : cause RÉPARÉE qui revient APRÈS son correctif — la porte a sauté ;
  * INEXPLIQUÉE : motif hors registre — la leçon n'existe pas encore, autopsie due.

Et le méta-piège : un registre qui déclare « réparé » sans commit daté ne peut pas
détecter de régression — l'hygiène du registre est elle-même testée.
"""
from __future__ import annotations

import json
from pathlib import Path

from hl_observer.ops.lecons_du_ledger import (
    CAUSES_CONNUES, VERDICT_EXPLIQUEE, VERDICT_INEXPLIQUEE, VERDICT_REGRESSION,
    classer_perte, lecons, resume_markdown,
)

T_REPARE_SHORTLIST = 1784460540000          # 19/07 13:29 (registre)


def _ledger(root: Path, lignes: list[dict]) -> None:
    p = root / "runtime" / "data" / "carry_paper_ledger.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(l) for l in lignes) + "\n", encoding="utf-8")


def test_une_perte_ATTENDUE_est_expliquee_sans_alarme():
    v, note = classer_perte("SORTIE_LIQUIDATION", 2_000_000_000_000)
    assert v == VERDICT_EXPLIQUEE and "risque" in note


def test_une_cause_REPAREE_qui_revient_APRES_le_correctif_est_une_REGRESSION():
    """LE COEUR : le churn shortlist a ete repare le 19/07 13:29. Une perte a ce motif
    APRES cette date signifie que la porte a saute — alarme, pas haussement d'epaules."""
    v, note = classer_perte("COIN_PLUS_DANS_SHORTLIST", T_REPARE_SHORTLIST + 1)
    assert v == VERDICT_REGRESSION and "586b466" in note
    # ... et AVANT le correctif, c'etait la vieille epoque : expliquee, pas une regression.
    v_avant, _ = classer_perte("COIN_PLUS_DANS_SHORTLIST", T_REPARE_SHORTLIST - 1)
    assert v_avant == VERDICT_EXPLIQUEE


def test_un_motif_HORS_REGISTRE_exige_une_autopsie():
    v, note = classer_perte("MOTIF_JAMAIS_VU", 2_000_000_000_000)
    assert v == VERDICT_INEXPLIQUEE and "autopsie" in note


def test_les_GAINS_n_ont_pas_besoin_d_excuse(tmp_path):
    _ledger(tmp_path, [
        {"kind": "CLOSE", "coin": "PURR", "ts_ms": 10, "realized_net_pnl_usdc": 0.5,
         "reason": "BASE_CONVERGEE_PREMIUM_CAPTURE"},
        {"kind": "OPEN", "coin": "PURR", "ts_ms": 5},
    ])
    r = lecons(tmp_path)
    assert r["expliquees"] == r["regressions"] == r["inexpliquees"] == []


def test_le_rapport_met_les_alarmes_en_ROUGE_et_reste_calme_sinon(tmp_path):
    _ledger(tmp_path, [
        {"kind": "CLOSE", "coin": "HYPE", "ts_ms": T_REPARE_SHORTLIST + 10,
         "realized_net_pnl_usdc": -0.17, "reason": "COIN_PLUS_DANS_SHORTLIST"},
        {"kind": "CLOSE", "coin": "PURR", "ts_ms": T_REPARE_SHORTLIST + 20,
         "realized_net_pnl_usdc": -0.05, "reason": "MOTIF_MYSTERE"},
    ])
    md = "\n".join(resume_markdown(tmp_path))
    assert "RÉGRESSION" in md and "INEXPLIQUÉE" in md and "🔴" in md
    md_vide = "\n".join(resume_markdown(tmp_path, depuis_ms=T_REPARE_SHORTLIST + 100))
    assert "Aucune perte" in md_vide


def test_HYGIENE_du_registre_un_REPARE_sans_commit_date_ne_peut_pas_exister():
    """Un 'répare' sans commit ni date est une promesse invérifiable — le registre se
    verrouille lui-même : pas d'entree REPARE sans les deux."""
    for motif, e in CAUSES_CONNUES.items():
        if e["statut"] == "REPARE":
            assert e.get("commit") and int(e.get("repare_ts_ms") or 0) > 0, motif
        else:
            assert e["statut"] == "ATTENDU", motif
        assert e.get("note"), "chaque cause porte sa leçon en une phrase: %s" % motif


def test_jamais_d_exception_sur_racine_morte(tmp_path):
    assert lecons(tmp_path / "nulle_part")["expliquees"] == []
