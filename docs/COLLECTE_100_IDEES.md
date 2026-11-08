# 100 améliorations de collecte — maximiser les données viables, backtestables et replayables

> Non destructif (tout est **additif** : plus de sources, plus de couverture, meilleure causalité),
> **PAPER / LECTURE SEULE**. Objectif : multiplier les **jours actifs appariés fill↔carnet** (le seul
> vrai levier du LCB du labo) et la fraîcheur du signal. Rien ne casse le fail-closed ni les collecteurs
> existants.

> **Édition GRATUITE** : toutes les idées payantes ont été retirées — S3 requester-pays (coûts AWS),
> VPS/cloud payants, proxys, fournisseurs de données payants, co-location. Il ne reste que du **100 %
> gratuit** : feeds WS publics, lanes GitHub Actions (gratuit), **nœud HL en local** (logiciel libre),
> conversion/dérivation locale, qualité causale et observabilité.

## Changements de paradigme (les plus puissants)

- **Feed explorer non-cappé** `wss://rpc.hyperliquid.xyz/ws` (`subscribe_explorer_txs` / `subscribe_explorer_block`) :
  toutes les transactions on-chain (`user`, `action`, `block`, `hash`, `time`), **non filtrées par user** →
  activité + découverte de **tous** les leaders, **hors du cap 10 users/IP**. Public, gratuit.
- **Nœud Hyperliquid self-hosted EN LOCAL** (logiciel libre, gratuit) : écrit `node_fills_by_block`
  (format API) et, avec `--write-raw-book-diffs`, les **diffs d'ordre L4** → tous les fills + reconstruction
  du **carnet au niveau ordre**, sans cap ni API. On lit les fichiers que NOTRE nœud écrit (zéro coût S3).

---

## A. Sources NON-CAPPÉES (franchir le mur des 10 users)
1. Flux explorer `subscribe_explorer_txs` : capter TOUTES les tx (user/action/block/hash/time) → fills de tous les leaders.
2. Flux explorer `subscribe_explorer_block` : résumés de blocs (height, time, hash, tx_count, proposer) → horloge L1 d'alignement causal.
3. Décoder les `action` des tx explorer (order, cancel, batch) → reconstituer fills + ordres leaders depuis la chaîne.
4. Corréler tx explorer (hash) ↔ userFills WS → enrichir le détail px/sz là où l'explorer donne la couverture.
5. Lire `node_fills_by_block` écrit par NOTRE nœud local → TOUS les fills par bloc, sans cap (gratuit).
6. Lire `node_trades` / `node_fills` locaux du nœud (ancien format) → densifier les jours (gratuit).
7. Promouvoir automatiquement en whitelist les leaders les plus actifs vus dans l'explorer.
8. Découverte continue de nouveaux leaders rentables via explorer-tx (hors whitelist statique).
9. Dédupliquer explorer-tx ↔ node_fills ↔ userFills par identité (hash/tid/block) → une seule vérité, zéro double.
10. Fallback : un leader sans slot WS est couvert via explorer-tx/node_fills → couverture 100 %.

## B. Nœud Hyperliquid self-hosted (la source ultime)
11. Faire tourner un **nœud non-validateur** : `node_fills_by_block` en continu, local, sans cap ni coût S3.
12. `--write-raw-book-diffs` : capter les **diffs L4** → carnet au niveau ordre (bien au-delà des snapshots L2).
13. Seed d'état ABCI (`orderbook_snapshots`) + diffs ordonnés → **replay L4 exact** du carnet (Graal exécution).
14. Nœud = fills de TOUS les users de TOUS les coins → le labo n'est plus limité à N leaders.
15. Nœud sur le **PC local** (ou un runner self-hosted gratuit), données vers le coffre (zéro coût).
16. Snapshot périodique de l'état du nœud local → reprise rapide après redémarrage (gratuit).
17. Parser `node_raw_book_diffs_by_block` en carnets causaux horodatés par bloc.
18. Horodatage causal **au bloc** (plus précis que le wall-clock WS).
19. Capturer annulations/replacements (L4) → vrai slippage / queue position.
20. Pipeline nœud→certificateur→coffre→labo entièrement automatique.

