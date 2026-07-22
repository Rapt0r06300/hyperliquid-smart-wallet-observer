"""COLLECTEUR DE LIQUIDATIONS — la donnée sans laquelle la mesure #3 est impossible pour toujours.

CE QU'IL RÉPARE (constat du 19/07)
----------------------------------
    === HISTORIQUE DES LIQUIDATIONS (pour la mesure #3) ===
    { "snapshots": 0, "coins": 0, "verdict": "AUCUN_HISTORIQUE_LA_MESURE_EST_IMPOSSIBLE" }

Le message affiché disait « laisse le moteur tourner plus longtemps pour accumuler des
liquidations ». **C'était un mauvais conseil.** Rien n'écrivait ces données : `enregistrer_grappes`
n'est appelé que par `mainnet_readonly_observer`, qui n'est pas sur la boucle live. On pouvait
attendre un mois : toujours 0. Un garde-fou qui indique le mauvais remède est pire qu'un silence,
parce qu'il fait perdre des semaines en croyant bien faire.

COMMENT (sans toucher au moteur)
---------------------------------
Tout ce dont la carte a besoin est PUBLIC et se lit en 3 appels :
  1. le leaderboard public  -> quels wallets observer (les gros comptes à levier) ;
  2. `clearinghouseState`   -> leurs positions, avec le champ `liquidationPx` ;
  3. `allMids`              -> le prix courant, pour situer chaque liquidation par rapport au marché.

On réutilise EXACTEMENT les modules existants (`parser_positions`, `construire_carte`,
`enregistrer_grappes`) : aucune 2ᵉ implémentation, aucune constante re-dérivée. Ce collecteur est
un ALIMENTATEUR, pas un nouveau moteur.

Il tourne à côté du bot (même schéma que le collecteur de marks), délibérément SÉPARÉ de la boucle
de décision : un appel réseau lent ne doit jamais bloquer le moteur.

CE QU'IL N'INVENTE PAS
----------------------
`parser_positions` écarte déjà toute position sans `liquidationPx` (deny-by-default). La carte est
donc une **borne basse honnête** : on ne voit que les wallets qu'on observe, jamais « toutes les
liquidations du marché ». Une carte avec des prix inventés serait pire qu'aucune carte.

READ-ONLY / PAPER-ONLY : 3 endpoints publics en lecture. Aucun ordre, aucune clé, aucune signature.
Observer où d'autres seront liquidés n'est pas prendre une position.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.market.liquidation_map import construire_carte, parser_positions  # noqa: E402
from hl_observer.market.liquidation_recorder import enregistrer_grappes, resume_historique  # noqa: E402

URL_INFO = "https://api.hyperliquid.xyz/info"
URL_LEADERBOARD = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"

INTERVALLE_S_DEFAUT = 300.0      # 5 min : une carte de liquidation ne bouge pas à la seconde
MAX_WALLETS_DEFAUT = 150         # 22/07 : élargi (80->150) — plus de comptes = plus de chances qu'au
                                 # moins 2 partagent un niveau de liq (une grappe). Politesse gardée (pause).
PAUSE_ENTRE_WALLETS_S = 0.15     # politesse : on veut durer 3 jours, pas 3 minutes
#: en dessous, une grappe (>= 2 wallets au MEME niveau de prix) ne se formera quasi jamais.
MIN_WALLETS_UTILE = 20


def _post_info(charge: dict[str, Any], *, timeout_s: float = 10.0) -> Any:
    corps = json.dumps(charge).encode("utf-8")
    req = urllib.request.Request(URL_INFO, data=corps,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:      # noqa: S310 (URL constante)
        return json.loads(rep.read().decode("utf-8"))


def lire_all_mids(*, timeout_s: float = 10.0) -> dict[str, float]:
    """{coin: mid}. Prix illisible/nul -> ABSENT (jamais 0.0 de remplissage)."""
    data = _post_info({"type": "allMids"}, timeout_s=timeout_s)
    if not isinstance(data, dict):
        return {}
    out: dict[str, float] = {}
    for coin, px in data.items():
        try:
            v = float(px)
        except (TypeError, ValueError):
            continue
        c = str(coin).upper().strip()
        if c and v > 0:
            out[c] = v
    return out


def wallets_du_leaderboard(*, limite: int = MAX_WALLETS_DEFAUT, timeout_s: float = 20.0) -> list[str]:
    """Les gros comptes publics : la population dont les liquidations comptent.

    Schéma toléré large (le format du leaderboard a déjà changé) : on cherche des adresses,
    d'où qu'elles viennent dans la structure. Illisible -> liste vide, jamais une invention.
    """
    try:
        with urllib.request.urlopen(URL_LEADERBOARD, timeout=timeout_s) as rep:   # noqa: S310
            data = json.loads(rep.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return []
    lignes = data.get("leaderboardRows") if isinstance(data, dict) else data
    if not isinstance(lignes, list):
        return []
    out: list[str] = []
    for row in lignes:
        adresse = ""
        if isinstance(row, dict):
            for cle in ("ethAddress", "address", "user", "wallet"):
                v = row.get(cle)
                if isinstance(v, str) and v.startswith("0x") and len(v) == 42:
                    adresse = v
                    break
        elif isinstance(row, str) and row.startswith("0x") and len(row) == 42:
            adresse = row
        if adresse and adresse not in out:
            out.append(adresse)
        if len(out) >= int(limite):
            break
    return out


def wallets_de_secours(root: Path) -> list[str]:
    """Repli : les wallets déjà vus par le bot (statut moteur). Mieux que zéro."""
    fichier = root / "runtime" / "data" / "hypersmart_engine_status.json"
    try:
        texte = fichier.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    import re
    vus: list[str] = []
    for m in re.finditer(r"0x[0-9a-fA-F]{40}", texte):
        a = m.group(0)
        if a not in vus:
            vus.append(a)
    return vus


#: 🟢 LEVIER 4 (22/07) — une position à <= 5 % de sa liquidation = FORT levier = candidate à
#: être liquidée. C'est LE ciblage qui manquait : le haut du leaderboard, ce sont des baleines
#: PEU leveragées (liq loin du marché, jamais déclenchée) — d'où 3 événements en des jours.
SEUIL_A_RISQUE_BPS = 500.0
MAX_WATCHLIST = 400
WATCHLIST_REL = Path("runtime") / "data" / "wallets_a_risque.json"


def wallets_a_risque(positions: list, mids: dict[str, float], *,
                     seuil_bps: float = SEUIL_A_RISQUE_BPS) -> list[str]:
    """Les wallets dont AU MOINS une position est à <= `seuil_bps` de son prix de liquidation.
    Le vrai flux FORCÉ vient d'eux (fort levier), pas des grosses baleines du leaderboard."""
    a_risque: list[str] = []
    for p in positions or []:
        try:
            px = float(mids.get(str(p.coin).upper()) or 0.0)
            liq = float(p.liq_px)
            wallet = p.wallet
        except (TypeError, ValueError, AttributeError):
            continue
        if px > 0 and liq > 0:
            dist = abs(1e4 * (liq - px) / px)
            if dist <= float(seuil_bps) and wallet not in a_risque:
                a_risque.append(wallet)
    return a_risque


