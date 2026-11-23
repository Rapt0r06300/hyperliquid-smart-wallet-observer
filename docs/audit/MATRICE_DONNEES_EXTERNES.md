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
| **Archive officielle Hyperliquid (S3)** | `hyperliquid-archive` : carnets L2 horaires + contextes d'actifs ; `hl-mainnet-node-data` : fills nœud par bloc (`node_fills_by_block`), blocs, événements (funding, transferts) | mensuelle, « sans garantie, données parfois manquantes » (doc officielle, lue le 23/11) | **le demandeur paie le transfert** (requester pays) : compte AWS + dépense | oui (fills nœud) | doc officielle | 4 potentiel (fills de tous les comptes) | **non utilisée : dépense et création de compte soumises à votre accord**. **Accès GRATUIT vérifié le 23/11 (requête anonyme, 0 €) : `hyperliquid-archive` (us-east-1) et `hl-mainnet-node-data` (ap-northeast-1) répondent 403 AccessDenied** ; sonde complète `tools/sonder_archive_s3.py` (exige la CLI aws, absente) |
| Nœud Hyperliquid | tous les fills de tous les comptes | temps réel | gratuit mais **128 Go de RAM, 500 Go + 100 Go/jour** | oui | doc officielle | 4 potentiel | **impossible sur ce PC** (32 Go) |

