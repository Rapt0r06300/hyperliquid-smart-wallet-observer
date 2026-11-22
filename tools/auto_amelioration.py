r"""Où en est l'auto-amélioration du moteur ? Lecture seule par défaut.

Le moteur lancé par `LANCER_HYPERSMART.cmd` exécute cette boucle tout seul, toutes les 5 minutes,
dans sa passe périodique (`collecter_userfills_vaults._auto_amelioration_une_passe`). Cet outil
montre ce qu'elle voit et ce qu'elle déciderait — sans rien écrire.

`--appliquer` n'a d'effet que sur une racine de TEST : sous le vrai runtime, seul le moteur a le
droit d'écrire (même règle d'isolation que les cohortes), et l'outil le dit au lieu de forcer.

PAPER. Aucun réseau, aucun ordre.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.experimental import auto_amelioration as AA  # noqa: E402


JOURNAL_DES_FILLS = Path("runtime") / "data" / "fills_journal.jsonl"
QUEUE_OCTETS = 16 * 1024 * 1024


def decisions_sur_les_ouvertures(racine: Path, *, cohorte: str = "RAW_PROBE",
                                 queue_octets: int = QUEUE_OCTETS) -> dict | None:
    """Ce que le bac à sable a répondu aux fills d'OUVERTURE des leaders (fin du journal du moteur).

    « 0 cycle » ne dit rien sans son motif : le 22/11/2026 le bac à sable affichait 0/20 parce que
    22 déclenchements sur 22 étaient refusés `VAULT_NON_SUIVI`. Rend None si le journal est absent
    — on ne fabrique pas un « aucun refus ».
    """
    chemin = Path(racine) / JOURNAL_DES_FILLS
    try:
        with chemin.open("rb") as f:
            taille = f.seek(0, 2)
            f.seek(max(0, taille - queue_octets))
            brut = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    lignes = brut.splitlines()
    if taille > queue_octets:
        lignes = lignes[1:]                              # première ligne coupée par la lecture de queue
    comptes: dict[str, int] = {}
    illisibles = 0
    for ligne in lignes:
        if not ligne.strip():
            continue
        try:
            x = json.loads(ligne)
        except ValueError:
            illisibles += 1
            continue
        if x.get("cohorte") != cohorte or not str(x.get("dir") or "").startswith("Open"):
            continue
        decision = str(x.get("decision") or "INCONNUE")
        comptes[decision] = comptes.get(decision, 0) + 1
    return {"cohorte": cohorte, "ouvertures_vues": sum(comptes.values()), "illisibles": illisibles,
            "par_decision": dict(sorted(comptes.items(), key=lambda kv: (-kv[1], kv[0])))}


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--racine", default=str(RACINE))
    p.add_argument("--appliquer", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    etat = AA.une_passe(Path(args.racine), appliquer=args.appliquer)
    if args.json:
        print(json.dumps(etat, ensure_ascii=False, indent=1))
        return 0
    v = etat["reglage_du_bac_a_sable"]
    print("  AUTO-AMELIORATION DU MOTEUR (papier)")
    print(f"  bac a sable : {v['variante']} — seuil frac_tvl={v['frac_tvl']}, stop {v['stop_bps']:.0f} bps,"
          f" horizon {v['horizon_ms'] / 60000:.0f} min")
    print(f"  echantillon en cours : {etat['cycles_de_la_config_en_vigueur']}/{etat['echantillon']} cycles clotures"
          f" | variantes essayees : {etat['variantes_essayees']}/{etat['variantes_max']}")
    vu = decisions_sur_les_ouvertures(Path(args.racine))
    if vu is None:
        print("  fills d'ouverture des leaders : journal du moteur ABSENT (moteur jamais lance ?)")
    else:
        detail = ", ".join(f"{k} x{n}" for k, n in vu["par_decision"].items()) or "aucun"
        print(f"  fills d'ouverture des leaders vus par le bac a sable : {vu['ouvertures_vues']} -> {detail}")
        print("    (AUCUN = sous le seuil de declenchement ; REFUS:... = declenchement refuse, motif donne)")
    if not etat["verdicts"]:
        print("  aucune variante jugee pour l'instant (aucun echantillon complet)")
    for nom, verdict in etat["verdicts"].items():
        moyenne = "n/d" if verdict["moyenne"] is None else f"{verdict['moyenne']:+.4f}"
        bornes = "n/d" if verdict["bas"] is None else f"[{verdict['bas']:+.4f} ; {verdict['haut']:+.4f}]"
        print(f"    {nom:<46} {verdict['statut']:<11} n={verdict['n']:<3} moyenne {moyenne} USD/cycle {bornes}"
              f"  cumul {verdict['pnl_cumule_usd']:+.4f} USD")
    for nom, promue in etat["cohortes_promues"].items():
        reglage = promue["reglage"].get("variante") or "defauts"
        print(f"  {nom:<16} reglage : {reglage} | cycles sous ce reglage : {promue['cycles']}")
    for action in etat["echelle"]:
        print(f"  ECHELLE : {action['action']} {action['cohorte']} frac_tvl={action['frac_tvl']} — {action['motif']}")
    if etat["cycles_non_attribues"]:
        print(f"  cycles d'etiquette inconnue, attribues a PERSONNE : {etat['cycles_non_attribues']}")
    d = etat["decision"]
    print(f"  DECISION : {d['action']} — {d['motif']}")
    if etat["refus"]:
        print(f"  non appliquee : {etat['refus']} (seul le moteur ecrit sous le vrai runtime)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
