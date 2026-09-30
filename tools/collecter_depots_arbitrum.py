"""#362 / X-01 — collecter les dépôts Arbitrum → Hyperliquid. LECTURE ON-CHAIN SEULE.

🔴 CE SCRIPT REFUSE DE TOURNER SANS UNE ADRESSE DE PONT **QUE TU AS VERIFIEE**.

Je n'ai pas verifie l'adresse du contrat de pont. L'ecrire « de memoire » serait une donnee
FABRIQUEE presentee comme reelle -- et elle ferait lire les depots du MAUVAIS contrat, produisant
un signal parfaitement faux **et parfaitement silencieux**. C'est le pire bug que ce projet
connaisse.

    set HYPERSMART_HL_BRIDGE_ARBITRUM=0x....   (apres verification sur la doc officielle)
    COLLECTER-DEPOTS.cmd

Aucun ordre reel. Aucune cle. Aucune signature. **Aucun depot EMIS** : on LIT la chaine.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection.arbitrum_deposits import (  # noqa: E402
    AdresseDuPontNonVerifiee,
    etat_de_la_piste,
    parser_logs,
    requete_logs,
    valider_adresse_du_pont,
)

RPC = os.environ.get("HYPERSMART_ARBITRUM_RPC", "https://arb1.arbitrum.io/rpc")
BLOCS = 2000        # ~10 min d'Arbitrum. On reste poli avec le RPC public.


def _rpc(payload: dict) -> dict:
    req = urllib.request.Request(
        RPC, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:      # noqa: S310 - RPC public, lecture
        return json.loads(r.read())


def main() -> int:
    print("=" * 92)
    print("  #362 / X-01 -- DEPOTS ARBITRUM -> HYPERLIQUID : le seul signal PRE-EXECUTION")
    print("  (COPY_TRADING_NO_EDGE designe elle-meme cette voie : « le flux AVANT execution ».)")
    print("=" * 92)

    try:
        pont = valider_adresse_du_pont(os.environ.get("HYPERSMART_HL_BRIDGE_ARBITRUM"))
    except AdresseDuPontNonVerifiee as exc:
        print("\n  🔴 REFUS DE COLLECTER.\n")
        print("  %s\n" % exc)
        print("  Je n'invente PAS une adresse on-chain. Lire le mauvais contrat produirait un")
        print("  signal faux ET silencieux -- exactement ce que ce projet interdit.")
        print("\n  Verifie l'adresse du pont sur la doc officielle Hyperliquid, puis :")
        print("      set HYPERSMART_HL_BRIDGE_ARBITRUM=0x...")
        return 0                                     # ce n'est pas une erreur : c'est un REFUS

    print("  pont (fourni et valide) : %s" % pont)
    print("  RPC                     : %s" % RPC)

    try:
        tete = int(_rpc({"jsonrpc": "2.0", "id": 1,
                         "method": "eth_blockNumber", "params": []})["result"], 16)
    except Exception as exc:                          # noqa: BLE001
        print("\n  RPC INJOIGNABLE : %s: %s" % (type(exc).__name__, exc))
        print("  (etat vide honnete -- on n'invente aucun depot)")
        return 0

    print("  bloc courant            : %d" % tete)
    try:
        r = _rpc(requete_logs(pont, du_bloc=tete - BLOCS, au_bloc=tete))
        logs = r.get("result") or []
    except Exception as exc:                          # noqa: BLE001
        print("\n  eth_getLogs a echoue : %s: %s" % (type(exc).__name__, exc))
        return 0

    depots = parser_logs(logs, adresse_du_pont=pont)
    print("\n  %d logs bruts -> **%d depots** >= seuil, sur les %d derniers blocs"
          % (len(logs), len(depots), BLOCS))
    for d in sorted(depots, key=lambda x: x.montant_usd, reverse=True)[:12]:
        print("    %-12.0f $   %s   bloc %d" % (d.montant_usd, d.deposant, d.bloc))

    etat = etat_de_la_piste(depots)
    print("\n  ⚠️ ETAT HONNETE : mesure_faite = %s" % etat["mesure_faite"])
    print("     %s" % etat["mesure_qui_trancherait"])

    out = RACINE / "data" / "reports" / "depots_arbitrum.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "pont": pont, "bloc_max": tete, "blocs": BLOCS,
        "depots": [d.as_dict() for d in depots], **etat,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n  -> %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
