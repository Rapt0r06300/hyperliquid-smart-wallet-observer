"""#598 — DIAGNOSTIC : QUI refuse ? On ne devine pas, on LIT.

⚠️ TEST DE DIAGNOSTIC TEMPORAIRE. Il n'assert presque rien : il IMPRIME.
Il sera supprime des que la cause sera trouvee et corrigee.

Pourquoi il existe : j'ai accuse le garde-fou breakeven, je l'ai corrige a la racine, et les
deux tests UI sont restes ROUGES. *Un diagnostic non verifie par execution ne vaut rien.*
On rejoue donc EXACTEMENT la meme fixture que le test rouge -- en reutilisant SES helpers,
pour ne pas fabriquer un scenario different -- et on affiche le motif de refus reel.

Lancer : python -m pytest -q -s tests/test_diag_598_qui_refuse.py
"""

from __future__ import annotations

import json
from pathlib import Path

from hl_observer.storage.models import MarketSnapshot
from hl_observer.utils.time import now_ms

# On REUTILISE les helpers du test rouge : meme client, meme leader, meme delta.
from tests.test_ui_simulation_v9_filters import _client, _leader, _open_delta


def test_DIAG_qui_refuse_le_cluster_frais(tmp_path: Path, monkeypatch):
    # --- fixture IDENTIQUE au test rouge (test_ui_simulation_v9_filters:285) ---
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    monkeypatch.setenv("HYPERSMART_V9_PIPELINE_AUTHORITATIVE", "1")
    monkeypatch.setenv("HYPERSMART_SIMULATION_MIN_EDGE_BPS", "5")
    monkeypatch.setenv("HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS", "30000")
    monkeypatch.setenv("HYPERSMART_FRESH_OPPORTUNITY_MIN_WALLETS", "2")
    monkeypatch.setenv("HYPERSMART_RUNTIME_DEPTH_FILL_GUARD", "0")
    monkeypatch.setenv("HYPERSMART_RUNTIME_MICROSTRUCTURE_GUARD", "0")

    client, factory, _state = _client(tmp_path)
    ts = now_ms()
    wallet_a = "0x" + "a" * 40
    wallet_b = "0x" + "b" * 40
    with factory() as session:
        session.add(_leader(wallet_a, rank=1, ts=ts))
        session.add(_leader(wallet_b, rank=2, ts=ts))
        session.add(MarketSnapshot(source="allMids", exchange_ts=ts, raw_json={"ETH": "3000"}))
        session.add(_open_delta(
            wallet_a, ts=ts - 2_000,
            raw={"coin": "ETH", "dir": "Open Long", "hash": "fresh-cluster-a", "time": ts - 2_000},
            source="hyperliquid_ws:userFills",
        ))
        session.add(_open_delta(
            wallet_b, ts=ts - 1_000,
            raw={"coin": "ETH", "dir": "Open Long", "hash": "fresh-cluster-b", "time": ts - 1_000},
            source="hyperliquid_ws:userFills",
        ))
        session.commit()

    payload = client.get("/api/simulation/overview?limit=40").json()

    bot = payload.get("bot_simulation") or {}

    print("\n" + "=" * 78)
    print("  #598 — QUI REFUSE ? (motifs REELS, lus, pas devines)")
    print("=" * 78)

    print("\n--- fresh_opportunities ---")
    for row in payload.get("fresh_opportunities") or []:
        print("  decision=%-28s reason=%-42s coin=%s edge=%s age=%s"
              % (row.get("decision"), row.get("reason") or row.get("no_trade_reason"),
                 row.get("coin"), row.get("expected_edge_bps"), row.get("signal_age_ms")))
    if not (payload.get("fresh_opportunities") or []):
        print("  (AUCUNE fresh_opportunity : le refus est encore PLUS EN AMONT)")

    print("\n--- counts ---")
    print("  %s" % json.dumps(payload.get("counts") or {}, ensure_ascii=False))

    print("\n--- prefilter_skips (le pre-filtre a-t-il jete le signal ?) ---")
    print("  prefilter_skip_count = %s" % bot.get("prefilter_skip_count"))
    for row in (bot.get("prefilter_skips") or [])[:20]:
        print("    %s" % json.dumps(row, ensure_ascii=False))

    print("\n--- filter_diagnostics ---")
    print("  %s" % json.dumps(bot.get("filter_diagnostics") or {}, ensure_ascii=False))

    print("\n--- events (motifs de NO_TRADE) ---")
    for row in (bot.get("events") or [])[:25]:
        print("    coin=%-8s reason=%s" % (row.get("coin"), row.get("reason")))

    print("\n--- refusal_reasons / no_trade ---")
    for cle in ("refusal_reasons", "no_trade_reasons", "no_trade_breakdown", "gate_rejections"):
        if bot.get(cle) is not None:
            print("  %-20s : %s" % (cle, json.dumps(bot.get(cle), ensure_ascii=False)[:600]))

    print("\n--- open_positions ---")
    print("  %s" % json.dumps(bot.get("open_positions") or [], ensure_ascii=False)[:400])
    print("=" * 78 + "\n")

    # Aucun assert de verdict : ce fichier DIAGNOSTIQUE, il ne juge pas.
    assert payload is not None
