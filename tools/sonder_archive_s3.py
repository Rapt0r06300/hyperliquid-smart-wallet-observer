"""#462 / H-57 -- L'archive S3. **DECISION DE FLO (2026-07-13) : RIEN DE PAYANT.**

═══════════════════════════════════════════════════════════════════════════════════════════════
🔒 LA REGLE
═══════════════════════════════════════════════════════════════════════════════════════════════

L'archive `hyperliquid-archive` est en **REQUESTER-PAYS** : chaque octet telecharge est FACTURE.

    ***Flo : « je ne veux rien de payant ».***

-> **Le mode requester-pays est DESACTIVE par defaut.** Il faut le demander explicitement avec
   `--payant`, et l'outil affiche alors ce qu'il va couter AVANT de bouger.

Mais il reste **UNE question a ZERO euro**, et elle vaut la peine :

    ***Le bucket est-il PUBLIQUEMENT lisible ?***

`aws s3 ls --no-sign-request` ne coute RIEN (pas d'identifiants, pas de facturation) et repond.
S'il repond oui -> on a la donnee **gratuitement**. S'il repond non -> la porte est fermee, et on
le saura **sans avoir depense un centime**.

*C'est exactement la lecon du jour, appliquee : ne pas AFFIRMER qu'une porte est fermee. La
POUSSER -- mais gratuitement.*

🔒 Aucun secret n'est ecrit dans un fichier. Aucun ordre reel. Aucune signature.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection.archive_s3 import (  # noqa: E402
    IdentifiantsAbsents,
    cle_l2_book,
    exiger_identifiants,
    plan_l2_book,
)

# Tarif egress AWS S3 sortant vers Internet : ~0,09 $/Go (premiers To). On l'affiche comme une
# HYPOTHESE, pas comme une verite -- le vrai chiffre est sur la facture de Flo.
USD_PAR_GO_HYPOTHESE = 0.09
UTC = timezone.utc


def _aws_dispo() -> bool:
    return shutil.which("aws") is not None


def _ls(uri: str, *, payant: bool) -> tuple[bool, int | None, str]:
    """`aws s3 ls`. En mode GRATUIT : --no-sign-request (aucun identifiant, aucune facturation)."""
    cmd = ["aws", "s3", "ls", uri]
    cmd += ["--request-payer", "requester"] if payant else ["--no-sign-request"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except Exception as exc:  # noqa: BLE001
        return False, None, str(exc)[:120]
    if r.returncode != 0:
        detail = (r.stderr or "").strip().splitlines()
        return False, None, (detail[-1][:110] if detail else "code %d" % r.returncode)
    for ligne in (r.stdout or "").split("\n"):
        parts = ligne.split()
        if len(parts) >= 3 and parts[-2].isdigit():
            return True, int(parts[-2]), ""
    return True, None, "liste vide"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", default="BTC")
    ap.add_argument("--jours", type=int, default=30, help="profondeur a CHIFFRER (pas a telecharger)")
    ap.add_argument("--payant", action="store_true",
                    help="ACTIVE le requester-pays. Facture. Desactive par defaut (decision de Flo).")
    a = ap.parse_args()

    print("=" * 92)
    print("  #462 / H-57 -- L'ARCHIVE S3 OFFICIELLE HYPERLIQUID")
    print("=" * 92)
    print("\n  🔴 J'ai affirme 3 fois que le carnet L2 n'avait AUCUNE source historique.")
    print("     La doc publie s3://hyperliquid-archive/market_data/.../l2Book/ depuis 2023.")
    print("     J'avais TORT. 3e fois aujourd'hui (candleSnapshot, fundingHistory, ceci).\n")
    print("  🔒 DECISION DE FLO : **RIEN DE PAYANT.** Le requester-pays est DESACTIVE.")
    print("     On pose la seule question qui coute ZERO : **le bucket est-il PUBLIC ?**\n")

    if not _aws_dispo():
        print("  ❌ La CLI `aws` n'est pas installee. -> https://aws.amazon.com/cli/")
        print("     RIEN n'a ete telecharge. RIEN n'a ete facture.")
        return 2

    base = datetime.now(UTC) - timedelta(days=45)   # upload ~mensuel : on evite le tout frais
    cibles = [
        ("carnet L2 (1 h)", cle_l2_book(a.coin, base, 12).uri),
        ("bucket marche", "s3://hyperliquid-archive/"),
        ("bucket noeud (fills/trades/transferts)", "s3://hl-mainnet-node-data/"),
    ]

    if not a.payant:
        print("  --- SONDE GRATUITE (--no-sign-request : aucun identifiant, aucune facture) ---")
        public = False
        for nom, uri in cibles:
            ok, taille, err = _ls(uri, payant=False)
            if ok:
                public = True
                print("    ✅ PUBLIC   %-38s %s" % (nom, uri))
                if taille:
                    print("                taille : %.2f Mo" % (taille / 1e6))
            else:
                print("    🔒 FERME    %-38s (%s)" % (nom, err))
        print("\n" + "-" * 92)
        if public:
            print("  🎉 AU MOINS UN BUCKET EST LISIBLE GRATUITEMENT. La porte est OUVERTE, sans payer.")
        else:
            print("  🔒 AUCUN acces gratuit : les buckets exigent le requester-pays (donc de l'argent).")
            print("     **Decision de Flo : on n'y va pas.** Ce n'est pas un mur technique,")
            print("     c'est un CHOIX -- et il est enregistre comme tel, pas comme une fatalite.")
            print("\n  Ce qui reste, GRATUIT, pour le carnet L2 et les trades :")
            print("     -> **enregistrer vers l'AVANT** (WS public, ce qu'on fait deja).")
            print("        On ne peut pas remonter le temps sans payer. On peut avancer.")
        print("-" * 92)
        print("\n  Rien n'a ete telecharge. **Rien n'a ete facture.**")
        return 0 if public else 1

    # --- mode PAYANT, explicitement demande ---
    print("  ⚠️ MODE PAYANT DEMANDE (--payant). Chaque octet sera FACTURE.")
    try:
        exiger_identifiants()
    except IdentifiantsAbsents as exc:
        print("  ❌ %s" % exc)
        print("     RIEN n'a ete telecharge. RIEN n'a ete facture.")
        return 3

    tailles: list[int] = []
    for h in (0, 6, 12, 18):
        ok, t, err = _ls(cle_l2_book(a.coin, base, h).uri, payant=True)
        if ok and t:
            tailles.append(t)
            print("    %s %02dh -> %8.2f Mo" % (base.date(), h, t / 1e6))
        else:
            print("    %s %02dh -> absent (%s)" % (base.date(), h, err))

    if not tailles:
        print("\n  Aucun objet lisible. **AUCUN chiffre invente.**")
        return 1

    moy = sum(tailles) / len(tailles)
    heures = a.jours * 24
    total_go = moy * heures / 1e9
    print("\n" + "-" * 92)
    print("  taille moyenne d'une heure : %.2f Mo" % (moy / 1e6))
    print("  pour **%d jours** d'un seul coin : %d objets, ~%.2f Go" % (a.jours, heures, total_go))
    print("  cout d'egress ESTIME           : ~%.2f USD  (hypothese %.2f $/Go -- la verite est"
          " sur la facture)" % (total_go * USD_PAR_GO_HYPOTHESE, USD_PAR_GO_HYPOTHESE))
    print("-" * 92)
    print("\n  ⚖️ CE QUE CA REOUVRE -- ET CE QUE CA NE REOUVRE **PAS** :")
    print("     ❌ **PAS le market making.** T1b a mesure a **100 %% de remplissage** (borne haute)")
    print("        et trouve que le prix bouge **5 a 30x plus** que le spread capture. Plus de")
    print("        donnees mesureront ce ratio MIEUX ; elles ne le feront pas changer de SIGNE.")
    print("        *Dire « l'archive ressuscite le MM » serait refaire la faute des 38 %% d'APR.*")
    print("     ✅ **node_trades / node_fills_by_block** : les trades avec le cote AGRESSEUR")
    print("        -> PIN/VPIN (#463) et selection adverse HISTORIQUE. Entree jamais mesuree.")
    print("     ✅ **misc_events_by_block** : les TRANSFERTS -> c'est **X-01 nativement**,")
    print("        en historique, sans scraper Arbitrum.")
    print("     ✅ **l2Book historique** : la carte des liquidations (X-11) au moment des chocs.")
    print("\n  Rien n'a ete telecharge en masse. Ce sondage n'a lu que %d objet(s)." % len(tailles))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