## C. Nouveaux canaux WS (données non collectées)
21. Canal **`bbo`** natif (top-of-book léger) → BBO haute fréquence pour l'appariement sans tirer tout le L2.
22. Canal **`trades`** public (par coin) → bande de trades marché pour une exécution réaliste (fin du « mid = fill »).
23. Canal **`candle`** (OHLCV multi-intervalles) → volatilité réalisée (sizing vol) + régimes.
24. Canal **`orderUpdates`** : ordres **placés** par le leader (pas que fills) → anticiper le fill, reconstruire le metaorder tôt.
25. Canal **`userEvents`** : fills + funding + liquidations agrégés → contexte PnL complet.
26. Canaux **`userTwapSliceFills`** + **`twapStates`** : TWAP/metaorders en cours → prédire l'activité, prioriser les slots.
27. Canal **`userTwapHistory`** : historique TWAP → densifier les épisodes.
28. Canaux **`userFundings`** + **`userNonFundingLedgerUpdates`** : coût de portage + ledger → PnL net réaliste.
29. Canaux **`clearinghouseState`** / **`webData2/3`** : état complet (positions) en push → snapshots frais event-driven.
30. **`activeAssetCtx`** / **`metaAndAssetCtxs`** : mark/oracle/funding par coin → valorisation correcte.

## D. Backfill historique GRATUIT (nœud local + REST public, aucun coût)
31. Backfill des fills depuis les fichiers `node_fills_by_block` de **NOTRE nœud local** → mois de jours (gratuit).
32. REST public **`userFillsByTime`** (gratuit, borné par le rate-limit) → historique des fills de chaque leader.
33. REST public **`candleSnapshot`** (OHLCV historique) → volatilité réalisée + régimes (gratuit).
34. REST public **`fundingHistory`** → funding historique par coin (coût de portage) gratuit.
35. REST public **`l2Book`** + nos snapshots collectés en continu → carnets récents constitués gratuitement.
36. Backfill incrémental (par date/heure), idempotent, dédupliqué, certifié.
37. Convertir les fichiers du nœud local → schéma coffre (`copy_vault_l2.v1`, fills) pour le labo.
38. Prioriser le backfill sur les coins/jours où les leaders ont tradé (max jours appariés par requête).
39. Marquer l'historique « backfill » (non causal forward) comme jours de MESURE, pas de signal.
40. Vérifier la qualité (gaps, dédup, continuité) avant ingestion (le labo exige du propre).

## E. Architecture distribuée / multi-IP avancée
41. Étendre les lanes 4 → N IP (matrice GitHub) : capacité linéaire au nombre de runners.
42. Lanes sur runners **GitHub (gratuit)** + runners **self-hosted gratuits** (ton PC) → plus d'IP, zéro coût.
43. Varier les fournisseurs de CI **gratuits** (GitHub Actions, GitLab CI free, Cloudflare Workers free-tier) → IP diverses sans frais.
44. Sharding **par activité** (pas uniforme) : coins/leaders chauds sur plus de lanes.
45. Orchestrateur central qui réassigne dynamiquement users/coins aux lanes selon le débit observé.
46. Lanes « chaudes » courtes (haute fréquence) + « froides » longues (couverture) complémentaires.
47. Fenêtres de collecte **décalées** entre lanes (cron horaire échelonné) → couverture temporelle continue, sans surcoût.
48. Lanes dédiées par canal (fills / L2 / trades / explorer) pour isoler les débits.
49. Budget de souscriptions optimisé (≤ 1000) : maximiser coins × streams sous quota/connexion.
50. Auto-scaling : déclencher plus de lanes quand le débit de fills monte (marché actif).

