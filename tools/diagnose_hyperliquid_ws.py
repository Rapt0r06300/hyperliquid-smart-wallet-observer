"""Diagnostic réseau Hyperliquid (read-only) — pour comprendre le "WS OFF".

Lance:  python tools/diagnose_hyperliquid_ws.py
Teste, depuis CETTE machine: (1) DNS, (2) REST /info, (3) WebSocket trades.
Aucune clé, aucun ordre, lecture seule. Dit clairement si le souci est le RÉSEAU
de la machine (DNS/firewall/VPN/antivirus) ou autre chose.
"""

from __future__ import annotations

import json
import socket
import sys
import time

HOST = "api.hyperliquid.xyz"


def main() -> int:
    print(f"=== Diagnostic Hyperliquid (read-only) — {HOST} ===\n")

    # 1) DNS
    print(f"[1/3] Résolution DNS de {HOST} ...")
    try:
        ip = socket.gethostbyname(HOST)
        print(f"      OK -> {ip}\n")
    except Exception as e:
        print(f"      ECHEC DNS: {e}")
        print("\n>>> VERDICT: ta machine NE RESOUT PAS Hyperliquid (DNS).")
        print("    C'est exactement le 'Temporary failure in name resolution' de tes logs.")
        print("    Cause = DNS/VPN/firewall/antivirus/proxy systeme. AUCUN code ne corrige ca.")
        print("    A faire: desactive VPN/proxy, change de DNS (1.1.1.1 / 8.8.8.8), autorise python dans le pare-feu, reteste.")
        return 1

    # 2) REST /info
    print("[2/3] REST POST /info (allMids) ...")
    rest_ok = False
    try:
        import httpx

        r = httpx.post(f"https://{HOST}/info", json={"type": "allMids"}, timeout=10.0)
        if r.status_code == 200:
            mids = r.json()
            print(f"      OK -> HTTP 200, {len(mids)} marches recus\n")
            rest_ok = True
        else:
            print(f"      HTTP {r.status_code} (inattendu)\n")
    except Exception as e:
        print(f"      ECHEC REST: {e}")
        print("      (Si DNS OK mais REST KO -> firewall/proxy bloque le HTTPS sortant.)\n")

    # 3) WebSocket trades
    print("[3/3] WebSocket wss://%s/ws (subscribe trades BTC, 8s) ..." % HOST)
    try:
        import websocket  # websocket-client

        ws = websocket.create_connection(f"wss://{HOST}/ws", timeout=10)
        ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "trades", "coin": "BTC"}}))
        received = 0
        deadline = time.time() + 8
        ws.settimeout(2)
        while time.time() < deadline:
            try:
                msg = ws.recv()
                if msg and ("trade" in msg.lower() or "data" in msg.lower()):
                    received += 1
            except Exception:
                pass
        ws.close()
        print(f"      messages WS recus en 8s: {received}\n")
        if received > 0:
            print(">>> VERDICT: le RESEAU MARCHE (DNS + REST + WS OK).")
            print("    Le 'WS OFF' du dashboard n'est donc PAS reseau -> envoie logs/hypersmart_poller_stderr.log")
            print("    (le log du run actuel) pour que je corrige le scan/flag WS cote code.")
            return 0
        print(">>> VERDICT: WS connecte mais 0 message recu (rare).")
        print("    Reteste; si ca persiste, envoie logs/hypersmart_poller_stderr.log.")
        return 0
    except Exception as e:
        print(f"      ECHEC WS: {e}")
        print("\n>>> VERDICT: la WS Hyperliquid est INJOIGNABLE depuis ta machine.")
        if rest_ok:
            print("    REST marche mais pas la WS -> firewall/antivirus/proxy bloque le WebSocket (wss://). ")
        else:
            print("    Ni REST ni WS -> firewall/VPN/antivirus/proxy bloque le sortant vers Hyperliquid.")
        print("    AUCUN code ne corrige ca: desactive VPN/proxy, autorise python.exe dans le pare-feu/antivirus, reteste.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
