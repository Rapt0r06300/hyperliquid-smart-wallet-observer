"""Ou se perdent les signaux, entre le corpus et un trade mesurable ?

POURQUOI CET OUTIL EXISTE. Le 18 et le 19/11/2026, le labo a rendu **11 391 essais rejetes sur
11 391**, en nommant a chaque fois le candidat (`REJECTED_BY_TRAIN_GATES`) et jamais la cause. Il
a fallu vingt-quatre heures pour decouvrir que le moteur gelé CALCULE deja les compteurs qui
repondent -- `candidate_audit` et `replay_audit`, rendus par `evaluate_frozen_v21_segment` -- et
que le labo les jette. La reponse etait produite a chaque essai, et personne ne la lisait.

Plutot que de les archiver 11 000 fois a l'identique (ils dependent du CORPUS, pas des parametres
cherches, a deux filtres pres), cet outil les rend a la demande, en une passe, pour les trois
segments. Il ne lit que le corpus deja prepare par la phase 1 : aucune ecriture, aucun acces au
coffre, rien qui puisse gener la collecte.

    tools/python/python.exe -X utf8 tools/audit_selection_labo.py .

Ce qu'il a trouve le 19/11/2026, et qui n'etait visible nulle part ailleurs :

  * 4 963 signaux dans TRAIN -> 262 candidats, dont 4 072 ecartes par `NON_ADD_REJECTED` : la
    politique gelee ne copie que les RENFORCEMENTS de position, jamais les ouvertures ;
  * 262 candidats -> **zero trade**, dont 250 pour `L2_CONNECTION_GAP_CROSSED` : les trois carnets
    d'un episode ne partageaient pas la meme connexion, parce que plusieurs lanes observent le
    meme coin en meme temps. Le refus etait juste, la cause etait dans l'alimentation ;
  * trois portes refusent **100 %** des essais, dont deux qu'aucun candidat ne peut franchir :
    `FUNDING_PNL_UNMEASURABLE` (son seul statut acceptant n'est produit par aucune ligne du depot)
    et `INSUFFICIENT_DISTINCT_DAYS` (seuil de 3 journees juge contre un TRAIN de 2,96 jours).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_RACINE = Path(__file__).resolve().parents[1]
for _chemin in (_RACINE / "src", _RACINE):
    if str(_chemin) not in sys.path:
        sys.path.insert(0, str(_chemin))

from hl_observer.backtesting.copy_vault_labo_deux_phases import (  # noqa: E402
    entrees_de_phase_2,
)
from hl_observer.backtesting.copy_vault_local_lab import _PARAMETER_DOMAINS  # noqa: E402
from hl_observer.backtesting.copy_vault_v21_frozen import (  # noqa: E402
    evaluate_frozen_v21_segment,
)
from hl_observer.contrat_paper import PAPER_EQUITY_USD  # noqa: E402
from hl_observer.simulation.economic_freeze_registry import parameter_hash  # noqa: E402

#: Les bornes que le labo a utilisees pour les essais du 19/11. Un decoupage chronologique se
#: RELIT, il ne se devine pas : elles viennent du champ `temporal_windows` des essais archives.
BORNES_PAR_DEFAUT = {
    "train_start_ms": 1794528000000, "train_end_ms": 1794783509999,
    "validation_start_ms": 1794790890000, "validation_end_ms": 1794869909999,
    "oos_start_ms": 1794877290000, "oos_end_ms": 1795035495181,
    "purge_ms": 3690000, "split_unit": "UTC_DAY",
}


def gel_au_contrat(racine: Path, bornes: dict[str, object]) -> dict[str, object]:
    """Le gel V21 ramene au capital du CONTRAT, exactement comme le labo le fait pour sa baseline.

    Le gel porte un notionnel total de 675 USD. Le comparer tel quel a des candidats dotes de
    100 USD mesurerait deux choses differentes : on le met donc a l'echelle, et on recalcule son
    empreinte -- sans quoi `_verified_freeze` leve `COPY_V21_FREEZE_HASH_MISMATCH`, et il a raison.
    """
    chemin = racine / "runtime/codex_research/COPY_V21_PHYSICAL_FREEZE.json"
    brut = json.loads(chemin.read_text(encoding="utf-8"))
    noyau = dict(brut.get("freeze", brut))
    params = dict(noyau["parameters"])
    total = float(params["core_notional_usd"]) + float(params["probe_notional_usd"])
    echelle = min(1.0, PAPER_EQUITY_USD / total) if total > 0 else 1.0
    if echelle < 1.0:
        for cle in ("core_notional_usd", "probe_notional_usd", "daily_profit_lock_usd"):
            params[cle] = float(params[cle]) * echelle
    # LE VERROU DE PROFIT SE NEUTRALISE, comme pour les challengers.
    #
    # Le gel porte `daily_profit_lock_usd = 4 USD`, soit 0,59 USD une fois ramene a 100 USD de
    # capital : la politique cessait de trader des ce gain realise dans la journee. Or le domaine
    # explore par le labo neutralise ce verrou (1 000 000 USD, inatteignable). Comparer des
    # challengers libres a une baseline bridee mesurerait deux regles differentes -- et le contrat
    # demande explicitement de retirer les regles ACTIVES de plafond de profit. Le gel sur disque
    # n'est pas touche : on neutralise a l'usage, et on le dit.
    params["daily_profit_lock_usd"] = max(
        dict(_PARAMETER_DOMAINS)["daily_profit_lock_usd"])
    params["bounds"] = dict(bornes)
    params["bonferroni_trial_count"] = 1
    noyau["parameters"] = params
    noyau["parameters_sha256"] = parameter_hash(params)
    noyau["frozen_at_ms"] = int(bornes["oos_end_ms"]) + 1
    print(f"  gel V21 : notionnel {total:.0f} -> {total * echelle:.0f} USD "
          f"(contrat {PAPER_EQUITY_USD:.0f} USD) · verrou de profit neutralise "
          f"({params['daily_profit_lock_usd']:,.0f} USD)")
    return {"freeze": noyau}


def rendre(segment: str, resultat: dict[str, object]) -> None:
    stats = resultat.get("statistics") or {}
    print(f"\n===== {segment.upper()} =====")
    print(f"  candidats retenus : {resultat.get('candidate_count'):,}")
    for cle, titre in (("candidate_audit", "SELECTION"), ("replay_audit", "REPLAY")):
        compteurs = resultat.get(cle) or {}
        if compteurs:
            print(f"  -- {titre}")
            for nom, valeur in sorted(compteurs.items(), key=lambda kv: -kv[1]):
                print(f"     {valeur:>9,}  {nom}")
    print(f"  trades fermes {stats.get('sample_count')} · journees actives "
          f"{stats.get('distinct_days')} · net {stats.get('net_pnl_usd')}")
    refus = resultat.get("reasons") or []
    print(f"  refus ({len(refus)}) : {', '.join(refus) or '(aucun)'}")


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("workspace", type=Path, nargs="?", default=Path("."))
    parseur.add_argument("--corpus", type=Path, default=None,
                         help="racine des tranches preparees (defaut : runtime/labo_phase1)")
    parseur.add_argument("--min-notionnel", type=float, default=None)
    parseur.add_argument("--bornes", type=Path, default=None,
                         help="JSON de fenetres temporelles ; sinon celles des essais du 19/11")
    parseur.add_argument("--segments", default="train,validation,oos")
    args = parseur.parse_args(argv)

    racine = args.workspace.resolve()
    corpus = args.corpus or (racine / "runtime/labo_phase1")
    if not corpus.is_dir():
        print(f"  Corpus absent : {corpus}")
        print("  Preparez-le d'abord : tools/labo_deux_phases.py . --phase 1")
        return 2
    bornes = dict(BORNES_PAR_DEFAUT)
    if args.bornes:
        bornes.update(json.loads(args.bornes.read_text(encoding="utf-8")))

    metaordres, carnets, audit = entrees_de_phase_2(
        corpus, dire=lambda m: print(f"  {m}"), min_notionnel_leader=args.min_notionnel)
    print(f"\n  corpus : {len(metaordres):,} metaordres causaux, "
          f"{sum(len(v) for v in carnets.values()):,} carnets sur {len(carnets)} coins")
    connexion = audit.get("connexion_unique") or {}
    if connexion:
        print(f"  connexions : {connexion.get('carnets_gardes'):,} gardes, "
              f"{connexion.get('ecartes_connexion_minoritaire'):,} ecartes comme minoritaires")
    gel = gel_au_contrat(racine, bornes)

    for segment in (s.strip() for s in args.segments.split(",") if s.strip()):
        rendre(segment, evaluate_frozen_v21_segment(metaordres, carnets, gel, segment=segment))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
