r"""Deux mesures que l'audit du 22/11/2026 a dû faire à la main, rendues répétables.

1. RETARD DE RÉCEPTION par ruban : `received_at_ms - exchange_ts_ms` (médiane, p90, p99, max) sur
   la fin de chaque ruban. Le 22/11 : trades 162 ms, carnets L2 337 ms, mais BBO 538 ms (p99 889) —
   un écart qu'aucun tableau ne montrait.
2. CONTINUITÉ DES POSITIONS : dans les fills d'un leader, la position AVANT un fill
   (`startPosition`) doit prolonger celle d'APRÈS le fill précédent. Une rupture = un fill manquant.
   Le 22/11 : 1 129 ruptures sur 110 690 fills rattrapés (1 %). Les fills d'une même milliseconde
   sont ordonnés par la chaîne (signe x position), JAMAIS par `tid` : cet ordre-là fabriquait
   60 953 fausses ruptures.

LECTURE SEULE. Aucun réseau. Un ruban absent ou sans horodatage rend « NON MESURABLE », jamais 0.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
RUBANS = ("copy_vault_trades_lane.jsonl", "copy_vault_bbo_lane.jsonl", "copy_vault_l2_tape.jsonl",
          "vault_fills_live.jsonl")
FILLS = ("vault_fills_live.jsonl", "vault_fills_poll.jsonl")
#: Au-delà, une ligne n'a pas été observée en direct : elle a été REJOUÉE (à l'abonnement). La compter
#: dans le retard de réception donnait « médiane 55 s » sur un ruban dont le direct arrive en 0,2 s.
REJOUE_AU_DELA_MS = 30_000


def fin_de_ruban(chemin: Path, octets: int = 2_000_000) -> list[dict]:
    """Les dernières lignes JSON complètes d'un ruban (la première, tronquée, est écartée)."""
    with chemin.open("rb") as f:
        taille = chemin.stat().st_size
        f.seek(max(0, taille - octets))
        lignes = f.read().decode("utf-8", "replace").splitlines()
    if taille > octets:
        lignes = lignes[1:]
    sortie = []
    for ligne in lignes:
        try:
            objet = json.loads(ligne)
        except ValueError:
            continue
        if isinstance(objet, dict):
            sortie.append(objet)
    return sortie


def retards(lignes: list[dict]) -> dict:
    """Statistiques du retard de réception. Les retards NÉGATIFS (horloge) sont comptés à part."""
    valeurs, negatifs, rejoues = [], 0, 0
    for x in lignes:
        emis = x.get("exchange_ts_ms") or x.get("ts_ms") or x.get("time")
        recu = x.get("received_at_ms") or x.get("observed_at_ms")
        if not isinstance(emis, (int, float)) or not isinstance(recu, (int, float)):
            continue
        if recu < emis:
            negatifs += 1
            continue
        if recu - emis > REJOUE_AU_DELA_MS:
            rejoues += 1            # rejoué à l'abonnement : ce n'est pas un retard de réception
            continue
        valeurs.append(float(recu - emis))
    if not valeurs:
        return {"n": 0, "statut": "NON_MESURABLE", "negatifs": negatifs, "rejoues": rejoues}
    valeurs.sort()
    q = lambda p: valeurs[min(len(valeurs) - 1, int(p * len(valeurs)))]  # noqa: E731
    return {"n": len(valeurs), "statut": "MESURE", "mediane_ms": q(0.5), "p90_ms": q(0.9), "p99_ms": q(0.99),
            "max_ms": valeurs[-1], "negatifs": negatifs, "rejoues": rejoues}


def ruptures_de_position(fills: list[dict]) -> dict:
    """Ruptures de la chaîne `startPosition` par (leader, coin). Rend le compte et les ruptures."""
    par_cle: dict[tuple[str, str], list[tuple]] = {}
    ignores = 0
    for x in fills:
        try:
            sp = float(x["startPosition"] if "startPosition" in x else x["start_position"])
            sz, ts = float(x["sz"]), int(x.get("ts_ms") or x.get("time"))
            signe = float(x["signe"]) if "signe" in x else (1.0 if str(x.get("side")) == "B" else -1.0)
        except (KeyError, TypeError, ValueError):
            ignores += 1
            continue
        par_cle.setdefault((str(x.get("vault")), str(x.get("coin"))), []).append((ts, signe * sp, sp, signe, sz))
    ruptures, total = [], 0
    for (vault, coin), suite in par_cle.items():
        suite.sort(key=lambda r: (r[0], r[1]))               # dans la milliseconde : l'ordre de la CHAÎNE
        total += len(suite)
        for avant, apres in zip(suite, suite[1:]):
            attendue = avant[2] + avant[3] * avant[4]
            echelle = max(abs(attendue), abs(apres[2]), avant[4], apres[4], 1e-12)
            if abs(apres[2] - attendue) > 1e-6 * echelle:
                ruptures.append({"vault": vault, "coin": coin, "ts_ms": apres[0],
                                 "attendue": attendue, "observee": apres[2]})
    return {"fills": total, "ignores": ignores, "ruptures": len(ruptures),
            "taux": (len(ruptures) / total) if total else None, "detail": ruptures}


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--racine", default=str(RACINE))
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    donnees = Path(args.racine) / "runtime" / "data"
    bilan: dict = {"retards": {}, "continuite": {}}
    for nom in RUBANS:
        chemin = donnees / nom
        bilan["retards"][nom] = retards(fin_de_ruban(chemin)) if chemin.is_file() else {"n": 0, "statut": "ABSENT"}
    for nom in FILLS:
        chemin = donnees / nom
        if chemin.is_file():
            r = ruptures_de_position(fin_de_ruban(chemin, 20_000_000))
            bilan["continuite"][nom] = {k: v for k, v in r.items() if k != "detail"} | {"exemples": r["detail"][:5]}
        else:
            bilan["continuite"][nom] = {"statut": "ABSENT"}
    if args.json:
        print(json.dumps(bilan, ensure_ascii=False, indent=1))
        return 0
    print("  RETARD DE RECEPTION (reception - horodatage de la plateforme), fin de chaque ruban")
    for nom, r in bilan["retards"].items():
        if r.get("statut") != "MESURE":
            print(f"    {nom:<32} {r.get('statut')}")
        else:
            print(f"    {nom:<32} n={r['n']:<6} mediane {r['mediane_ms']:>6.0f} ms | p90 {r['p90_ms']:>6.0f} | p99 {r['p99_ms']:>7.0f}"
                  f" | max {r['max_ms']:>8.0f} | negatifs {r['negatifs']} | rejoues {r['rejoues']}")
    print("  CONTINUITE DES POSITIONS (startPosition) dans les fills")
    for nom, r in bilan["continuite"].items():
        if "fills" not in r:
            print(f"    {nom:<32} {r.get('statut')}")
        else:
            taux = "n/d" if r["taux"] is None else f"{100 * r['taux']:.2f} %"
            print(f"    {nom:<32} fills {r['fills']:<7} ruptures {r['ruptures']:<5} ({taux}) | lignes non lisibles {r['ignores']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
