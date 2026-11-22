# Matrice des données externes gratuites — CopyVault (22/11/2026, 23:40 heure de Paris)

Niveaux : **1** descriptif · **2** études d'événements · **3** backtest sous hypothèses explicites ·
**4** replay d'exécution rigoureux (jamais accordé sans carnet vérifié, ordre des événements et
disponibilité réelle de l'information) · **5** inutilisable pour l'objectif.
Aucune source externe n'est SAFE : aucune ne porte l'heure de RÉCEPTION par Alina.

| Source | Contenu | Période | Licence / accès | Wallets | Vérifié | Niveau | Statut chez nous |
|---|---|---|---|---|---|---|---|
| **Ironflow** funding | taux réglés + premium, 494 marchés | 12/05/2023 → 31/10/2026, horaire depuis 08/06/2023 | CC BY 4.0, gratuit, HF | — | SHA-256 + schéma ; **identique** à nos données sur 860 570 paires | 2 | **intégré** (42 fichiers) |
| **Ironflow** open interest | OI, mark, oracle horaires, 553 perps | 20/05/2023 → 31/10/2026 | CC BY 4.0 | — | SHA-256 + schéma ; 4 lignes HIP-3 à OI négatif exclues | 2 | **intégré** (42) |
| **Ironflow** liquidations | events (1/position) + fills, 468 marchés | 25/05/2025 → 31/10/2026 | CC BY 4.0 | **oui** | SHA-256 + schéma | 2 | **intégré** (36) ; H17 mesurée, H18 en attente |
| **Ironflow** bougies 1 h | OHLCV de tous les fills, 799 marchés (délistés, HIP-3) | 25/05/2025 → 31/10/2026 | CC BY 4.0 | — | SHA-256 + OHLC ; écart médian 0 bps avec nos bougies (793 015 paires) | 2–3 | **intégré** (18) |
| Ironflow trades | 1 ligne/trade avec acheteur et vendeur | 03/10 → 08/11/2026 | CC BY 4.0 avant le 10/11, **CC BY-NC** après | oui | — | 2 | non ingéré : 5,3 Go, période déjà consultée |
| Ironflow HIP-4 | marchés à issue | 08/2026 → 11/2026 | CC BY 4.0 | — | — | 5 | hors périmètre |
| Zenodo L4 (Albers et al.) | statuts d'ordres + rejets, diffs de carnet BTC/ETH/SOL | **déc. 2025** | ouvert | oui | métadonnées seulement | 2 (micro) | non téléchargé : ~195 Go, hors de la période de nos leaders ; rejets non observables en direct |
| OKX historique | trades (2021→), bougies, funding, L2 haute résolution (2023→) | longue | gratuit | non | — | 1–2 (contexte) | module existant `official_archive_backfill` ; jamais pour simuler une exécution Hyperliquid |
| Binance data.binance.vision | aggTrades, trades, klines, métriques | longue | gratuit, checksums officiels | non | — | 1–2 (contexte) | module existant ; Lead-Lag désactivé : variable explicative seulement |
| Bybit public.bybit.com | trades | longue | gratuit | non | listing | 1–2 | module existant |
| Bybit quote-saver.bycsi.com | carnets | ? | **origine non vérifiée** (domaine tiers) | non | listing seul | 5 tant que non audité | non utilisé |
| **Tardis.dev Hyperliquid** | `incremental_book_L2` (profondeur complète), `trades` (avec **acheteur et vendeur** depuis le 01/12/2024), `derivative_ticker` ; horodatage local de réception de Tardis | depuis le 29/10/2024 ; **1er jour de chaque mois gratuit** sans clé | gratuit ces jours-là seulement | oui (trades) | doc officielle lue | 3, candidat 4 pour tester le moteur d'exécution (carnet complet + ordre de capture) — l'heure de réception est celle de Tardis, pas d'Alina | **intégré** : 24 fichiers, 326 Mo (BTC, ETH, HYPE ; 01/05, 01/06, 01/07, 01/08/2026), 24,0 h chacun. **Mesuré** : ce « L2 incrémental » est en fait une suite d'INSTANTANÉS toutes les ~0,54 s, **20 niveaux** par côté jusqu'en juin puis **5 niveaux** dès juillet ; trou de capture de ~3,5 min le 01/08 (tous coins). → coût d'un petit ordre au BBO : oui ; profondeur complète : non. Niveau 3. |
| Nœud Hyperliquid | tous les fills de tous les comptes | temps réel | gratuit mais **128 Go de RAM, 500 Go + 100 Go/jour** | oui | doc officielle | 4 potentiel | **impossible sur ce PC** (32 Go) |

## Ce que ces données ont changé (22/11)
- Liquidations : de « inmesurable » à mesurées. Essai 33 (H17) : `REJECTED` pour la copie ; fait de marché :
  les vagues CONTINUENT (−72,9 bps à 24 h pour l'absorbeur, [−149 ; −0,6]).
- Le funding et les bougies de notre corpus sont confirmés par une source indépendante.

## Bloqué / à faire
- H18 attend le fichier Ironflow de novembre (début décembre).
- Aucune source temps réel de liquidations réalisées : un filtre fondé sur elles n'est pas applicable en direct.
- Tardis : Hyperliquid confirmé (gratuit le 1er du mois) ; ingestion d'un jour d'exploration à faire, bornée.
- Tardis L2 Hyperliquid = instantanés top-20 puis top-5 (mesuré) : ne pas l'appeler carnet complet.
