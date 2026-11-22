"""SONDE : le labo peut-il former son split, si on ne garde que les HORODATAGES des carnets ?

LA CONTRADICTION QU'ELLE INSTRUIT, mesuree des deux cotes :

```
le split exige >= 6 journees UTC distinctes DANS UNE SEULE tranche (`_bounds`, plancher 3)
la memoire     n'en tient qu'environ UNE : 24,2 Go de RSS pour 8 jours (22/11/2026),
               ~28 Go pour 6 jours denses (docstring de `load_observed_books`, 18/11/2026)
```

POURQUOI UNE SONDE, ET PAS UN CORRECTIF. L'appariement du labo
(`copy_vault_signal_alignment.evaluable_signals`) tient en six lignes et ne lit **qu'un seul
champ** de chaque carnet :

    for row in metaorders:
        stamps = horloges.get(row["coin"])          # <- uniquement des ts_ms
        index = bisect.bisect_right(stamps, signal_ms) - 1
        if index < 0 or signal_ms - stamps[index] > max_book_age_ms:
            continue

Or c'est le CONTENU des carnets qui coute la memoire : 32,7 M lignes x ~700 o en dicts Python
= 23 Go, ce qui explique exactement le RSS de 24,2 Go mesure. Les memes horodatages dans un
`array('q')` de 8 octets tiennent dans **0,26 Go**, soit ~90x moins.

Cette sonde MESURE cette hypothese sans toucher au labo : elle lit les rubans de carnets en
flux, ne garde que `(coin, ts_ms)`, puis demande aux VRAIES fonctions du labo si le split se
formerait. Elle n'ecrit rien, ne decide rien, et ne remplace aucun chemin de production.

LECTURE SEULE, aucun reseau, aucun ordre. Le resultat est un refus ou des chiffres, jamais un
zero favorable : un ruban absent est annonce comme absent.
"""
from __future__ import annotations

import argparse
import array
import bisect
import json
import re
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import diagnostic_signal as DS  # noqa: E402
from hl_observer.backtesting.copy_vault_local_lab import _bounds  # noqa: E402
from hl_observer.backtesting.copy_vault_signal_alignment import (  # noqa: E402
    MAX_BOOK_AGE_MS,
    MIN_SIGNALS_PER_DAY,
)

#: Rubans de carnets lus par le labo, dans l'ordre de `load_observed_books`.
RUBANS_CARNETS = (
    "runtime/data/copy_vault_l2_tape.jsonl",
    "runtime/data/copy_vault_bbo_tape.jsonl",
    "runtime/data/carnet_venues.jsonl",
)
RUBAN_FILLS = "runtime/data/vault_fills_live.jsonl"

#: Extraction par regex plutot que `json.loads` sur chaque ligne : 7 Go de L2 passent ainsi en
#: quelques minutes au lieu de dizaines. La sonde n'a besoin que de deux champs ; un parse
#: complet couterait le temps ET la memoire qu'on cherche justement a mesurer.
_TS = re.compile(rb'"(?:ts_ms|received_at_ms|observed_at_ms)"\s*:\s*(\d{10,16})')
_COIN = re.compile(rb'"coin"\s*:\s*"([^"]{1,24})"')
_SIGNAL_TS = re.compile(rb'"signal_ts_ms"\s*:\s*(\d{10,16})')
_ACTION = re.compile(rb'"action"\s*:\s*"([^"]{1,16})"')


