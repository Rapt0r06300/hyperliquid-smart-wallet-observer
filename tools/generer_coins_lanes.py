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
import contextlib
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
RAPPORTS = Path("runtime") / "reports" / "copy_vault_quant_lab"
#: Mesuré le 2026-11-11 : 61,1 % du notionnel des leaders portait sur 184 coins sans carnet ; les
#: 60 premiers en couvrent 60,4 points. Au-delà, le gain est négligeable pour un volume doublé.
MAX_COINS = 180

#: Ruban des fills live : ce que les leaders viennent de trader (source PROACTIVE, voir plus bas).
FILLS_LIVE = Path("runtime") / "data" / "vault_fills_live.jsonl"
#: On ne lit que la QUEUE du ruban : cout borne quelle que soit la taille du fichier.
OCTETS_QUEUE_RUBAN = 8 * 1024 * 1024
#: Part maximale de la liste qui peut etre DEPLACEE en un seul passage (anti-brassage).
PART_MAX_DEPLACEE = 0.2


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


def coins_bloquant_la_mesure(root: Path) -> list[str]:
    """Coins dont le labo a mesuré que des signaux NE PEUVENT PAS être exécutés (carte d'exécutabilité).

    Lecture seule du dernier rapport du labo (``resultat.json`` →
    ``economic_result.train_executability.coins_a_collecter``, classés par signaux bloqués décroissants).
    C'est un signal plus précis que « coin sans carnet » : il nomme les coins dont la collecte est
    incomplète pour l'EXÉCUTION (pas de carnet de sortie, identité manquante...). Boucle labo →
    collecteurs. Rien si aucun rapport lisible.
    """
    dossier = root / RAPPORTS
    try:
        runs = sorted((d for d in dossier.iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True)
    except OSError:
        return []
    for run in runs:
        data = _lire_json(run / "resultat.json")
        sonde = (((data or {}).get("economic_result") or {}).get("train_executability") or {})             if isinstance(data, dict) else {}
        cibles = sonde.get("coins_a_collecter") if isinstance(sonde, dict) else None
        if isinstance(cibles, list) and cibles:
            return [nom for nom in (preserve_native_instrument_symbol(c.get("coin")) for c in cibles
                                    if isinstance(c, dict) and c.get("coin")) if nom]
    return []


def _queue_du_ruban(chemin: Path, octets: int) -> list[str]:
    """Les dernieres lignes COMPLETES du ruban, en lisant au plus ``octets`` octets depuis la fin."""
    try:
        taille = chemin.stat().st_size
        depart = max(0, taille - max(1, int(octets)))
        with chemin.open("rb") as flux:
            flux.seek(depart)
            brut = flux.read()
    except OSError:
        return []
    lignes = brut.decode("utf-8", errors="replace").splitlines()
    return lignes[1:] if depart > 0 and lignes else lignes       # la 1re ligne lue est tronquee


def coins_habituels_des_leaders(root: Path, *, octets: int = OCTETS_QUEUE_RUBAN,
                                vaults: set[str] | None = None) -> list[str]:
    """Coins que les leaders tradent HABITUELLEMENT, classes par notionnel decroissant.

    POURQUOI (A2 / S1.2). Les deux sources ci-dessus sont REACTIVES : elles nomment les coins ou les
    leaders ont DEJA trade sans qu'on ait de carnet — les signaux concernes sont donc deja perdus.
    Mesure du 12/11 : **77 008 signaux sur 98 138** refuses pour « aucun carnet dans les 30 s avant le
    signal », de loin le premier motif. Pour les sauver il faut PRE-CHAUFFER, c'est-a-dire enregistrer
    le carnet des coins habituels AVANT le prochain fill. Et le meilleur predicteur de ce qu'un leader
    va trader reste ce qu'il vient de trader.

    Lecture seule, cout borne (queue du ruban seulement). ``vaults`` restreint aux comptes suivis.
    """
    totaux: dict[str, float] = {}
    for ligne in _queue_du_ruban(root / FILLS_LIVE, octets):
        texte = ligne.strip()
        if not texte.startswith("{"):
            continue
        try:
            fill = json.loads(texte)
        except ValueError:
            continue
        if not isinstance(fill, dict):
            continue
        if vaults is not None and str(fill.get("vault") or "") not in vaults:
            continue
        nom = preserve_native_instrument_symbol(fill.get("coin"))
        if not nom:
            continue
        try:
            notionnel = abs(float(fill.get("px") or 0.0) * float(fill.get("sz") or 0.0))
        except (TypeError, ValueError):
            notionnel = 0.0
        totaux[nom] = totaux.get(nom, 0.0) + notionnel
    return [nom for nom, _n in sorted(totaux.items(), key=lambda kv: (-kv[1], kv[0]))]


def composer(existants: list[str], demandes: list[str], univers: set[str] | None, *,
             max_coins: int = MAX_COINS, deplacer_les_inutiles: bool = True) -> dict[str, Any]:
    """Liste finale + compte rendu. Les coins existants gardent leur rang ; les ajouts suivent le
    classement du labo. Univers non vérifiable : aucun ajout (on ne publie pas un nom non vérifié).

    [S1.2, 2026-11-12] Si le plafond est SATURÉ et qu'il reste des demandes, les coins existants qui
    n'apparaissent dans AUCUNE source (ni bloquants la mesure, ni demandés par le labo, ni habituels
    des leaders) cèdent leur place, en partant du rang le plus bas. Sans cela la liste se figeait :
    mesuré le 12/11, **180 coins occupés et 117 demandes « hors plafond »** — la boucle
    labo → collecteurs était morte en pratique, aucun coin nouveau ne pouvait plus entrer. Au plus
    ``PART_MAX_DEPLACEE`` de la liste bouge par passage (anti-brassage : un coin dont on vient de
    commencer le carnet ne doit pas sauter au passage suivant), et les déplacements sont RAPPORTÉS.
    """
    gardes, retires = filtrer_abonnables(existants, univers)
    ajoutables, refuses = filtrer_abonnables([c for c in demandes if c not in set(gardes)], univers)
    if univers is None:
        ajoutables, refuses = [], []
    place = max(0, int(max_coins) - len(gardes))
    deplaces: list[str] = []
    if place == 0 and ajoutables and deplacer_les_inutiles:
        utiles = set(demandes)
        a_liberer = min(len(ajoutables), max(1, int(int(max_coins) * PART_MAX_DEPLACEE)))
        for nom in reversed(gardes):                  # du rang le plus bas vers le plus haut
            if len(deplaces) >= a_liberer:
                break
            if nom not in utiles:
                deplaces.append(nom)
        if deplaces:
            sortants = set(deplaces)
            gardes = [c for c in gardes if c not in sortants]
            place = len(deplaces)
    ajoutes = ajoutables[:place]
    return {
        "coins": gardes + ajoutes,
        "ajoutes": ajoutes,
        "deplaces_car_plus_demandes": deplaces,
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
            "sources": ["config/copy_vault_coins.json", "runtime/data/copy_vault_besoins_collecte.json",
                        "runtime/reports/copy_vault_quant_lab/*/resultat.json (carte d'executabilite)",
                        "runtime/data/vault_fills_live.jsonl (coins habituels, pre-chauffage)"],
            "n_coins": len(resultat["coins"]), "n_hip3": len(hip3),
            "ajoutes": resultat["ajoutes"],
            "deplaces_car_plus_demandes": resultat.get("deplaces_car_plus_demandes", []),
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
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--max", type=int, default=MAX_COINS)
    p.add_argument("--publier", action="store_true",
                   help="écrit la liste COMMITÉE config/copy_vault_coins.json (lanes cloud) au lieu de la liste locale")
    p.add_argument("--simulation", action="store_true", help="affiche le résultat sans rien écrire")
    args = p.parse_args(argv)
    root = Path(args.root)
    # TROIS sources, dédupliquées en gardant l'ordre de priorité :
    #  1. les coins dont des signaux ne peuvent PAS être exécutés (carte d'exécutabilité : le plus précis) ;
    #  2. les coins sans carnet classés par notionnel (besoin mesuré par le labo) ;
    #  3. PRÉVENTIF (S1.2) : les coins que les leaders tradent habituellement. Les deux premières
    #     sources sont RÉACTIVES — quand un coin y apparaît, ses signaux sont déjà perdus. La
    #     troisième pré-chauffe le carnet AVANT le prochain fill, ce qui attaque le motif de refus
    #     n°1 (77 008 signaux sur 98 138 : « aucun carnet dans les 30 s avant le signal »).
    _vus: set[str] = set()
    demandes = []
    for nom in (coins_bloquant_la_mesure(root) + coins_demandes_par_le_labo(root)
                + coins_habituels_des_leaders(root)):
        if nom not in _vus:
            _vus.add(nom)
            demandes.append(nom)
    resultat = composer(coins_existants(root), demandes, charger_univers(root), max_coins=args.max)
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
          f"{len(resultat.get('deplaces_car_plus_demandes') or [])} déplacés car plus demandés, "
          f"{sum(':' in c for c in resultat['coins'])} HIP-3, {len(resultat['retires_inconnus_de_l_exchange'])} "
          f"retirés car inconnus) -> {chemin}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
