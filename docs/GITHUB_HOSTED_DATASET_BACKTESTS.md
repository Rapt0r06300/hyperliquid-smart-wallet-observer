# GitHub-hosted Dataset V2 : collecte, replay et backtests

## Architecture canonique

La source de vérité unique pour Alina Smart Flow est :

`Rapt0r06300/hyperliquid-smart-wallet-observer`

Le même dépôt contient :
- le code des collecteurs ;
- le control plane `IDLE / COLLECT / ANALYZE` ;
- `catalog/DATA_INDEX.json`, les manifests, receipts et registres de qualité ;
- les workflows GitHub Actions ;
- les moteurs de replay/backtest ;
- OOS, forward paper, PnL proof et scoreboard ;
- les lecteurs/materializers SAFE-only.

Les données lourdes sont publiées comme assets immuables de GitHub Releases **dans ce même dépôt**. Aucun nouveau workflow actif ne dépend d'un dépôt dataset séparé. Les anciens dépôts dataset restent uniquement des archives de provenance et ne sont jamais une autorité de phase, une source automatique de collecte ou une source implicite de replay/backtest.

## Collecte GitHub-hosted

La collecte continue canonique est orchestrée par :
- `.github/workflows/create-resumable-campaigns.yml` ;
- `.github/workflows/resumable-campaign-controller.yml` ;
- `.github/workflows/resumable-campaign-worker.yml` ;
- `.github/workflows/campaign-watchdog.yml`.

Les workers sont GitHub-hosted uniquement. Ils ne doivent jamais dépendre du PC utilisateur ni d'un runner self-hosted.

Sources principales, selon disponibilité publique et couverture courante :
- Hyperliquid ;
- Binance ;
- Bybit ;
- OKX ;
- Gate ;
- Bitget ;
- sources additionnelles déjà intégrées lorsqu'elles améliorent la couverture sans créer un collecteur concurrent inutile.

Les campagnes sont bornées et reprenables. Les captures visent un maximum de données **replay-grade** : trades, BBO, L2, séquences, timestamps exchange/réception, clock-sync, métadonnées instrument, profondeur, funding/mark/oracle et données Copy-Vault nécessaires aux modules actifs.

## Qualification

Cycle logique :

`INCOMING -> QUARANTINE -> SAFE | PARTIAL | REJECT`

Un shard ne peut devenir `SAFE` et `replay_compatible=true` que si les preuves nécessaires sont présentes :
- SHA-256 et taille ;
- provenance publique/read-only ;
- intégrité et continuité vérifiables ;
- détection des gaps, régressions, duplications et désynchronisations ;
- horodatage causal suffisant ;
- contraintes de synchronisation ;
- réconciliation historique quand la famille l'exige ;
- asset GitHub distant revalidé contre son digest.

Aucune valeur absente n'est remplacée silencieusement par zéro et aucun gap non prouvé n'est inventé/interpolé pour rendre un replay valide.

## Publication

Le publisher canonique est `tools/publish_dataset_v2_release.py`.

Il publie dans le repo Alina courant :
1. les assets de données ;
2. les manifests construits à partir des octets réellement collectés ;
3. la taille et le SHA-256 ;
4. la vérification des métadonnées distantes ;
5. `RUN_MANIFEST.json` après vérification.

Une Release incomplète ou non vérifiée ne devient jamais une source de validation.

## Replays et backtests

Quand l'utilisateur demandera explicitement le passage en `ANALYZE`, la chaîne reste :

`REPLAY -> BACKTEST -> OOS -> FORWARD_PAPER -> PNL_PROOF -> SCOREBOARD -> DONE`

Le passage en `ANALYZE` fige :
- le `source_collection_epoch` ;
- le `collection_cutoff_at_utc` ;
- le `dataset_selection_id`.

Les lecteurs V2 et `hl_observer.ops.v2_dataset_bridge` chargent `catalog/DATA_INDEX.json` depuis le repo Alina et :
- sélectionnent uniquement les shards `SAFE` et explicitement replay-compatibles ;
- refusent un `release_repository` étranger ;
- téléchargent uniquement les shards contenus dans la fenêtre gelée ;
- revérifient taille et SHA-256 ;
- conservent la provenance de sélection.

Le replay matérialise le workspace SAFE. Les étapes économiques réutilisent ce workspace ; elles ne relancent pas la collecte et ne changent pas la sélection après observation.

## Sécurité

Toute la chaîne reste :
- GitHub-hosted uniquement ;
- paper/read-only ;
- sans clé privée ;
- sans ordre réel ;
- sans endpoint de trading réel ;
- sans self-hosted runner ;
- sans accès ou réveil du PC utilisateur.

Les grosses campagnes doivent rester bornées, résumables et fail-closed afin qu'un échec d'infrastructure ne puisse ni fabriquer une preuve ni invalider silencieusement des données correctes.
