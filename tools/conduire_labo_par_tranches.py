#!/usr/bin/env python3
"""CONDUIRE LE LABO PAR TRANCHES : six journées lues l'une après l'autre, jamais ensemble.

POURQUOI. Le labo chargeait tout le corpus à l'étape 2 : 31,8 Go de fills (8 464 251 lignes à
3 754 octets) et 20,4 Go de carnets (7 527 878 à 2 713), ce qui faisait couper l'enveloppe du
rejeu pour mémoire critique. `run_local_campaign` sait désormais travailler sur une tranche ; cet
outil l'appelle une fois par tranche et combine les rapports par `agregation_tranches`.

DEUX CHOSES QU'IL NE FAIT PAS, VOLONTAIREMENT :

* il ne découpe pas par journée calendaire. Les six journées du corpus sont très inégales — le
  13/11 porte 2 172 496 fills contre 476 078 le 18/11, soit 4,6 fois plus — et la plus dense
  demanderait ~7 Go de fills plus ~4,8 Go de carnets. Le découpage suit donc la DENSITÉ RÉELLE du
  ruban, mesurée en flux avant de commencer, avec un budget de lignes par tranche ;
* il ne fabrique aucun total. Une tranche dont le labo ne rend rien laisse l'agrégat NON
  EXPLOITABLE, avec sa raison. C'est `agregation_tranches` qui porte ce refus, et il est testé là.

PAPER / LECTURE SEULE : aucune requête réseau, aucun ordre, aucune écriture hors du rapport.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import agregation_tranches as AG  # noqa: E402

SCHEMA = "hypersmart.conduite_labo_tranches.v1"

#: Le ruban dont la densité décide du découpage : c'est lui qui pèse le plus (7,12 Go mesurés).
RUBAN_FILLS = Path("runtime") / "data" / "vault_fills_live.jsonl"

#: Lignes de fills par tranche. 500 000 lignes ont été mesurées à 1,54 Go de pic pour l'étape 2
#: (476 078 fills retenus le 18/11), carnets non compris : c'est un budget prudent sur une machine
#: où la RAM libre tourne autour de 10 Go.
BUDGET_LIGNES = 500_000

#: Granularité du découpage. Descendre sous l'heure ne sert à rien ici : la détention médiane des
#: leaders est de ~47 min, donc une tranche plus courte couperait la plupart des épisodes.
PAS_MS = 3_600_000

_TS = re.compile(rb'"ts_ms":\s*(\d+)')


def densite_par_pas(ruban: Path, *, pas_ms: int = PAS_MS) -> dict[int, int]:
    """Combien de fills dans chaque pas de temps, lu EN FLUX (32 s pour 7,12 Go).

    On mesure avant de découper, parce que le corpus est inégal : supposer une densité uniforme
    ferait une tranche de 7 Go le 13/11 et une de 1,5 Go le 18/11.
    """
    compte: dict[int, int] = {}
    try:
        flux = ruban.open("rb")
    except OSError:
        return compte
    with flux:
        for ligne in flux:
            trouve = _TS.search(ligne)
            if trouve is None:
                continue
            seau = int(trouve.group(1)) // pas_ms * pas_ms
            compte[seau] = compte.get(seau, 0) + 1
    return compte


def decouper(
    densite: Mapping[int, int], *, budget: int = BUDGET_LIGNES, pas_ms: int = PAS_MS
) -> list[tuple[int, int]]:
    """Des tranches CONTIGUËS dont aucune ne dépasse le budget, sauf un pas indivisible.

    Les tranches se touchent sans se recouvrir (`fin + 1 == debut` de la suivante), ce que
    `agregation_tranches.couverture` vérifie ensuite : un trou laisserait croire qu'une période vaut
    zéro, un recouvrement compterait deux fois les mêmes signaux.

    Un pas seul au-dessus du budget n'est pas découpé plus fin : on le rend tel quel et l'appelant
    verra sa taille. Le casser en deux séparerait des fills que la reconstruction doit voir
    ensemble, et ce serait un mensonge plus coûteux qu'une tranche lourde.
    """
    if not densite:
        return []
    seaux = sorted(densite)
    tranches: list[tuple[int, int]] = []
    debut = seaux[0]
    cumul = 0
    for seau in seaux:
        lignes = int(densite[seau])
        if cumul and cumul + lignes > budget:
            tranches.append((debut, seau - 1))
            debut, cumul = seau, lignes
        else:
            cumul += lignes
    tranches.append((debut, seaux[-1] + pas_ms - 1))
    return tranches


def _jour(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d %H:%M")


def conduire(
    workspace: Path,
    tranches: Sequence[tuple[int, int]],
    *,
    lancer: Callable[[Path, tuple[int, int]], Mapping[str, Any]],
    additifs: Sequence[str] = (),
    ratios: Sequence[tuple[str, str]] = (),
    journal: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Appelle `lancer` une fois par tranche, puis combine. Un échec ne devient jamais un zéro.

    `lancer` est injecté pour que la conduite soit testable sans corpus. Si une tranche lève, elle
    est consignée avec son type d'erreur et ne produit PAS de rapport : l'agrégat sera donc déclaré
    non exploitable, ce qui est le résultat juste.
    """
    dire = journal or (lambda _m: None)
    rapports: list[Mapping[str, Any]] = []
    incidents: list[dict[str, Any]] = []
    for index, tranche in enumerate(tranches, start=1):
        dire(f"[{index}/{len(tranches)}] {_jour(tranche[0])} → {_jour(tranche[1])}")
        depart = time.time()
        try:
            rapport = lancer(workspace, tranche)
        except Exception as exc:                      # noqa: BLE001 — consigné, jamais avalé
            incidents.append({
                "tranche": list(tranche), "index": index,
                "erreur": type(exc).__name__, "message": str(exc)[:300],
            })
            dire(f"      ÉCHEC {type(exc).__name__} — cette tranche n'aura pas de rapport")
            continue
        if not isinstance(rapport, Mapping):
            incidents.append({
                "tranche": list(tranche), "index": index,
                "erreur": "RAPPORT_NON_LISIBLE", "message": type(rapport).__name__,
            })
            continue
        rapports.append({**rapport, "tranche": list(tranche)})
        dire(f"      {rapport.get('status', '?')} en {time.time() - depart:.0f} s")
    agregat = AG.combiner(rapports, tranches=tranches, additifs=additifs, ratios=ratios)
    return {
        "schema": SCHEMA,
        "tranches": [list(t) for t in tranches],
        "incidents": incidents,
        "agregat": agregat,
        "rapports": rapports,
        "paper_read_only": True,
        "real_execution": False,
    }


