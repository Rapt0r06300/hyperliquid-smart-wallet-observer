# HYPERSMART — IDÉES EXTERNES : CE QUI ENTRE, CE QUI SORT (2026-07-29)

Règle de tri : une idée n'entre que si son **mécanisme est clair, testable et compatible paper-only**.
Ni les étoiles GitHub, ni un README prometteur, ni un fil X ne valent une preuve.

---

## 1. Idées retenues et effectivement implémentées dans ce run

| # | Idée | Ce qui a été porté | Ce qui a été REFUSÉ | Statut |
|---|---|---|---|---|
| ALPHA-5 | Lead-lag conditionné aux événements | Conditionnement causal (OFI, régime de spread, profondeur, burst de volatilité, 4 horloges pré-enregistrées), embargo, comptage de **tous** les essais | Chercher « Binance mène HL » globalement ; retuner un seuil après lecture | `DISCOVERY_PROBE` max, jamais promu |
| ALPHA-6 | NBBO synthétique (Cryptofeed) | Normalisation multi-venues, mapping versionné, routes buy/sell séparées | La dépendance Cryptofeed elle-même (le schéma maison couvre le besoin) ; tout écart de **mid** traité comme arbitrage | `DONE_VERIFIED` |
| ALPHA-7 | Toxicité / crowding des métaordres (papier HL 2026) | Crowding même sens, imbalance extrême, profondeur reconstruite alors que le prix est parti, markout adverse | Traiter le papier comme une preuve de profit | `SHADOW`, `promotion_possible=false` |
| ALPHA-8 | Sizing proportionnel au leader (repos copy Polymarket) | `min(capacité L2, budget risque, equity × clip(delta/NAV))`, caps coin/direction/cluster, REDUCE proportionnel | Sizing fixe « qui marche bien » ; toute taille dérivée d'un résultat futur | `DONE_VERIFIED` |

---

## 2. Ce que nous n'avons PAS importé, et pourquoi

| Source | Ce qu'on prend | Ce qu'on refuse | Raison |
|---|---|---|---|
| **Hummingbot XEMM** | La machine d'état de la seconde jambe et le hedge après fill | Lancer du market-making réel | Le scope est paper-only ; et la loi mesurée du projet dit MM dans le spread 0/29 |
| **NautilusTrader** | `liquidity consumption` (ne pas surremplir la liquidité affichée), moteur d'événements déterministe | Réécrire HyperSmart dans Nautilus | Coût de migration sans gain d'edge ; on aurait une 3ᵉ architecture |
| **hftbacktest** | Modèles latence / file / fill partiel | Prétendre que la latence d'exécution est « mesurée » | Sans ordre réel, elle reste `ASSUMED` |
| **Freqtrade** | `lookahead-analysis` et `recursive-analysis` → bloc 17 | Ses stratégies | Une stratégie tierce n'a pas de raison d'avoir un edge sur HL |
| **Cryptofeed** | La normalisation et le NBBO directionnel | La dépendance | Schéma maison suffisant (ALPHA-6) |
| **Petits repos « AI arbitrage/copy bot »** | Rien | Tout | Aucun mécanisme testable ; promotion par marketing |
| **Posts X (concentration wallets, alertes TWAP)** | La **question** posée | Toute statistique | Une intuition publique motive une mesure, elle ne la remplace pas |

---

## 3. Idées qui restent SHADOW faute de données

| Idée | Ce qui manque | Producteur en place ? |
|---|---|---|
| ALPHA-5 conditions microstructure sur données réelles | Une tape L2 HL synchronisée assez longue par condition | Oui — `collecter_lab_microstructure`, `collecter_bbo` |
| ALPHA-7 crowding sur métaordres réels | Densité de TWAP simultanés même sens | Oui — `metaorder_shadow_ledger.jsonl` (76 Mo) |
| ALPHA-8 sizing proportionnel | NAV des leaders point-in-time | Partiel — `collecter_vaults` fournit la NAV des vaults, pas des wallets |
| Capacité (`capacite_usd`) dans le rapport économique | Profondeur L2 au moment de chaque épisode | Oui — `collecter_carnet`, mais non joint aux ledgers historiques |

Chacune est **mesurable** : le producteur existe. Ce qui manque est l'exécution d'une campagne, pas du code.

---

## 4. Ce que ce run ne prouve pas

- Aucune de ces idées n'a produit d'edge positif mesuré. Elles ont produit des **instruments de mesure** et
  des **portes de refus**.
- Le seul chiffre économique réel du run est **négatif** (`raw_probe` -5,88 bps/trade).
- Une idée en SHADOW n'est pas une idée qui marche : c'est une idée dont on n'a pas encore le droit de dire
  qu'elle marche.

---

`0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.`