def charger_watchlist(root: Path) -> list[str]:
    """La watchlist accumulée des comptes à risque (fort levier), vue après vue."""
    try:
        d = json.loads((Path(root) / WATCHLIST_REL).read_text(encoding="utf-8"))
        return [a for a in (d.get("wallets") or []) if isinstance(a, str)]
    except (OSError, ValueError):
        return []


def sauver_watchlist(root: Path, wallets: list[str]) -> int:
    """Fusionne + dédoublonne + borne aux plus récents. Rend la taille finale."""
    uniq = list(dict.fromkeys(w for w in wallets if isinstance(w, str)))[-MAX_WATCHLIST:]
    p = Path(root) / WATCHLIST_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"wallets": uniq, "maj": time.time(), "real_execution": False},
                            ensure_ascii=False), encoding="utf-8")
    return len(uniq)


def _expliquer_zero(positions: list, mids: dict[str, float]) -> None:
    """POURQUOI 0 GRAPPE ? — le chiffre, pas une hypothese.

    Mesure du 19/07 : le leaderboard repondait (80 wallets, 690 positions avec `liquidationPx`)
    et pourtant AUCUNE ligne n'etait ecrite. J'avais d'abord accuse « la population est trop
    petite » -- FAUX, et c'est exactement le genre de diagnostic a l'intuition qui fait perdre
    des jours. On decompose donc les trois filtres de `construire_carte`, un par un :
        distance au prix courant <= 1000 bps · >= 2 wallets a 50 bps · notionnel >= 10 000 $
    Celui qui elimine tout est celui qu'il faudra discuter -- avec un nombre en main.
    """
    from hl_observer.market.liquidation_map import (
        MIN_NOTIONNEL_GRAPPE_USD, MIN_WALLETS_PAR_GRAPPE)

    n = len(positions)
    proches, par_coin_prix = 0, {}
    for p in positions:
        px = float(mids.get(str(p.coin).upper()) or 0.0)
        if px <= 0:
            continue
        dist = abs(1e4 * (float(p.liq_px) - px) / px)
        if dist <= 1000.0:
            proches += 1
            cle = (p.coin, round(float(p.liq_px) / (1.0 + 50 / 1e4)))
            e = par_coin_prix.setdefault(cle, {"wallets": set(), "usd": 0.0})
            e["wallets"].add(p.wallet)
            e["usd"] += float(p.notionnel_usd)
    assez_wallets = sum(1 for e in par_coin_prix.values()
                        if len(e["wallets"]) >= MIN_WALLETS_PAR_GRAPPE)
    complets = sum(1 for e in par_coin_prix.values()
                   if len(e["wallets"]) >= MIN_WALLETS_PAR_GRAPPE
                   and e["usd"] >= MIN_NOTIONNEL_GRAPPE_USD)
    print("[liq] POURQUOI 0 GRAPPE — %d positions lues" % n, flush=True)
    print("[liq]   1) a moins de 10%% du prix courant .... %d  (les autres sont trop loin "
          "pour etre actionnables)" % proches, flush=True)
    print("[liq]   2) amas formes a ce niveau ............ %d" % len(par_coin_prix), flush=True)
    print("[liq]   3) dont >= %d wallets DISTINCTS ....... %d"
          % (MIN_WALLETS_PAR_GRAPPE, assez_wallets), flush=True)
    print("[liq]   4) dont >= %.0f $ de notionnel ......... %d  <- grappes retenues"
          % (MIN_NOTIONNEL_GRAPPE_USD, complets), flush=True)
    if proches == 0 and n > 0:
        print("[liq]   => C'EST LE FILTRE DE DISTANCE qui elimine tout : les gros comptes du "
              "leaderboard sont peu leverages, leur prix de liquidation est tres loin du "
              "marche. Rien d'anormal -- mais on n'enregistrera aucun historique tant qu'on "
              "ne gardera QUE le rayon de 10 %%.", flush=True)