def _lanceur_reel(max_trials: int, campaign_root: Path | None, repository_root: Path):
    """Le vrai appel au labo, isolé ici pour que `conduire` reste testable sans lui."""
    from hl_observer.backtesting.copy_vault_local_lab import run_local_campaign

    def lancer(workspace: Path, tranche: tuple[int, int]) -> Mapping[str, Any]:
        return run_local_campaign(
            workspace, tranche=tranche, max_trials=max_trials,
            campaign_root=campaign_root, repository_root=repository_root,
        )

    return lancer


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("workspace", help="le workspace matérialisé par le labo")
    p.add_argument("--budget", type=int, default=BUDGET_LIGNES,
                   help=f"lignes de fills par tranche (défaut {BUDGET_LIGNES:,})")
    p.add_argument("--pas-heures", type=int, default=1, help="granularité du découpage")
    p.add_argument("--max-trials", type=int, default=1)
    p.add_argument("--plan-seulement", action="store_true",
                   help="mesurer et afficher le découpage, sans lancer le labo")
    p.add_argument("--sortie", default="")
    args = p.parse_args(argv)

    workspace = Path(args.workspace).resolve()
    pas = max(1, args.pas_heures) * 3_600_000
    ruban = workspace / RUBAN_FILLS
    print(f"  mesure de la densité de {ruban.name}…", flush=True)
    depart = time.time()
    densite = densite_par_pas(ruban, pas_ms=pas)
    total = sum(densite.values())
    if not densite:
        print(f"  AUCUN FILL LISIBLE dans {ruban} — rien à conduire, et ce n'est pas un zéro.")
        return 2
    tranches = decouper(densite, budget=args.budget, pas_ms=pas)
    print(f"  {total:,} fills sur {len(densite)} pas de {args.pas_heures} h, "
          f"lus en {time.time() - depart:.0f} s")
    print(f"  → {len(tranches)} tranches (budget {args.budget:,} lignes) :")
    for index, (debut, fin) in enumerate(tranches, start=1):
        lignes = sum(n for seau, n in densite.items() if debut <= seau <= fin)
        marque = "  ⚠ au-dessus du budget" if lignes > args.budget else ""
        print(f"     {index:>2}. {_jour(debut)} → {_jour(fin)}  {lignes:>9,} fills{marque}")
    couverture = AG.couverture(tranches)
    print(f"  couverture : continue={couverture['continue']} "
          f"étendue={couverture['etendue_ms'] / 3_600_000:.1f} h")
    if args.plan_seulement:
        return 0

    resultat = conduire(
        workspace, tranches,
        lancer=_lanceur_reel(args.max_trials, workspace.parent / "campagne-tranches", RACINE),
        additifs=("net_pnl_usd", "entries", "metaorders", "candidates_tested"),
        ratios=(("temporally_aligned_add_signals", "entries"),),
        journal=lambda message: print(message, flush=True),
    )
    agregat = resultat["agregat"]
    print(f"\n  VERDICT GLOBAL : {agregat['verdict']['status']} "
          f"(exploitable={agregat['exploitable']})")
    if not agregat["exploitable"]:
        print(f"  non exploitable : {agregat.get('raison_non_exploitable')}")
    print(f"  jours UTC distincts (union) : {agregat['jours']['distincts']}")
    if resultat["incidents"]:
        print(f"  {len(resultat['incidents'])} tranche(s) sans rapport :")
        for incident in resultat["incidents"]:
            print(f"     {_jour(incident['tranche'][0])} — {incident['erreur']}")
    if args.sortie:
        destination = Path(args.sortie)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with open(destination, "w", encoding="utf-8", newline="") as flux:
            json.dump(resultat, flux, ensure_ascii=False, indent=2, default=str)
        print(f"\n  rapport : {destination}")
    return 0 if agregat["exploitable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
