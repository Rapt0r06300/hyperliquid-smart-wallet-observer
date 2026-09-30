"""COLLECTEUR DE MARKS — tous les coins qui apparaissent dans les candidats de replay.

POURQUOI (mesure du 2026-07-19, pas une intuition)
--------------------------------------------------
Après avoir réparé l'écriture des marks (18/07), le dataset de replay ressemblait à ça :

    candidats : 30 148  sur 106 coins  (HYPE 8392, BTC 5743, ZEC 3828, ETH 2923, SOL 1659…)
    marks     :    661  sur   2 coins  (HYPE 601, PURR 60)
    -> candidats REJOUABLES : 8 815 / 30 148  (29 %)

Les marks venaient de la SHORTLIST CARRY (une poignée de coins) alors que le firehose
enregistre des candidats sur 106 coins. Résultat : BTC, ETH, SOL, ZEC ont des candidats mais
AUCUN prix futur -> impossible de calculer leur PnL forward. Ils existaient dans le dataset
sans pouvoir rien prouver.

Ce collecteur lit `allMids` (endpoint PUBLIC /info, LECTURE SEULE) et écrit un mark par coin
utile, à cadence régulière. Il tourne à côté du bot, comme le feeder carry — délibérément
SÉPARÉ de la boucle de décision : un appel réseau qui rame ne doit jamais bloquer le moteur.

CE QU'IL N'INVENTE PAS
----------------------
Un prix non numérique, nul ou négatif est IGNORÉ (pas de 0.0 de remplissage, pas de report du
tick précédent). Un mark absent est un trou honnête ; un mark fabriqué est un mensonge qui
ressort plus tard en faux PnL.

CHOIX DES COINS : ceux vus dans les candidats récents (on marque ce qu'on doit juger). Si on ne
peut pas lire les candidats, on marque TOUT ce que renvoie l'API — mieux vaut trop que rien.
Un plafond borne quand même le volume (les shards de marks sont capés à 800 000 lignes).

READ-ONLY / PAPER-ONLY : aucun ordre, aucune clé, aucune signature. Un prix observé n'est pas
une position.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops.decision_firehose import enregistrer_marks  # noqa: E402

URL_INFO = "https://api.hyperliquid.xyz/info"
INTERVALLE_S_DEFAUT = 60.0
#: on ne marque pas l'univers entier indéfiniment : les shards de marks sont capés.
PLAFOND_COINS = 250
#: fenêtre de lecture des candidats pour savoir QUELS coins méritent un mark.
FENETRE_CANDIDATS_H = 48.0
#: on recalcule la liste des coins utiles de temps en temps (un coin neuf doit être marqué).
RAFRAICHIR_COINS_TOUTES_LES_S = 900.0


def lire_all_mids(*, timeout_s: float = 10.0) -> dict[str, float]:
    """{coin: mid} depuis l'endpoint PUBLIC. Prix non exploitable -> absent (jamais 0.0)."""
    corps = json.dumps({"type": "allMids"}).encode("utf-8")
    req = urllib.request.Request(URL_INFO, data=corps,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:      # noqa: S310 (URL constante)
        data = json.loads(rep.read().decode("utf-8"))
    if not isinstance(data, dict):
        return {}
    out: dict[str, float] = {}
    for coin, px in data.items():
        try:
            v = float(px)
        except (TypeError, ValueError):
            continue                                   # prix illisible = prix ABSENT
        c = str(coin).upper().strip()
        if c and v > 0:
            out[c] = v
    return out


def coins_utiles(root: Path, *, fenetre_h: float = FENETRE_CANDIDATS_H) -> set[str]:
    """Les coins vus dans les candidats récents : on marque ce qu'on aura à juger.

    Illisible/vide -> set() vide, et l'appelant marque TOUT (mieux vaut trop que rien : c'est
    exactement l'erreur inverse qu'on vient de payer).
    """
    coins: set[str] = set()
    limite = time.time() - float(fenetre_h) * 3600.0
    base = root / "runtime" / "replay"
    if not base.exists():
        return coins
    for fichier in base.glob("candidates*.jsonl"):
        try:
            with fichier.open(encoding="utf-8", errors="ignore") as fh:
                for ligne in fh:
                    ligne = ligne.strip()
                    if not ligne:
                        continue
                    try:
                        row = json.loads(ligne)
                    except ValueError:
                        continue
                    if not isinstance(row, dict):
                        continue
                    ts = row.get("recorded_at")
                    if isinstance(ts, (int, float)) and float(ts) < limite:
                        continue
                    c = str(row.get("coin") or "").upper().strip()
                    if c:
                        coins.add(c)
        except OSError:
            continue
    return coins


def une_passe(root: Path, *, coins: set[str], plafond: int = PLAFOND_COINS) -> tuple[int, int]:
    """(n_marks_ecrits, n_coins_dispo). Une erreur réseau ne tue pas la boucle : 0 écrit."""
    try:
        mids = lire_all_mids()
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return 0, 0
    if not mids:
        return 0, 0
    retenus = {c: p for c, p in mids.items() if c in coins} if coins else dict(mids)
    if len(retenus) > plafond:                          # borne dure : on ne noie pas les shards
        retenus = dict(sorted(retenus.items())[:plafond])
    n = enregistrer_marks(str(root), retenus, ts_s=time.time())
    return n, len(mids)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Collecteur de marks replay (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--intervalle", type=float, default=INTERVALLE_S_DEFAUT)
    p.add_argument("--une-fois", action="store_true", help="une seule passe (test/diagnostic)")
    args = p.parse_args(argv)

    root = Path(args.root)
    coins = coins_utiles(root)
    dernier_refresh = time.time()
    print("[marks] collecteur demarre — %d coin(s) utile(s) vus dans les candidats recents"
          % len(coins), flush=True)
    if not coins:
        print("[marks] aucun candidat lisible -> on marque TOUT l'univers (plafond %d)"
              % PLAFOND_COINS, flush=True)

    total = 0
    while True:
        n, dispo = une_passe(root, coins=coins)
        total += n
        print("[marks] %s  ecrits=%d  cumul=%d  (univers API: %d coins, suivis: %d)"
              % (time.strftime("%H:%M:%S"), n, total, dispo, len(coins) or dispo), flush=True)
        if args.une_fois:
            return 0
        if time.time() - dernier_refresh > RAFRAICHIR_COINS_TOUTES_LES_S:
            nouveaux = coins_utiles(root)
            if nouveaux:
                ajout = nouveaux - coins
                coins = nouveaux
                if ajout:
                    print("[marks] +%d nouveau(x) coin(s) a suivre : %s"
                          % (len(ajout), ", ".join(sorted(ajout)[:8])), flush=True)
            dernier_refresh = time.time()
        time.sleep(max(5.0, float(args.intervalle)))


if __name__ == "__main__":
    raise SystemExit(main())