## Ce que ces données ont changé (22/11)
- Liquidations : de « inmesurable » à mesurées. Essai 33 (H17) : `REJECTED` pour la copie ; fait de marché :
  les vagues CONTINUENT (−72,9 bps à 24 h pour l'absorbeur, [−149 ; −0,6]).
- Le funding et les bougies de notre corpus sont confirmés par une source indépendante.

## Au coffre (23/11) — `COFFRE_DONNEES_EXTERNES.cmd`
Décision de l'opérateur : « si ces données sont viables, fiables, backtestables et replayables, elles sont
autorisées à aller dans le coffre-fort » ; « il faudra que ces données soient utiles au labo ».
`tools/coffre_donnees_externes.py` (`--plan` : lecture seule, ni réseau ni écriture) :
1. récolte incrémentale (empreintes vérifiées) : Ironflow + 1ers du mois Tardis (BTC, ETH, HYPE) ;
2. **recoupement dex par dex** contre nos données, seuils fixés AVANT la mesure (`SEUILS` dans l'outil) ; un dex
   sans paire commune avec nous (para, hyna, km, cash…) est **refusé**, pas présumé bon ;
3. versement **seulement là où Alina n'a rien** : heure de funding ou bougie absente, OI et trades avant notre
   première observation ; pré-certification ligne par ligne, fichier refusé au-delà de 0,1 % de quarantaine ;
4. scellement par le certificateur habituel ; l'index porte `provenance: EXTERNAL_HISTORICAL` et `source_tag`
   `EXTERNE_*` ; chaque ligne `data_origin: EXTERNAL_HISTORICAL`, `causal_observation: false`.

Ce que le labo en fait : le funding comble des heures du portage (Alina prioritaire à la même heure) ;
bougies, OI, liquidations, trades = signaux de contexte comptés **à part** (`signaux_externes_par_famille`).
**Jamais au coffre** : le carnet Tardis (aucune heure de réception par Alina ; on ne la fabrique pas).

**⚠ L'open interest d'Ironflow est daté du DÉBUT de l'heure mais mesuré à sa FIN.** Octobre, 126 539 paires :
mark à 1,89 bps (médiane) de la clôture de notre bougie, à 46 bps de son ouverture. Lu tel quel, il donne le
marché **une heure à l'avance**. Le recoupement l'a refusé ; il entre daté t + 1 h (sens prudent : en retard,
jamais en avance), l'étiquette d'origine dans `ironflow_horodatage_ms`. Aucun essai goal2 ne l'avait utilisé.

**Trouvé en chemin : 444 073 règlements de funding d'Alina en double au coffre** (dédoublonnage par ruban, pas
entre sources ; 34 037 depuis le 01/04). `taux_du_coffre` les additionnait ; il n'en garde plus qu'un par heure.

## Recherche du 23/11 (Exa, Tavily, TinyFish, WebSearch) — nouvelles sources GRATUITES
Licence, verrouillage et taille lus sur l'API publique de Hugging Face (`/api/datasets/<repo>`), pas sur la
seule fiche. Aucune n'est téléchargée à ce stade ; aucune n'a d'heure de réception par Alina.

| Source | Contenu utile au labo | Période | Licence / accès | Wallets | Taille | Usage labo visé |
|---|---|---|---|---|---|---|
| **Hydromancer Reservoir** (HF) | fills de tous les comptes ; carnets **20 niveaux à la minute** ; liquidations ; valeurs de compte (mensuelles) ; ADL ; bougies 1 min | fills 18/11/2025 → 17/11/2026 ; carnets 15/12/2025 → 17/11/2026 ; liquidations depuis 28/07/2025 | **CC BY 4.0**, HF public non verrouillé (la même archive sur S3 = payante, requester-pays) | oui | 245 Go (fills ~199, carnets ~23) | **carnet à la SORTIE** des épisodes (la cause racine du verdict manquant) ; historique complet des fills des leaders |
| **ProbioticFarmer copytrading** (HF) | fills depuis la genèse du DEX ; **valeur de compte QUOTIDIENNE** par wallet ; carnets 1 min (150+ perps) ; liquidations ; contextes d'actifs horaires (3,4 ans) | 391 jours de valeurs de compte depuis le 29/07/2025 ; 443 partitions de fills | **MIT**, HF public, sans frais de transfert | oui | 268 Go (60 096 fichiers) | courbe d'équité quotidienne des leaders et des vaults ; fills des leaders au-delà des 10 000 de l'API |
| Chainticks perp-data (HF) | funding, trades `hyperliquid_chain` | depuis le 20/05/2023, mis à jour le 12/08/2026 | CC BY 4.0 | à vérifier | 91 Go | recoupement ; à évaluer |
| Hypedexer | export CSV des fills de n'importe quelle adresse | depuis le 01/01/2024 | portail gratuit **sans compte** ; API = compte (5 000 crédits/mois) | oui | à la demande | contrôle croisé des fills de nos leaders |
| CryptoHFTData | carnets L2 (instantanés + deltas), fichiers horaires Parquet | depuis le 29/09/2025 | fichiers à l'unité sans clé, limités ; API = compte gratuit | non | à la demande | carnet à la sortie, en appoint |
| 0xArchive | carnets L2/L4, trades | **30 derniers jours** seulement en gratuit | compte gratuit, redistribution interdite | ? | — | écarté (fenêtre trop courte) |
| QuantFeatures (HF) | indicateurs dérivés 10 min / 1 h, 6 instruments | 2026 | **licence d'évaluation** (production interdite) | non | 8 Go | écarté (licence) |
| HyperNatt, Bitquery, Dwellir, Allium, CoinAPI | carnets, fills | — | **payants** (échantillons gratuits seulement) | — | — | écartés |

**Hydromancer INTÉGRÉ le 23/11** (`tools/ingerer_hydromancer.py`, manifeste `runtime/history/hydromancer/MANIFESTE.json`) :
746 fichiers sur 746 validés, 23,99 Go, SHA-256 LFS vérifiés, gardés tels que publiés (Parquet ZSTD) — carnets perps
21,1 Go, bougies 1 min 2,0 Go, instantanés de comptes 0,66 Go, liquidations 0,32 Go. Validation par fichier : heures
du jour, carnets croisés (0 sur les premiers jours), carnets à un seul côté comptés et nommés. **Alignement mesuré**
contre NOS carnets (coffre, 8–16/11, 652 paires par décalage) : écart de mid médian **0,47 bps à décalage nul**,
3,3 bps à ±30 s, 9 bps à ±3 min — symétrique : `block_time_ms` est l'heure de la bourse, aucune fuite du futur.
Lecteur du labo : `src/hl_observer/backtesting/carnets_externes_hydromancer.py` (non causal par construction ;
`predicats_de_rejouabilite` le compte NON causal, il ne peut pas devenir SAFE). Fills de tous les comptes (199 Go)
non pris : il faudrait tout télécharger pour garder nos leaders.

Règles avant tout téléchargement : tailles par préfixe via l'API « tree » de HF, estimation de la tranche utile
(nos leaders, nos coins, notre période) ; test d'alignement des horodatages de −3 h à +3 h sur chaque source (l'OI
Ironflow était décalé d'une heure) ; fills : jamais de doublon d'une identité déjà au coffre, jamais causaux ;
carnets 1 min : ils n'entrent pas dans `book_l2` (pas d'heure de réception) — un lecteur du labo doit être décidé
AVANT de les verser, sinon ils dorment dans `familles_non_chargees`. Créer un compte (Hypedexer API, CryptoHFTData,
0xArchive) demande l'accord de l'opérateur.

## Bloqué / à faire
- H18 attend le fichier Ironflow de novembre (début décembre).
- Aucune source temps réel de liquidations réalisées : un filtre fondé sur elles n'est pas applicable en direct.
- Tardis : Hyperliquid confirmé (gratuit le 1er du mois) ; ingestion d'un jour d'exploration à faire, bornée.
- Tardis L2 Hyperliquid = instantanés top-20 puis top-5 (mesuré) : ne pas l'appeler carnet complet.