def une_passe(root: Path, wallets: list[str], *, pause_s: float = PAUSE_ENTRE_WALLETS_S
              ) -> tuple[int, int, int]:
    """(n_lignes_ecrites, n_positions_vues, n_wallets_lus). Une erreur réseau -> (0, 0, 0)."""
    try:
        mids = lire_all_mids()
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return 0, 0, 0
    if not mids or not wallets:
        return 0, 0, 0

    positions = []
    lus = 0
    for wallet in wallets:
        try:
            etat = _post_info({"type": "clearinghouseState", "user": wallet})
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            continue                              # un wallet illisible n'arrête pas la passe
        if isinstance(etat, dict):
            positions.extend(parser_positions(wallet, etat))
            lus += 1
        if pause_s > 0:
            time.sleep(pause_s)

    if not positions:
        return 0, 0, lus
    # 🟢 LEVIER 4 : on APPREND les comptes à fort levier vus cette passe et on les garde. Vue
    # après vue, la watchlist se remplit de comptes VRAIMENT liquidables -> les grappes (>= 2
    # wallets au même niveau) finissent par se former. Code maintenant, verdict à l'accumulation.
    a_risque = wallets_a_risque(positions, mids)
    if a_risque:
        sauver_watchlist(root, charger_watchlist(root) + a_risque)
    grappes = construire_carte(positions, mids)
    if not grappes:
        _expliquer_zero(positions, mids)
    try:
        from hl_observer.runtime.session_identity import session_courante
        session = session_courante(str(root))
    except Exception:                             # noqa: BLE001 — l'identité ne doit rien casser
        session = "collecteur_liquidations"
    n = enregistrer_grappes(grappes, root=str(root), ts_ms=int(time.time() * 1000),
                            session_id=session)
    return n, len(positions), lus


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Collecteur de liquidations (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--intervalle", type=float, default=INTERVALLE_S_DEFAUT)
    p.add_argument("--max-wallets", type=int, default=MAX_WALLETS_DEFAUT)
    p.add_argument("--une-fois", action="store_true")
    args = p.parse_args(argv)

    root = Path(args.root)
    wallets = wallets_du_leaderboard(limite=args.max_wallets)
    origine = "leaderboard public"
    if not wallets:
        wallets = wallets_de_secours(root)[: args.max_wallets]
        origine = "statut moteur (REPLI — le leaderboard n'a pas repondu)"
    # 🟢 LEVIER 4 : on ADJOINT la watchlist accumulée des comptes à RISQUE (fort levier). C'est
    # eux qui se font liquider ; les rajouter à chaque démarrage fait grossir la bonne population.
    watch = charger_watchlist(root)
    ajoutes = [a for a in watch if a not in wallets]
    wallets = wallets + ajoutes
    if ajoutes:
        origine += " + %d compte(s) a risque memorises" % len(ajoutes)
    print("[liq] collecteur demarre — %d wallet(s) a observer (%s)" % (len(wallets), origine),
          flush=True)
    if not wallets:
        print("[liq] AUCUN wallet : rien a observer. On ne fabrique pas de carte -> arret.",
              flush=True)
        return 1
    # 🔴 DIAGNOSTIC DU 19/07 : la base `liquidation_map.sqlite3` restait ABSENTE alors que le
    # collecteur tournait « sans erreur ». Cause : `construire_carte` exige >= 2 wallets DISTINCTS
    # sur le MEME niveau de prix (a 50 bps pres) et >= 10 000 $ — c'est le garde « un seul wallet
    # ne fait pas un flux », et il a raison. Avec la poignee de wallets du REPLI, la probabilite
    # que deux d'entre eux aient un prix de liquidation voisin est quasi nulle : on pouvait
    # tourner des jours et n'ecrire JAMAIS une ligne, sans le moindre message.
    # Un collecteur qui ne peut STRUCTURELLEMENT rien produire doit le DIRE, pas se taire.
    if len(wallets) < MIN_WALLETS_UTILE:
        print("[liq] ⚠️  POPULATION TROP PETITE (%d wallets). Une grappe exige >= 2 wallets "
              "DISTINCTS au meme niveau de prix : avec si peu de comptes, on n'ecrira "
              "probablement JAMAIS une ligne. Cause probable : le leaderboard public n'a pas "
              "repondu (%s). Ce n'est pas une panne du collecteur, c'est un manque d'entree."
              % (len(wallets), URL_LEADERBOARD), flush=True)

    total = 0
    while True:
        n, vues, lus = une_passe(root, wallets)
        total += n
        etat = resume_historique(root=str(root))
        print("[liq] %s  ecrits=%d  cumul=%d  (positions vues=%d, wallets lus=%d) "
              "| base: %s snapshots, %s coins"
              % (time.strftime("%H:%M:%S"), n, total, vues, lus,
                 etat.get("snapshots"), etat.get("coins")), flush=True)
        if args.une_fois:
            return 0
        time.sleep(max(30.0, float(args.intervalle)))


if __name__ == "__main__":
    raise SystemExit(main())
