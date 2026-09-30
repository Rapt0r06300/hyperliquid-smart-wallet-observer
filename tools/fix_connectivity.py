"""Trouve un chemin réseau qui MARCHE vers Hyperliquid (read-only), malgré un DNS
local cassé / proxy / VPN. Essaie plusieurs méthodes et dit laquelle réussit.

Lance:  python tools/fix_connectivity.py
Aucune clé, aucun ordre, lecture seule. Sortie = la méthode à câbler dans le bot.

Méthodes testées:
  A) DNS système + HTTPS direct (le défaut actuel)
  B) DNS-over-HTTPS (DoH via Cloudflare/Google) -> IP -> HTTPS direct (SNI)
  C) Proxy système (HTTPS_PROXY/HTTP_PROXY de l'environnement, comme le navigateur)
  D) WebSocket wss:// (direct, puis via IP DoH)
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import sys
import time
import urllib.request

HOST = "api.hyperliquid.xyz"
INFO_PATH = "/info"


def _ok(s): return f"[OK]   {s}"
def _ko(s): return f"[KO]   {s}"


def test_system_dns() -> str | None:
    try:
        ip = socket.gethostbyname(HOST)
        print(_ok(f"A) DNS système -> {ip}"))
        return ip
    except Exception as e:
        print(_ko(f"A) DNS système échoue: {e}"))
        return None


def doh_resolve() -> str | None:
    """Résout HOST via DNS-over-HTTPS (sans dépendre du DNS local)."""
    endpoints = [
        ("https://1.1.1.1/dns-query?name=%s&type=A" % HOST, {"accept": "application/dns-json"}),
        ("https://dns.google/resolve?name=%s&type=A" % HOST, {}),
    ]
    for url, headers in endpoints:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "hs-doh", **headers})
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
                data = json.loads(r.read().decode())
            answers = [a["data"] for a in data.get("Answer", []) if a.get("type") == 1]
            if answers:
                print(_ok(f"B) DoH ({url.split('/')[2]}) -> {answers[0]}"))
                return answers[0]
        except Exception as e:
            print(_ko(f"B) DoH {url.split('/')[2]} échoue: {e}"))
    return None


def test_rest_direct(ip: str | None) -> bool:
    """POST /info allMids, soit par hostname (DNS OK), soit par IP+SNI (DoH)."""
    try:
        import httpx
    except Exception as e:
        print(_ko(f"   httpx absent: {e}")); return False
    payload = {"type": "allMids"}
    try:
        if ip:
            # connexion par IP, mais SNI + Host = hostname (TLS valide)
            transport = httpx.HTTPTransport(retries=1)
            with httpx.Client(timeout=12, transport=transport, verify=True,
                              headers={"Host": HOST}) as c:
                # httpx ne permet pas trivialement IP+SNI; on tente via resolution forcée
                url = f"https://{HOST}{INFO_PATH}"
                r = c.post(url, json=payload, extensions={"sni_hostname": HOST})
        else:
            with httpx.Client(timeout=12) as c:
                r = c.post(f"https://{HOST}{INFO_PATH}", json=payload)
        ok = r.status_code == 200 and isinstance(r.json(), dict)
        print((_ok if ok else _ko)(f"   REST /info -> HTTP {r.status_code}, {len(r.json()) if ok else '?'} marchés"))
        return ok
    except Exception as e:
        print(_ko(f"   REST /info échoue: {e}")); return False


def test_rest_system_proxy() -> bool:
    try:
        import httpx
    except Exception:
        return False
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    if not proxy:
        print("   C) Aucun proxy système dans l'environnement (HTTPS_PROXY vide).")
        return False
    try:
        with httpx.Client(timeout=12, trust_env=True) as c:
            r = c.post(f"https://{HOST}{INFO_PATH}", json={"type": "allMids"})
        ok = r.status_code == 200
        print((_ok if ok else _ko)(f"   C) REST via proxy système ({proxy}) -> HTTP {r.status_code}"))
        return ok
    except Exception as e:
        print(_ko(f"   C) REST via proxy système échoue: {e}")); return False


def test_ws(ip: str | None) -> bool:
    try:
        import websocket  # websocket-client
    except Exception as e:
        print(_ko(f"   websocket-client absent: {e}")); return False
    url = f"wss://{HOST}/ws"
    try:
        if ip:
            sslopt = {"server_hostname": HOST}  # SNI correct sur IP
            ws = websocket.create_connection(f"wss://{ip}/ws", timeout=10, sslopt=sslopt,
                                             header=[f"Host: {HOST}"])
        else:
            ws = websocket.create_connection(url, timeout=10)
        ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "trades", "coin": "BTC"}}))
        n = 0; end = time.time() + 8; ws.settimeout(2)
        while time.time() < end:
            try:
                m = ws.recv()
                if m and ("trade" in m.lower() or "data" in m.lower()): n += 1
            except Exception:
                pass
        ws.close()
        ok = n > 0
        print((_ok if ok else _ko)(f"   D) WS {'via IP DoH' if ip else 'direct'} -> {n} messages en 8s"))
        return ok
    except Exception as e:
        print(_ko(f"   D) WS échoue: {e}")); return False


def main() -> int:
    print(f"=== Recherche d'un chemin réseau vers {HOST} (read-only) ===\n")
    sys_ip = test_system_dns()
    doh_ip = None if sys_ip else doh_resolve()

    print("\n-- REST --")
    rest_direct = test_rest_direct(sys_ip)
    rest_doh = test_rest_direct(doh_ip) if (doh_ip and not rest_direct) else False
    rest_proxy = test_rest_system_proxy() if not (rest_direct or rest_doh) else False

    print("\n-- WebSocket --")
    ws_direct = test_ws(None) if sys_ip else False
    ws_doh = test_ws(doh_ip) if (doh_ip and not ws_direct) else False

    print("\n========== VERDICT ==========")
    if rest_direct and ws_direct:
        print("Le réseau marche en direct. Le 'WS OFF' n'est PAS réseau -> envoie logs/hypersmart_poller_stderr.log.")
    elif (rest_doh or ws_doh):
        print(">>> SOLUTION TROUVÉE: DoH (le DNS local est cassé, mais résoudre via 1.1.1.1 marche).")
        print("    Dis-moi 'câble le DoH' et je l'intègre aux clients du bot (REST + WS).")
    elif rest_proxy:
        print(">>> SOLUTION TROUVÉE: ton accès passe par un PROXY système.")
        print("    Dis-moi 'câble le proxy' et je fais lire le proxy système par le bot (trust_env).")
    elif rest_direct or rest_doh:
        print(">>> REST marche mais PAS la WS -> firewall/antivirus bloque le WebSocket (wss).")
        print("    Solution: mode REST-only (polling fréquent des fills) — dis 'câble le mode REST-only'.")
    else:
        print(">>> Rien n'atteint Hyperliquid depuis Python: blocage total (antivirus/pare-feu/VPN).")
        print("    Autorise python.exe dans le pare-feu + antivirus, coupe le VPN, reteste.")
        print("    (Ton navigateur marche peut-être via un proxy que Python ne voit pas.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
