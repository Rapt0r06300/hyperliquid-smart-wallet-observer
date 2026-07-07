# Fusion #13 — Polymarket/agents

**Repo:** https://github.com/Polymarket/agents — "Trade autonomously on Polymarket using AI Agents". 2.8k★, officiel Polymarket, Python 99.6%, MIT.
**Venue d'origine:** Polymarket. **Notre cible:** dYdX v4 (paper) + HL comparatif.

## Architecture observée
- `agents/connectors/` — couche de connecteurs qui **standardise les sources de données et les types d'ordre**:
  - `Chroma.py`: vector DB (Chroma) pour vectoriser news & données API → RAG.
  - `Gamma.py`: `GammaMarketClient` — fetch/parse metadata marchés & events (marchés courants/tradables, infos par marché).
  - `Polymarket.py`: classe d'interaction API — récupération données + **exécution d'ordres sur le DEX** (init clé API, build & sign orders).
  - `Objects.py`: **modèles de données Pydantic** — trades, markets, events, entités liées.
- `scripts/python/cli.py`: interface CLI (commandes: `get-all-markets --limit --sort-by`, news retrieval, query local data, prompts LLM, execute trades).
- `agents/application/trade.py`: boucle de trading autonome.
- RAG local & distant; sources: betting services, news providers, web search.

## KEEP (offline / recherche uniquement)
1. **Couche connecteurs standardisée (data sources + normalisation).** Pattern excellent: un client par source qui *normalise* vers des modèles internes. → on a déjà `dydx_v4/indexer_rest` + `indexer_ws`; formaliser un `connectors/` avec un client par flux (markets, accounts, fills, orderbook) renvoyant des **modèles Pydantic** unifiés.
2. **`Objects.py` = modèles Pydantic pour trades/markets/events.** → adopter Pydantic (ou dataclasses validées) pour normaliser accounts/subaccounts/positions/orders/fills dYdX. Validation stricte = refus des deltas UNKNOWN / mappings douteux (notre exigence "refuser les marchés mal mappés").
3. **RAG local pour la RECHERCHE (offline, jamais hot path).** Vectoriser news/contexte marché pour *enrichir l'analyse a posteriori* d'un signal (pourquoi un wallet a bougé), **hors du chemin de décision temps réel**. → respecte "no LLM in hot path". Range dans `research/` uniquement, pas dans le pipeline signal→paper.
4. **CLI structurée par commande** (`command_name [attr value]`). → notre `cli.py` HL suit déjà ce style; le dupliquer pour `python -m dydx_v4 ...` (discover-markets, scan, backtest, replay, dashboard).
5. **`get-all-markets --sort-by volume`**: tri par volume comme défaut de découverte. → notre discovery dYdX doit trier les marchés par liquidité/volume pour prioriser les marchés liquides (filtre illiquidité).

## ADAPT_TO_DYDX
- `Gamma.py` (Gamma API Polymarket) → équivalent **Indexer REST dYdX v4** (markets, perpetualMarkets, candles). Même rôle: metadata + snapshots.
- Tri/sélection des marchés "tradables" → notre shortlist de marchés liquides + bien mappés.

## BAN (jamais)
- `Polymarket.py` build/sign/execute orders + `POLYGON_WALLET_PRIVATE_KEY` → **clé privée + signature + ordre réel. Interdit absolu.**
- `agents/application/trade.py` (boucle autonome qui trade) → **BAN runtime.** On ne lance jamais une boucle qui poste des ordres.
- `OPENAI_API_KEY` dans le chemin de décision → **no LLM in hot path.** LLM toléré seulement en recherche offline.
- "Load your wallet with USDC" / "just go trade" → argent réel. Interdit.
- Note ToS: Polymarket interdit les US persons; de toute façon **aucune** exécution réelle chez nous, tous venues confondus.

## DEFER
- Orchestration LLM agentique complète (prompt engineering tools, autonomous reasoning loop). Intéressant pour un *assistant de recherche*, pas pour le bot de copie. DEFER derrière un flag recherche.

## OR OUBLIÉ (pépites V9)
- **Modèles Pydantic stricts comme frontière anti-corruption**: tout ce qui entre du marché passe par un modèle validé → un fill/delta non conforme est rejeté *à la frontière*, pas plus loin. C'est l'implémentation concrète de nos règles "refuser deltas UNKNOWN / closes orphelins / marchés mal mappés".
- **RAG d'evidence pour l'audit**: après coup, attacher au DecisionLedger un contexte (news/why) récupéré par RAG → enrichit la *traçabilité* d'une décision sans polluer le hot path. Pur read-only, offline.
- **Séparation `connectors/` (I/O brut normalisé) vs `application/` (logique)**: discipline d'architecture qui garde l'I/O testable/mockable → renforce nos tests "REST mocké / WS mocké".
