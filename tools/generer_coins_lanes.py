"""Liste des coins dont les collecteurs L2 / marché doivent suivre le carnet — boucle labo → collecteurs.

Le laboratoire mesure, à chaque étude de copiabilité, sur quels coins les leaders tradent SANS
qu'aucun carnet ne soit collecté (besoin ``SPREAD_MANQUANT`` de
``runtime/data/copy_vault_besoins_collecte.json``, classé par part du notionnel des leaders). Ces
coins — en majorité des marchés HIP-3 — rendent le coût de copie non mesurable. Cet outil les
ajoute à la liste suivie, APRÈS vérification de chaque nom auprès de l'univers officiel
Hyperliquid : un nom inconnu ferait fermer toute la connexion WebSocket (voir
``hl_observer.collection.univers_perps``), il n'entre donc jamais dans la liste.

Deux sorties, jamais confondues :

* par défaut, ``runtime/data/copy_vault_coins_local.json`` : lue par le collecteur LOCAL
  ``l2-leaders`` (régénérée à chaque lancement de ``LANCER_COLLECTEURS_COPY_VAULT.cmd``) ;
* avec ``--publier``, ``config/copy_vault_coins.json`` : la liste COMMITÉE que lisent les lanes
  cloud. Geste délibéré : elle ne change sur GitHub qu'après une poussée du code.

Sans univers vérifiable (réseau coupé et aucun cache), aucun coin n'est ajouté : la liste
existante est conservée telle quelle. Lecture seule : aucun ordre, aucune clé.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection.univers_perps import charger_univers, filtrer_abonnables  # noqa: E402
from hl_observer.instrument_identity import preserve_native_instrument_symbol  # noqa: E402

LISTE_COMMITEE = Path("config") / "copy_vault_coins.json"
LISTE_LOCALE = Path("runtime") / "data" / "copy_vault_coins_local.json"
BESOINS = Path("runtime") / "data" / "copy_vault_besoins_collecte.json"
#: Mesuré le 2026-11-11 : 61,1 % du notionnel des leaders portait sur 184 coins sans carnet ; les
#: 60 premiers en couvrent 60,4 points. Au-delà, le gain est négligeable pour un volume doublé.
MAX_COINS = 180


def _lire_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def coins_existants(root: Path) -> list[str]:
    data = _lire_json(root / LISTE_COMMITEE)
    coins = data.get("coins") if isinstance(data, dict) else data
    return [nom for nom in (preserve_native_instrument_symbol(c) for c in coins or ()) if nom] \
        if isinstance(coins, list) else []


def coins_demandes_par_le_labo(root: Path) -> list[str]:
    """Coins sans carnet, classés par part du notionnel des leaders (mesure du labo). PUR côté données."""
    data = _lire_json(root / BESOINS)
    besoins = data.get("needs") if isinstance(data, dict) else None
    for besoin in besoins if isinstance(besoins, list) else ():
        if not isinstance(besoin, dict) or besoin.get("need") != "SPREAD_MANQUANT":
            continue
        classes = besoin.get("coins_by_notional")
        if isinstance(classes, list) and classes:
            return [nom for nom in (preserve_native_instrument_symbol(c[0]) for c in classes
                                    if isinstance(c, (list, tuple)) and c) if nom]
        return [nom for nom in (preserve_native_instrument_symbol(c) for c in besoin.get("top_coins") or ()) if nom]
    return []


def composer(existants: list[str], demandes: list[str], univers: set[str] | None, *,
             max_coins: int = MAX_COINS) -> dict[str, Any]:
    """Liste finale + compte rendu. Les coins existants gardent leur rang ; les ajouts suivent le
    classement du labo. Univers non vérifiable : aucun ajout (on ne publie pas un nom non vérifié)."""
    gardes, retires = filtrer_abonnables(existants, univers)
    ajoutables, refuses = filtrer_abonnables([c for c in demandes if c not in set(gardes)], univers)
    if univers is None:
        ajoutables, refuses = [], []
    place = max(0, int(max_coins) - len(gardes))
    ajoutes = ajoutables[:place]
    return {
        "coins": gardes + ajoutes,
        "ajoutes": ajoutes,
        "retires_inconnus_de_l_exchange": retires,
        "demandes_refusees_inconnues": refuses,
        "demandes_hors_plafond": ajoutables[place:],
        "univers_verifie": univers is not None,
    }


def ecrire(root: Path, sortie: Path, resultat: dict[str, Any], *, now_ms: int) -> Path:
    chemin = root / sortie
    chemin.parent.mkdir(parents=True, exist_ok=True)
    hip3 = [c for c in resultat["coins"] if ":" in c]
    payload = {
        "_comment": "Coins (perp HL, dex HIP-3 compris) que les leaders suivis tradent, pour les collecteurs "
                    "L2/marche. Identite NATIVE (casse et prefixe de dex) verifiee aupres de l'univers "
                    "officiel. PAPER/lecture seule.",
        "_provenance": {
            "genere_ms": now_ms, "outil": "tools/generer_coins_lanes.py",
            "sources": ["config/copy_vault_coins.json", "runtime/data/copy_vault_besoins_collecte.json"],
            "n_coins": len(resultat["coins"]), "n_hip3": len(hip3),
            "ajoutes": resultat["ajoutes"],
            "retires_inconnus_de_l_exchange": resultat["retires_inconnus_de_l_exchange"],
            "demandes_refusees_inconnues": resultat["demandes_refusees_inconnues"],
            "univers_verifie": resultat["univers_verifie"],
        },
        "coins": resultat["coins"],
    }
    temporaire = chemin.with_name(chemin.name + ".partial")
    temporaire.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    temporaire.replace(chemin)
    return chemin


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--max", type=int, default=MAX_COINS)
    p.add_argument("--publier", action="store_true",
                   help="écrit la liste COMMITÉE config/copy_vault_coins.json (lanes cloud) au lieu de la liste locale")
    p.add_argument("--simulation", action="store_true", help="affiche le résultat sans rien écrire")
    args = p.parse_args(argv)
    root = Path(args.root)
    resultat = composer(coins_existants(root), coins_demandes_par_le_labo(root), charger_univers(root),
                        max_coins=args.max)
    if not resultat["coins"]:
        print("[coins] aucune liste existante lisible : rien n'est écrit.")
        return 2
    if args.publier and not resultat["univers_verifie"]:
        print("[coins] univers officiel non vérifiable : la liste commitée n'est pas modifiée.")
        return 3
    resume = {k: (len(v) if isinstance(v, list) else v) for k, v in resultat.items()}
    if args.simulation:
        print(json.dumps({**resume, "ajoutes_liste": resultat["ajoutes"][:40]}, ensure_ascii=False))
        return 0
    chemin = ecrire(root, LISTE_COMMITEE if args.publier else LISTE_LOCALE, resultat, now_ms=int(time.time() * 1000))
    print(f"[coins] {len(resultat['coins'])} coins ({len(resultat['ajoutes'])} ajoutés, "
          f"{sum(':' in c for c in resultat['coins'])} HIP-3, {len(resultat['retires_inconnus_de_l_exchange'])} "
          f"retirés car inconnus) -> {chemin}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
