r"""Le WS rate-t-il des fills que le REST capte ? Mesure sur l'INTERSECTION, seule honnête.

POURQUOI CE SCRIPT EXISTE (22/11/2026). `tools/reconcilier_sources.py` compare des sources de
fills et rend les exclusifs de chacune. Lance tel quel sur la session archivee du 08/11, il
donne « le WS a rate 6 495 fills que le REST avait » -- et **ce chiffre ne prouve rien** :

```
live : 17 vaults sur 13 JOURS   (26/10 11:44 -> 08/11 14:06)
poll : 27 vaults sur  1 JOUR    (07/11 15:25 -> 08/11 16:59)
vaults communs : 14
```

Deux populations differentes observees sur deux fenetres differentes : les « exclusifs » sont
d'abord l'effet du perimetre, pas d'un defaut de capture. Comparer ainsi, c'est mesurer la
difference des echantillons en croyant mesurer la qualite des collecteurs.

CE QUE CE SCRIPT FAIT. Il restreint les deux sources a leur **intersection stricte** -- memes
vaults ET fenetre temporelle commune -- puis compte ce que chacune a manque. La, un ecart est
un vrai trou de capture : les deux observateurs regardaient la meme chose au meme moment.

Un trou REEL a une consequence directe sur le verdict economique : un fill manquant a l'entree
ou a la sortie d'une position rend l'episode incomplet, et le labo le rejette
(`STALE_OR_MISSING_EXIT_BOOK`, 1 045 cas sur 1 613 candidats TRAIN).

LECTURE SEULE. Aucune ecriture hors du rapport JSON. PAPER.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

RACINE = pathlib.Path(__file__).resolve().parents[1]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))

from reconcilier_sources import cle_identite  # noqa: E402


def _horodatage(fill: dict) -> int | None:
    """L'instant du fill, ou ``None``. Jamais une valeur de repli : un fill sans instant
    ne peut pas etre place dans une fenetre, et le dire est plus utile qu'un zero."""
    for clef in ("time", "received_at_ms", "observed_at_ms", "processed_at_ms"):
        valeur = fill.get(clef)
        if isinstance(valeur, bool):
            continue
        if isinstance(valeur, (int, float)) and valeur > 0:
            return int(valeur)
    return None


def _vault(fill: dict) -> str | None:
    brut = fill.get("vault") or fill.get("user")
    return str(brut).strip().lower() if brut else None


def lire(chemin: pathlib.Path, *, limite: int | None = None) -> list[dict]:
    lignes: list[dict] = []
    with chemin.open(encoding="utf-8", errors="replace") as flux:
        for index, ligne in enumerate(flux):
            if limite is not None and index >= limite:
                break
            try:
                objet = json.loads(ligne)
            except ValueError:
                continue
            if isinstance(objet, dict):
                lignes.append(objet)
    return lignes


def perimetre(fills: list[dict]) -> dict:
    vaults = {v for v in (_vault(f) for f in fills) if v}
    instants = [t for t in (_horodatage(f) for f in fills) if t is not None]
    return {
        "fills": len(fills), "vaults": vaults,
        "sans_horodatage": sum(1 for f in fills if _horodatage(f) is None),
        "debut_ms": min(instants) if instants else None,
        "fin_ms": max(instants) if instants else None,
    }


def comparer(a: list[dict], b: list[dict], *, nom_a: str, nom_b: str) -> dict:
    """Compte les trous de chacun SUR L'INTERSECTION stricte (memes vaults, meme fenetre)."""
    pa, pb = perimetre(a), perimetre(b)
    vaults = pa["vaults"] & pb["vaults"]
    if not vaults or pa["debut_ms"] is None or pb["debut_ms"] is None:
        return {"verdict": "INCOMPARABLE",
                "pourquoi": ("aucun vault commun" if not vaults
                             else "une source n'a aucun horodatage lisible"),
                "vaults_a": len(pa["vaults"]), "vaults_b": len(pb["vaults"])}
    debut = max(pa["debut_ms"], pb["debut_ms"])
    fin = min(pa["fin_ms"], pb["fin_ms"])
    if debut >= fin:
        return {"verdict": "INCOMPARABLE", "pourquoi": "fenetres disjointes",
                "debut_ms": debut, "fin_ms": fin}

    def restreindre(fills: list[dict]) -> set:
        cles = set()
        for f in fills:
            v, t = _vault(f), _horodatage(f)
            if v not in vaults or t is None or not (debut <= t <= fin):
                continue
            c = cle_identite(f)
            if c is not None:
                cles.add(c)
        return cles

    ca, cb = restreindre(a), restreindre(b)
    union = ca | cb
    return {
        "verdict": "COMPARABLE",
        "vaults_communs": len(vaults),
        "fenetre_commune_ms": [debut, fin],
        "fenetre_commune_h": round((fin - debut) / 3_600_000, 2),
        f"fills_{nom_a}": len(ca), f"fills_{nom_b}": len(cb),
        "union": len(union),
        f"manques_par_{nom_a}": len(cb - ca),
        f"manques_par_{nom_b}": len(ca - cb),
        f"part_manquee_par_{nom_a}_pct": round(100.0 * len(cb - ca) / len(union), 2) if union else None,
        f"part_manquee_par_{nom_b}_pct": round(100.0 * len(ca - cb) / len(union), 2) if union else None,
        "couverture_meilleure_source_pct": (
            round(100.0 * max(len(ca), len(cb)) / len(union), 2) if union else None),
    }


def main(argv: list[str] | None = None) -> int:
    flux = sys.stdout
    try:  # noqa: SIM105
        flux.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--a", required=True, help="premiere source (ex. le ruban WS live)")
    p.add_argument("--b", required=True, help="seconde source (ex. le ruban REST poll)")
    p.add_argument("--nom-a", default="live")
    p.add_argument("--nom-b", default="poll")
    p.add_argument("--limite", type=int, default=None, help="lignes max par source")
    p.add_argument("--out", default="")
    args = p.parse_args(argv)

    ca, cb = pathlib.Path(args.a), pathlib.Path(args.b)
    for chemin in (ca, cb):
        if not chemin.is_file():
            print(f"  SOURCE INTROUVABLE : {chemin}  — rien a mesurer, et ce n'est pas un zero.")
            return 2
    a, b = lire(ca, limite=args.limite), lire(cb, limite=args.limite)
    pa, pb = perimetre(a), perimetre(b)
    print(f"  {args.nom_a:<6} {pa['fills']:>8,} fills | {len(pa['vaults']):>3} vaults"
          f" | sans horodatage {pa['sans_horodatage']:,}")
    print(f"  {args.nom_b:<6} {pb['fills']:>8,} fills | {len(pb['vaults']):>3} vaults"
          f" | sans horodatage {pb['sans_horodatage']:,}")
    print()
    bilan = comparer(a, b, nom_a=args.nom_a, nom_b=args.nom_b)
    print(json.dumps(bilan, ensure_ascii=False, indent=1))
    if args.out:
        sortie = pathlib.Path(args.out)
        sortie.parent.mkdir(parents=True, exist_ok=True)
        sortie.write_text(json.dumps(bilan, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n  rapport : {sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