## F. Qualité causale / replayabilité (ce dont le labo a besoin)
51. Appariement **garanti** fill↔carnet : souscrire le L2/BBO du coin **avant** le fill (anticipation sur positions ouvertes).
52. Fenêtre de fraîcheur **adaptative** par coin (liquide = serrée, illiquide = plus large) sans look-ahead.
53. Double horloge partout (exchange_ts vs received/observed) + skew mesuré par source.
54. Horodatage **monotone** (`recv_mono_ns`) systématique pour ordonner sans dépendre du wall-clock.
55. Capturer le **bloc** de chaque fill (explorer/node) → causalité au bloc, alignement parfait L2↔fill.
56. Certificat de continuité par flux (heartbeats) → prouver « aucun trou » sur une fenêtre.
57. **Snapshot L2 on-fill** : capturer le carnet à l'instant exact du fill → appariement parfait.
58. Mesurer/stocker la **latence fill→observation** par leader → quantifier la dégradation de copie (le vrai edge).
59. Reconstruire la **queue position** (L4) au moment du fill → fill maker réaliste.
60. Tag de provenance + tier (SAFE/LOCAL/NODE/ARCHIVE) sur chaque record → le labo sait quoi prouver.

## G. Débit / efficacité réseau
61. permessage-deflate (fait) + négocier la compression serveur maximale.
62. `post` WS (envelopper les requêtes info dans le WS) → éviter des connexions REST séparées.
63. Flag d'**agrégation** `userFills` (merge partiels du même ordre/bloc) → moins de bruit, plus de signal.
64. Batching des souscriptions au démarrage en respectant 30 conn/min.
65. Réutiliser une connexion pour plusieurs canaux (coins) jusqu'au quota/connexion.
66. Backpressure + file bornée **par canal** (jamais de perte silencieuse, compter les drops).
67. Parsing incrémental zéro-copie (orjson) pour tenir le débit en pointe.
68. **Delta-encoding** des carnets (stocker les diffs, pas les snapshots complets) → moins de volume, plus d'historique.
69. Compression colonnaire (Parquet/zstd) du coffre → plus de jours à coût égal.
70. Dédup en streaming (Bloom filter borné) pour fusionner multi-sources sans exploser la RAM.

## H. Résilience / complétude (zéro trou)
71. Gap-fill REST `userFillsByTime` au reconnect (fait) + gap-fill `node_fills_by_block` pour les trous longs.
72. Watermark persistant par (user, coin) → reprise exacte après coupure/redémarrage.
73. Réconciliation croisée WS ↔ node ↔ explorer : l'un comble ce que l'autre manque.
74. Détection de connexion muette (pas de msg/pong) → recyclage ciblé de la socket fautive.
75. Confirmation de chaque subscribe (`subscriptionResponse`) + re-subscribe (fait).
76. Heartbeat de complétude : alerter si un leader attendu n'émet rien depuis X (slot gaspillé).
77. Checkpoint atomique + fsync + rotation des tapes (anti-crash).
78. Rejeu idempotent : réingérer un lot deux fois ne crée aucun double (identité stable).
79. Quarantaine des trames non causales/incohérentes (jamais inventer, jamais perdre en silence).
80. Audit périodique « jours couverts » par coin → cibler la collecte là où il manque des jours.

