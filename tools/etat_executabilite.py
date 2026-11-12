#!/usr/bin/env python3
"""État d'exécutabilité du labo, en une commande — « suis-je prêt à mesurer, et sinon que collecter ? ».

Lit le DERNIER rapport du labo (``runtime/reports/copy_vault_quant_lab/*/resultat.json``, champ
``economic_result.train_executability`` produit par ``copy_vault_train_executability.sonder_train``) et
l'affiche en clair : le labo peut-il mesurer quelque chose, combien de signaux sont exécutables, pourquoi
les autres ne le sont pas, et quels coins collecter en priorité pour débloquer la mesure.

C'est la jauge que l'utilisateur consulte pendant les jours de collecte : quand « Aucun trade exécutable »
disparaît, la recherche économique peut enfin tourner. Lecture seule ; aucun calcul, aucune requête réseau.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
RAPPORTS = Path("runtime") / "reports" / "copy_vault_quant_lab"


def dernier_rapport(root: Path) -> Path | None:
    """Le `resultat.json` du run le plus récent (nom horodaté décroissant), ou ``None``."""
    try:
        runs = sorted((d for d in (root / RAPPORTS).iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True)
    except OSError:
        return None
    for run in runs:
        if (run / "resultat.json").is_file():
            return run / "resultat.json"
    return None


def lire_sonde(resultat_json: Path) -> dict[str, Any]:
    """La carte d'exécutabilité d'un `resultat.json`, ou un dict vide si absente/illisible."""
    try:
        data = json.loads(resultat_json.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    sonde = ((data.get("economic_result") or {}).get("train_executability") or {}) if isinstance(data, dict) else {}
    return sonde if isinstance(sonde, dict) else {}


def rendre(sonde: dict[str, Any], *, run_nom: str = "") -> list[str]:
    """Lignes de texte lisibles décrivant l'état d'exécutabilité."""
    lignes: list[str] = []
    titre = f"ÉTAT D'EXÉCUTABILITÉ DU LABO  (run {run_nom})" if run_nom else "ÉTAT D'EXÉCUTABILITÉ DU LABO"
    lignes.append(titre)
    lignes.append("=" * len(titre))
    if not sonde:
        lignes.append("Le dernier run a pu lancer la recherche (aucun blocage d'exécutabilité enregistré),")
        lignes.append("ou aucun rapport n'est encore lisible. Lancez le labo pour produire une carte.")
        return lignes
    signaux = int(sonde.get("signaux_train") or 0)
    executables = int(sonde.get("signaux_executables") or 0)
    if sonde.get("executable"):
        lignes.append(f"✅ MESURABLE : {executables:,} signaux sur {signaux:,} sont exécutables.".replace(",", " "))
        lignes.append("La recherche économique peut tourner (VALIDATION / OOS / FORWARD restent requis pour une preuve).")
        return lignes
    lignes.append(f"🚫 PAS ENCORE MESURABLE : 0 trade exécutable sur {signaux:,} signaux d'entraînement.".replace(",", " "))
    refus = sonde.get("refus_par_motif") if isinstance(sonde.get("refus_par_motif"), dict) else {}
    explications = sonde.get("explications") if isinstance(sonde.get("explications"), dict) else {}
    if refus:
        lignes.append("")
        lignes.append("Carnets refusés, par motif :")
        for motif, nombre in list(refus.items())[:8]:
            lignes.append(f"  {int(nombre):>8,} × {explications.get(motif, motif)}".replace(",", " "))
    cibles = sonde.get("coins_a_collecter") if isinstance(sonde.get("coins_a_collecter"), list) else []
    if cibles:
        lignes.append("")
        lignes.append("Coins à collecter en priorité (le plus de signaux bloqués d'abord) :")
        for c in cibles[:15]:
            if isinstance(c, dict) and c.get("coin"):
                motif = explications.get(c.get("motif_principal")) or c.get("motif_principal") or "—"
                lignes.append(f"  {str(c['coin']):<14} {int(c.get('non_executables') or 0):>7,} bloqués   ({motif})".replace(",", " "))
        lignes.append("")
        lignes.append("→ generer_coins_lanes.py cible déjà ces coins ; laissez tourner les collecteurs,")
        lignes.append("  puis le Certificateur, puis relancez le labo : le blocage recule coin par coin.")
    return lignes


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--json", action="store_true", help="sort la carte brute au lieu du texte")
    args = p.parse_args(argv)
    root = Path(args.root)
    rapport = dernier_rapport(root)
    if rapport is None:
        print("[executabilite] aucun rapport du labo trouvé — lancez LANCER_LAB_QUANT_COPY_VAULT.cmd.")
        return 2
    sonde = lire_sonde(rapport)
    if args.json:
        print(json.dumps(sonde, ensure_ascii=False, indent=2))
        return 0
    for ligne in rendre(sonde, run_nom=rapport.parent.name):
        print(ligne)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
