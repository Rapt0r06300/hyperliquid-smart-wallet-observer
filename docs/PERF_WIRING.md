# PERF — câblage anti-throttle / anti-ban (à appliquer sur Windows)

Modules livrés + testés cette session (16 tests verts) :
- `collection/ws_first_plan.py` — WS-first (coupe le REST couvert par le firehose).
- `collection/concurrent_fetch.py` — dimensionnement anti-ban (poids/min → wallets/cycle) + `bounded_gather`.
- `collection/proxy_config.py` — rotation multi-proxy (Webshace & co), fallback direct sûr.

Le câblage ci-dessous n'est **pas** appliqué automatiquement parce que `collector.py`
et `rest_info_client.py` tombent dans la zone de troncature du mount sandbox
(les éditer ici risquerait de committer un fichier tronqué). Sur Windows il n'y a
pas de troncature : applique ces patches, puis `set PYTHONPATH=src && python -m pytest -q`.

---

## 1) WS-first — arrête le dépassement 4000 > 1200 poids/min (GRATUIT, aucun proxy)

Dans `src/hl_observer/collection/collector.py`, fonction `run_collection_once`,
juste après la résolution multi-actifs (~ligne 185), ajouter **2 lignes** :

```python
    if plan.all_coins or plan.coins_from_meta or plan.coins_from_all_mids:
        plan = await _resolve_multi_asset_plan(plan, settings, client=client)
    from hl_observer.collection.ws_first_plan import reduce_plan_from_env
    plan = reduce_plan_from_env(plan)   # WS-first: coupe le REST couvert par le WS (no-op sauf flag)
    result = CollectionResult(planned_items=plan.requested_items(), dry_run=plan.dry_run)
```

Activation (launcher `LANCER_HYPERSMART.cmd`) :

```bat
set "HYPERSMART_WS_FIRST_COLLECT=1"
set "HYPERSMART_WS_FIRST_CHANNELS=allMids,userFills"
```

Effet mesuré : ~1002 poids/cycle économisés pour 50 leaders (userFills + allMids
cessent d'être re-pollés en REST puisque le WS les pousse déjà). Conservateur :
ne coupe que les canaux déclarés frais ; sinon garde le REST (jamais de trou).

---

## 2) Proxies — multiplie le plafond (10 IP Webshare gratuites = ~12 000 poids/min)

Dans `src/hl_observer/hyperliquid/rest_info_client.py`, là où le client est construit
(`httpx.AsyncClient(timeout=self.timeout_seconds)`), injecter un proxy tournant :

```python
from hl_observer.collection.proxy_config import ProxyRotator
_ROTATOR = ProxyRotator.from_env()

# à la construction du client :
proxy = _ROTATOR.next_url()
self._client = httpx.AsyncClient(timeout=self.timeout_seconds, proxy=proxy) if proxy \
    else httpx.AsyncClient(timeout=self.timeout_seconds)
```

Activation : crée un compte Webshare (offre gratuite 10 proxies), puis :

```bat
set "HYPERSMART_HTTP_PROXIES=http://user:pass@ip1:port,http://user:pass@ip2:port,..."
```

`ProxyRotator` tourne sur les IP saines, écarte automatiquement celles qui prennent
des 429/403, et retombe en direct si tout meurt. `egress_count()` = multiplicateur
de budget. **Ne PAS** utiliser de listes publiques de proxies gratuits (instables,
non fiables) : palier gratuit d'un vrai fournisseur uniquement.

---

## 3) Concurrence bornée (finir un cycle plus vite sans burst)

`collection/concurrent_fetch.py` fournit :
- `max_wallets_per_cycle(...)` — combien de leaders tu peux poller/cycle sous budget ;
- `recommended_concurrency(...)` — parallélisme pour finir avant l'échéance ;
- `bounded_gather(factories, limit=...)` — exécution parallèle bornée, ordre préservé,
  échecs isolés.

À utiliser pour paralléliser la boucle `for wallet in plan.wallets` de `_collect_plan`
(chantier séparé : envelopper chaque bloc wallet dans une coroutine + `bounded_gather`).

---

## Ordre recommandé
1. WS-first (gratuit, plus gros gain, aucune dépendance externe).
2. Proxies (si tu veux suivre beaucoup plus de wallets).
3. Concurrence (latence de cycle, après WS-first).

Sécurité inchangée : lecture seule, 0 ordre réel, 0 clé, 0 signature.
