# Objectif Codex — HyperSmart Observer

Coller dans `/goal` de Codex. Limite: 4 000 caractères. Ce prompt: ~1 450 caractères.

---

```
Projet HyperSmart Observer — dYdX v4 paper-only copy-trading bot.
Code: hyper_smart_observer/dydx_v4/ | Tests: tests/dydx_v4/
État: 245 tests pass, 13 xfail (modules pas câblés). live_observer.py=1701 lignes.

SÉCURITÉ: paper_only=True, read_only=True, allow_trading=False. 0 ordre réel, 0 clé privée. Grep interdit: place_order, private_key, mnemonic, sign_transaction, allow_trading=True.
EDIT INTERDIT sur fichiers >500 lignes → utiliser bash/sed/python.

5 ÉTAPES:

1) Câbler trend_regime.py dans _evaluate_cluster() de live_observer.py. Détection trending/ranging via ATR ratio + EMA slope. Gate: refuser mean-reversion en trend fort. Dé-xfail test_trend_regime_sizing.py.

2) Câbler dynamic_sizing.py: notional = base × edge_factor × vol_factor × conviction_factor. Remplacer le notional fixe dans _evaluate_cluster(). Dé-xfail les tests sizing_reason de test_volume_confluence_correlation.py.

3) Ajouter correlation_gate dans _evaluate_cluster(): refuser si exposition corrélée (BTC+ETH même side) > max_correlated_same_side (config=5). Ajouter _correlated_exposure_reason, _recent_signal_sources. Dé-xfail test_leader_market_funding_consensus.py.

4) Async scan: convertir wallet_discovery.py en asyncio/aiohttp, semaphore=10, objectif 500 wallets <3s. Test mocké.

5) Vérif: pytest tests/dydx_v4/ -x -q → 0 fail, 0 xfail. Grep sécurité clean.

DONE: 0 xfail, 3 modules câblés, scan async, grep sécurité clean.
```