def horloges_des_carnets(
    racine: Path, *, rubans: tuple[str, ...] = RUBANS_CARNETS, borne_min_ms: int = 0,
    borne_max_ms: int | None = None,
) -> tuple[dict[str, array.array], dict[str, object]]:
    """`{coin: array('q') d'horodatages tries}` + un audit de ce qui a ete lu ou refuse."""
    horloges: dict[str, array.array] = {}
    lues = retenues = sans_coin = sans_ts = 0
    absents: list[str] = []
    depart = time.time()
    for relatif in rubans:
        chemin = racine / relatif
        if not chemin.is_file():
            absents.append(relatif)
            continue
        with chemin.open("rb") as flux:
            for ligne in flux:
                lues += 1
                t = _TS.search(ligne)
                if t is None:
                    sans_ts += 1
                    continue
                c = _COIN.search(ligne)
                if c is None:
                    sans_coin += 1
                    continue
                ts = int(t.group(1))
                if ts < borne_min_ms or (borne_max_ms is not None and ts > borne_max_ms):
                    continue
                coin = c.group(1).decode("ascii", errors="replace").upper()
                horloges.setdefault(coin, array.array("q")).append(ts)
                retenues += 1
    for serie in horloges.values():
        valeurs = sorted(serie)
        del serie[:]
        serie.extend(valeurs)
    return horloges, {
        "rubans_absents": absents,
        "lignes_lues": lues,
        "horodatages_retenus": retenues,
        "lignes_sans_coin": sans_coin,
        "lignes_sans_horodatage": sans_ts,
        "coins": len(horloges),
        "secondes": round(time.time() - depart, 1),
    }


def signaux_des_metaordres(
    racine: Path, *, relatif: str = RUBAN_FILLS, borne_min_ms: int = 0,
    borne_max_ms: int | None = None, limite_lignes: int | None = None,
) -> tuple[list[tuple[str, int, str]], dict[str, object]]:
    """`[(coin, signal_ts_ms, action)]` lus en flux. `signal_ts_ms` absent -> `ts_ms`."""
    chemin = racine / relatif
    if not chemin.is_file():
        return [], {"ruban_absent": relatif}
    signaux: list[tuple[str, int, str]] = []
    lues = sans_ts = 0
    depart = time.time()
    with chemin.open("rb") as flux:
        for ligne in flux:
            lues += 1
            if limite_lignes is not None and lues > limite_lignes:
                break
            s = _SIGNAL_TS.search(ligne) or _TS.search(ligne)
            c = _COIN.search(ligne)
            if s is None or c is None:
                sans_ts += 1
                continue
            ts = int(s.group(1))
            if ts < borne_min_ms or (borne_max_ms is not None and ts > borne_max_ms):
                continue
            a = _ACTION.search(ligne)
            action = a.group(1).decode("ascii", errors="replace").upper() if a else "ADD"
            signaux.append((c.group(1).decode("ascii", errors="replace").upper(), ts, action))
    return signaux, {
        "lignes_lues": lues, "signaux_retenus": len(signaux),
        "lignes_sans_horodatage": sans_ts, "secondes": round(time.time() - depart, 1),
    }


