#!/usr/bin/env python3
"""G1 -- LA RECHERCHE 150 M LIT-ELLE LE FUTUR ? On TORTURE les donnees, on ne lit pas le code.

On prend la VRAIE fonction de selection de la recherche (`scenario_search._eval_pairs`, via un
scenario reel), et on la rappelle avec un futur DETRUIT de trois facons. Si l'ensemble des
candidats acceptes bouge d'un seul element : FUITE.

On mesure AUSSI le biais de SURVIVANCE de `prefilter_candidates` -- qui, lui, utilise
legitimement le futur ("garder les candidats mesurables"), mais qu'il faut CHIFFRER et non
passer sous silence.

Lecture seule. Aucun ordre, aucune cle, aucune signature.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting.ab_flag_replay import load_jsonl, marks_by_coin  # noqa: E402
from hl_observer.backtesting.lookahead_differential import (  # noqa: E402
    selection_invariante_au_futur,
)
from hl_observer.backtesting.scenario_grid import generate  # noqa: E402
from hl_observer.backtesting.scenario_search import _eval_pairs, _config_for  # noqa: E402

REPLAY = RACINE / "runtime" / "replay"
MAX_CANDIDATS = 4000


def _selecteur(sc):
    """La VRAIE selection d'entree de la recherche. Rend les candidats ACCEPTES (pas le PnL).

    On rejoue exactement les 7 filtres de `_eval_pairs`, mais en gardant le candidat au lieu du
    PnL -- et on garde `simulate_exit_on_path` dans la boucle, car c'est LUI qui recoit `marks`.
    Si la selection depend du futur, c'est par la que ca passerait.
    """
    cfg = _config_for(sc)
    hz = float(sc.horizon_min)
    min_edge = float(sc.min_edge_bps)
    base_cost = float(sc.cost_bps)
    max_age = float(getattr(sc, "max_signal_age_ms", 0.0) or 0.0)
    min_liq = float(getattr(sc, "min_liquidity_score", 0.0) or 0.0)
    if min_liq > 1.0:
        min_liq /= 100.0
    min_cons = int(getattr(sc, "min_consensus_wallets", 1) or 1)
    max_deg = float(getattr(sc, "max_copy_degradation_bps", 0.0) or 0.0)
    min_ls = float(getattr(sc, "min_leader_score", 0.0) or 0.0)
    side_mode = str(getattr(sc, "side_mode", "both") or "both")

    def selectionner(candidats, marks):
        # On rejoue la MEME logique, mais on rend le CANDIDAT. Un dict par (coin, ts) suffit :
        # _eval_pairs rend (coin, pnl) ; on refait la boucle des filtres a l'identique.
        acceptes = []
        for c in candidats:
            paires = list(_eval_pairs(
                [c], marks, cfg, hz, min_edge, base_cost, 500.0,
                max_age, min_liq, min_cons, max_deg, min_ls, side_mode,
            ))
            if paires:
                acceptes.append(c)
        return acceptes

    return selectionner


def main() -> int:
    cands = []
    for f in sorted(REPLAY.rglob("candidates*.jsonl")):
        cands.extend(load_jsonl(f))
        if len(cands) >= MAX_CANDIDATS:
            break
    cands = [c for c in cands if str(c.get("coin") or "")][:MAX_CANDIDATS]

    mark_rows = []
    for f in sorted(REPLAY.rglob("marks*.jsonl")):
        mark_rows.extend(load_jsonl(f))
    marks = marks_by_coin(mark_rows)

    print("=" * 78)
    print(" G1 -- LA RECHERCHE LIT-ELLE LE FUTUR ? (test DIFFERENTIEL, pas une lecture de code)")
    print("=" * 78)
    print()
    print(f"  candidats testes : {len(cands):>7}")
    print(f"  marches marques  : {len(marks):>7}")
    print()

    if not cands or not marks:
        print("  INSUFFICIENT_DATA -- c'est un fait, pas une panne.")
        return 0

    # On teste plusieurs scenarios REELS de la grille -- pas un scenario invente.
    scenarios = list(generate())[:12]
    print(f"  scenarios de la VRAIE grille : {len(scenarios)}")
    print()
    print("-" * 78)
    print(f"  {'scenario':<10} {'candidats':>10} {'acceptes':>9} {'FUTUR_BROUILLE':>15} "
          f"{'FUTUR_EFFACE':>13} {'FUTUR_INVERSE':>14}")
    print("-" * 78)

    # 🚩 LA DISTINCTION QUE MON PREMIER OUTIL RATAIT.
    #
    # Il criait « FUITE » des qu'UNE torture faisait bouger la selection. Faux -- et faux dans
    # le sens qui fait paniquer. Les trois tortures ne disent PAS la meme chose :
    #
    #   BROUILLE / INVERSE : le futur EXISTE mais il MENT (bruit, ou chemin retourne).
    #       -> si la selection change, elle a LU ce futur. C'est du LOOKAHEAD. Fatal.
    #
    #   EFFACE : le futur N'EXISTE PLUS.
    #       -> la selection change forcement : sans prix futur, il n'y a pas de PnL a mesurer
    #          (simulate_exit_on_path rend None). Ce n'est pas de la triche, c'est de la
    #          MESURABILITE. Un trade dont on ne connaitra jamais l'issue n'est pas evaluable.
    #          Ca s'appelle de la SURVIVANCE, et il faut la CHIFFRER, pas la confondre.
    #
    # Un outil qui melange les deux fabrique une fausse alarme. On s'est deja fait avoir
    # (l'audit qui contaminait ses propres tests, 12/07). On ne recommence pas.
    lookahead = 0
    survivance_totale = 0
    acceptes_total = 0
    details = []
    for i, sc in enumerate(scenarios):
        v = selection_invariante_au_futur(_selecteur(sc), cands, marks)
        b = v.ecarts.get("FUTUR_BROUILLE", 0)
        e = v.ecarts.get("FUTUR_EFFACE", 0)
        r = v.ecarts.get("FUTUR_INVERSE", 0)
        fuite = (b > 0) or (r > 0)          # <-- SEULS ceux-la sont du lookahead
        if fuite:
            lookahead += 1
            details.append(v.as_dict())
        survivance_totale += e
        acceptes_total += v.acceptes_reel
        pct = (100.0 * e / v.acceptes_reel) if v.acceptes_reel else 0.0
        print(f"  #{i:<9} {v.n_candidats:>10} {v.acceptes_reel:>9} "
              f"{(str(b) if b else 'OK'):>15} {(str(e) if e else '0'):>13} "
              f"{(str(r) if r else 'OK'):>14}   "
              f"{'LOOKAHEAD !' if fuite else f'survivance {pct:.0f}%'}")

    print("-" * 78)
    print()
    print("  " + "=" * 74)
    print("   VERDICT -- DEUX QUESTIONS DIFFERENTES, DEUX REPONSES")
    print("  " + "=" * 74)
    print()
    print("   1) LOOKAHEAD : la selection LIT-ELLE le futur ?")
    if lookahead == 0:
        print("      >>> NON. Sur les 12 scenarios reels, on peut BROUILLER le futur (bruit)")
        print("          ou l'INVERSER (le prix fait exactement le contraire) : la recherche")
        print("          accepte EXACTEMENT les memes candidats. Elle ne le lit pas.")
        print()
        print("          Le garde-fou par timestamps (`assert_no_lookahead`) aurait passe")
        print("          TRIVIALEMENT ici (data_ts == decision_ts par construction) -- il")
        print("          n'aurait rien prouve. Le brancher aurait ete du THEATRE.")
        print()
        print("          CONSEQUENCE : « 0 config robuste sur 150 M » n'est PAS un artefact de")
        print("          lookahead. Ce resultat TIENT. La cause est ailleurs (voir H-181 :")
        print("          on teste les configs qui sur-ajustent le plus).")
    else:
        print(f"      >>> OUI -- {lookahead} scenario(s). Brouiller ou inverser le futur CHANGE")
        print("          la selection. Tous les resultats de recherche sont a jeter.")
        for d in details[:3]:
            for ex in d["exemples"]:
                print(f"          {ex}")
    print()
    pct_g = (100.0 * survivance_totale / acceptes_total) if acceptes_total else 0.0
    print("   2) SURVIVANCE : combien de trades ne sont evaluables QUE parce qu'un mark futur")
    print("      a ete enregistre ?")
    print(f"      >>> {pct_g:.0f} % des candidats acceptes disparaissent si on efface le futur.")
    print()
    print("          Ce n'est PAS du lookahead : sans prix futur, il n'y a pas de PnL a mesurer.")
    print("          Mais c'est un BIAIS REEL, et il faut le dire : la recherche ne juge que les")
    print("          signaux qui ont EU la chance d'etre suivis par un mark. Les marches peu")
    print("          marques sont silencieusement absents.")
    print("          Attenuation : le filtre est SCENARIO-INDEPENDANT et s'applique a l'identique")
    print("          au train ET au test -- il ne peut donc pas fabriquer un faux gagnant OOS.")
    print()

    sortie = RACINE / "data" / "reports" / "g1_lookahead_differentiel.json"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps({
        "candidats": len(cands),
        "scenarios": len(scenarios),
        "lookahead_scenarios": lookahead,
        "lookahead": lookahead > 0,
        "survivance_pct": round(pct_g, 2),
        "note": ("BROUILLE/INVERSE => lookahead (fatal). EFFACE seul => survivance de "
                 "mesurabilite (attendu, chiffre, applique identiquement train/test)."),
        "details": details,
    }, indent=2), encoding="utf-8")
    print(f"  rapport : {sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