## I. Intelligence de collecte (adaptatif, prédictif)
81. Allocation des slots WS par **bandit** (fait) + réévaluation continue sur le débit réel.
82. Prédire les fenêtres d'activité d'un leader (profil horaire, TWAP en cours) → pré-souscrire.
83. Suivre les **positions ouvertes volatiles** (via `clearinghouseState`) → pré-souscrire le L2 du coin visé.
84. Découverte continue de leaders via explorer-tx (volume/rentabilité) → whitelist auto-enrichie.
85. Scoring de « valeur causale » par leader (jours appariés produits) → concentrer la collecte sur les plus utiles.
86. Cadence de poll **adaptative** à l'activité (plus quand ça trade, moins quand c'est calme).
87. Détection de régime (volatilité) → intensifier la collecte en régime actif (plus d'edge à capter).
88. Priorisation L2 par coin/heure où les leaders tradent (pas uniforme).
89. Boucle fermée : le labo signale les coins/jours manquants → collecte ciblée.
90. Auto-tuning des seuils (fraîcheur, lag) selon la qualité mesurée, sans affaiblir le fail-closed.

## J. Observabilité, gouvernance & enrichissement
91. Dashboard par flux (débit, fraîcheur, gaps, taux de capture) en JSON (sans changer l'affichage `.cmd`).
92. Métrique « taux de capture » par leader (captés vs attendus on-chain) → mesurer les manques.
93. Catalogue intelligent du coffre (coin × jour × tier × famille) → le labo cible instantanément.
94. Enrichir chaque fill avec son contexte (mark, funding, L2 au moment, bloc) → records auto-suffisants pour le replay.
95. Dériver une BBO cross-venue (binance/bybit/okx/bitget déjà) comme référence de prix robuste.
96. Calculer/stocker la capacité (profondeur × prix) par snapshot → tests de capacité réalistes.
97. Signatures de qualité par lot (SHA, continuité, complétude) dans le manifeste → certification traçable.
98. Déduplication inter-sources canonique (une identité unique fill/book partagée partout).
99. Versioning de schéma des flux (évolutif) → ne jamais casser le labo lors d'ajouts.
100. Pipeline end-to-end **tout-automatique** : node/lanes → dédup/certif → coffre → labo, piloté par les manques détectés.

---

## Priorisation recommandée (impact × faisabilité, non destructif)
1. **Feed explorer `subscribe_explorer_txs`** (#1-#10) — franchit le cap 10 users immédiatement, nouveau collecteur autonome.
2. **Backfill GRATUIT** (#31-#40 : nœud local + REST public `userFillsByTime`/`candleSnapshot`/`fundingHistory`) — mois de jours, convertible au schéma coffre.
3. **Nouveaux canaux WS** `bbo`/`trades`/`candle`/`orderUpdates`/`clearinghouseState` (#21-#30) — ajouts additifs aux lanes.
4. **Nœud self-hosted + L4** (#11-#20) — la source ultime (plus d'infra, plus gros gain).
5. **Appariement causal garanti + enrichissement** (#51-#60, #94) — convertit la donnée brute en jours scoreables.

## Sources (API & données Hyperliquid)
- [Hyperliquid WebSocket subscriptions guide (OnFinality)](https://onfinality.io/en/learn/hyperliquid-websocket-subscriptions-guide)
- [Hyperliquid WebSocket trades & fills mechanics (OnFinality)](https://onfinality.io/en/learn/hyperliquid-websocket-trades-fills-channel-mechanics)
- [WebSocket API quick reference (Dwellir)](https://www.dwellir.com/docs/hyperliquid/websocket-api)
- [Hyperliquid WS.md (carter2099 mirror)](https://github.com/carter2099/hyperliquid/blob/main/docs/WS.md)
- [Hyperliquid API.md (carter2099 mirror)](https://github.com/carter2099/hyperliquid/blob/main/docs/API.md)
- [Post requests / WS post (Hyperliquid docs)](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/post-requests)
- [Info endpoint (Hyperliquid docs)](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
- [Rate limits & user limits (Hyperliquid docs)](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits)
- [Info endpoint request types (HL docs)](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint) — `userFillsByTime`, `candleSnapshot`, `fundingHistory`, `l2Book` (REST public gratuit)
- [Hyperliquid order book data: L2, L4 & history (Ironflow)](https://ironflow.sh/guides/hyperliquid-order-book-data) — *contexte ; node_fills via NOTRE nœud local (gratuit), pas S3 payant*

> Note : les sources S3 requester-pays et fournisseurs de données payants (archives tierces) ont été
> **retirées** — cette édition n'utilise que des sources gratuites (WS/REST publics, nœud local, CI gratuit).