def apparier(
    signaux: list[tuple[str, int, str]], horloges: dict[str, array.array],
    *, age_max_ms: int = MAX_BOOK_AGE_MS,
) -> dict[str, object]:
    """Reproduit `evaluable_signals` a l'identique, sur des horodatages seuls.

    MEME LOGIQUE, mot pour mot : dichotomie sur les horodatages du coin, rejet si le carnet le
    plus recent qui PRECEDE le signal est plus vieux que `age_max_ms`. Un test d'equivalence
    (`tests/test_sonde_horloges_carnets.py`) verifie que cette sonde et la vraie fonction
    rendent les memes nombres -- sans quoi elle mesurerait autre chose que la porte du labo.
    """
    evaluables: list[int] = []
    alignes_add = 0
    sans_carnet = trop_vieux = 0
    for coin, signal_ms, action in signaux:
        stamps = horloges.get(coin)
        if not stamps:
            sans_carnet += 1
            continue
        index = bisect.bisect_right(stamps, signal_ms) - 1
        if index < 0 or signal_ms - stamps[index] > age_max_ms:
            trop_vieux += 1
            continue
        evaluables.append(signal_ms)
        if action == "ADD":
            alignes_add += 1
    jour_ms = DS.JOUR_MS
    par_jour: dict[int, int] = {}
    for ts in evaluables:
        par_jour[ts // jour_ms] = par_jour.get(ts // jour_ms, 0) + 1
    denses = {j for j, n in par_jour.items() if n >= MIN_SIGNALS_PER_DAY}
    timestamps_denses = [ts for ts in evaluables if ts // jour_ms in denses]
    return {
        "signaux_lus": len(signaux),
        "evaluables": len(evaluables),
        "alignes_add": alignes_add,
        "sans_carnet_pour_ce_coin": sans_carnet,
        "carnet_trop_vieux": trop_vieux,
        "jours_evaluables": len(par_jour),
        "jours_DENSES": len(denses),
        "seuil_signaux_par_jour": MIN_SIGNALS_PER_DAY,
        "timestamps_denses": timestamps_denses,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("workspace")
    p.add_argument("--depuis-ms", type=int, default=0)
    p.add_argument("--jusqu-a-ms", type=int, default=None)
    p.add_argument("--limite-fills", type=int, default=None,
                   help="borne de lignes de fills lues (sonde rapide)")
    p.add_argument("--sortie", default="")
    args = p.parse_args(argv)
    racine = Path(args.workspace).resolve()

    flux = sys.stdout
    try:  # noqa: SIM105
        flux.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    print("  lecture des horodatages de carnets (flux, aucun contenu garde)...", flush=True)
    horloges, audit_carnets = horloges_des_carnets(
        racine, borne_min_ms=args.depuis_ms, borne_max_ms=args.jusqu_a_ms)
    if not horloges:
        print("  AUCUN HORODATAGE DE CARNET LISIBLE — refus, et ce n'est pas un zero.")
        print(json.dumps(audit_carnets, ensure_ascii=False, indent=1))
        return 2
    octets = sum(s.buffer_info()[1] * s.itemsize for s in horloges.values())
    print(f"     {audit_carnets['horodatages_retenus']:,} horodatages sur "
          f"{audit_carnets['coins']} coins · {octets / 2**30:.3f} Go · "
          f"{audit_carnets['secondes']} s", flush=True)

    print("  lecture des signaux...", flush=True)
    signaux, audit_signaux = signaux_des_metaordres(
        racine, borne_min_ms=args.depuis_ms, borne_max_ms=args.jusqu_a_ms,
        limite_lignes=args.limite_fills)
    if not signaux:
        print("  AUCUN SIGNAL LISIBLE — refus.")
        print(json.dumps(audit_signaux, ensure_ascii=False, indent=1))
        return 2
    print(f"     {audit_signaux['signaux_retenus']:,} signaux · "
          f"{audit_signaux['secondes']} s", flush=True)

    bilan = apparier(signaux, horloges)
    couverture = DS.signal_coverage(bilan["timestamps_denses"])
    bornes = _bounds(bilan["timestamps_denses"], seuil_jours=DS.MINIMUM_SIGNAL_UTC_DAYS)
    diagnostic = DS.diagnostic_du_split(
        bilan["timestamps_denses"], seuil_jours=DS.MINIMUM_SIGNAL_UTC_DAYS)

    rapport = {
        "carnets": audit_carnets, "signaux": audit_signaux,
        "octets_horloges": octets,
        "appariement": {k: v for k, v in bilan.items() if k != "timestamps_denses"},
        "couverture_du_signal": couverture,
        "split_se_forme": bornes is not None,
        "split_diagnostic": diagnostic,
    }
    print()
    print("  ===== LE SPLIT SE FORMERAIT-IL ? =====")
    print(f"     journees UTC evaluables : {bilan['jours_evaluables']}"
          f" · DENSES : {bilan['jours_DENSES']}"
          f" (seuil {bilan['seuil_signaux_par_jour']} signaux/jour)")
    print(f"     signaux evaluables      : {bilan['evaluables']:,}"
          f" sur {bilan['signaux_lus']:,}")
    print(f"     SPLIT                   : "
          f"{'SE FORME' if bornes is not None else 'REFUSE — ' + str(diagnostic['motif'])}")
    print(f"     memoire des horloges    : {octets / 2**30:.3f} Go"
          f"  (le rejeu complet mesurait 24,2 Go pour 8 jours)")
    if args.sortie:
        destination = Path(args.sortie)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(rapport, ensure_ascii=False, indent=1),
                               encoding="utf-8")
        print(f"     rapport                 : {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
