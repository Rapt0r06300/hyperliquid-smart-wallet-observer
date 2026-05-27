# Hyperliquid Smart-Wallet Observer

Hyperliquid Smart-Wallet Observer est un logiciel local de surveillance, d'analyse, de simulation et d'audit autour de Hyperliquid.

Le but du projet est de reproduire la partie techniquement vérifiable des systèmes de type "copy-observer" popularisés par des tutoriels et dépôts open source, tout en gardant une ligne de sécurité très stricte :

- observer d'abord ;
- scorer ensuite ;
- simuler localement ;
- ne jamais exécuter d'ordre réel ;
- ne jamais promettre de gain ;
- ne jamais transformer un score ou une simulation en recommandation d'achat ou de vente.

Le logiciel est conçu pour répondre à une question précise :

> Si un observateur local surveille des wallets Hyperliquid publics, détecte leurs ouvertures, ajouts, réductions et fermetures de position, puis rejoue localement ces comportements avec frais, spread, slippage, latence et filtres de risque, que montre le P&L simulé ?

Ce README est volontairement long et explicatif. Il doit permettre de comprendre l'architecture, les garde-fous, le pipeline de données, le dashboard, les commandes, les tests, et les limites du projet.

---

## 1. Statut actuel

Le projet contient deux zones historiques :

- `src/hl_observer/` : package principal actuel, utilisé par le lanceur, l'UI, les scans, la simulation et les tests récents.
- `hyper_smart_observer/` : base HyperSmart séparée issue des sprints précédents, conservée pour compatibilité et documentation.

La cible opérationnelle locale est aujourd'hui :

```powershell
python -m hl_observer ...
```

Le lanceur principal Windows est :

```text
LANCER_HYPERSMART.cmd
```

Ce lanceur démarre :

- le serveur UI local ;
- le poller read-only ;
- le dashboard sur `http://127.0.0.1:8792/#simulationPanel` ;
- une console visible permettant un arrêt propre.

Important : ce projet reste en simulation locale. Il ne doit pas être utilisé comme bot de trading réel.

---

## 2. Doctrine de sécurité

Doctrine absolue :

- OBSERVE FIRST.
- SCORE SECOND.
- SIMULATE LOCALLY THIRD.
- NEVER EXECUTE.
- NO REAL LOSS PROTOCOL.
- SCORE IS NOT SIGNAL.
- PAPER TRADE IS NOT ORDER.
- HISTORICAL PNL IS NOT FUTURE PROFIT.
- NO GUARANTEED PROFIT.

Interdictions permanentes dans l'état actuel du projet :

- aucun mainnet ;
- aucun ordre réel ;
- aucun endpoint `/exchange` opérationnel ;
- aucune signature ;
- aucune clé privée ;
- aucun formulaire de clé privée ;
- aucun connect wallet ;
- aucun bouton buy ;
- aucun bouton sell ;
- aucun bouton trade ;
- aucun bouton execute ;
- aucun bouton copy trade ;
- aucun testnet executor actif ;
- aucun LLM dans le hot path ;
- aucun score transformé en recommandation ;
- aucune promesse de bénéfice.

Le dashboard peut afficher des données, des refus, des simulations, des positions virtuelles et des rapports. Il ne doit jamais devenir une interface d'exécution.

---

## 3. Vision produit

HyperSmart Observer doit devenir un observateur local Hyperliquid capable de :

1. découvrir des wallets publics intéressants ;
2. construire une shortlist de leaders ;
3. surveiller positions, fills, ordres ouverts et activité publique ;
4. détecter les deltas de position ;
5. classer les wallets par qualité statistique ;
6. refuser les wallets insuffisants ou suspects ;
7. générer des candidats de simulation ;
8. calculer obligatoirement `edge_remaining_bps` ;
9. refuser les signaux non mesurables ;
10. simuler localement les suivis de position ;
11. produire un P&L simulé lisible ;
12. expliquer les refus dans un `no_trade_report` ;
13. afficher le tout dans un dashboard local read-only ;
14. auditer le code et l'archive ;
15. rester strictement local et sans exécution réelle.

Le projet ne cherche pas à prouver qu'un wallet est "magique". Il cherche à mesurer si une hypothèse de suivi de wallets résiste aux coûts et aux contraintes réelles.

---

## 4. Architecture "3 jobs"

Le logiciel suit une architecture inspirée des projets de copy-observer crédibles :

### Job A - Discovery / Leaderboard

Objectif : trouver et filtrer des leaders observables.

Fonctions :

- importer des wallets CSV/JSON/TXT ;
- valider les adresses complètes `0x` + 40 hex ;
- refuser les adresses tronquées avec `...` ;
- scanner des flux publics en lecture seule ;
- construire un pool de wallets candidats ;
- scorer la régularité, l'historique, le drawdown, la concentration du PnL et la copiabilité ;
- écrire une shortlist locale.

Résultats attendus :

- wallets candidats ;
- top wallets ;
- shortlist ;
- refus documentés.

### Job B - Copy loop dry-run

Objectif : observer les leaders, détecter les changements, simuler localement.

Fonctions :

- charger la shortlist ;
- lire `/info` en read-only si `--network-read` est explicitement fourni ;
- récupérer `clearinghouseState`, `userFillsByTime`, `userFills`, `openOrders`, `frontendOpenOrders`, `allMids` ;
- stocker snapshots et deltas ;
- détecter `OPEN_LONG`, `OPEN_SHORT`, `ADD`, `INCREASE`, `REDUCE`, `CLOSE_LONG`, `CLOSE_SHORT`, `UNKNOWN` ;
- calculer `edge_remaining_bps` ;
- refuser ou créer une intention de simulation locale ;
- ne jamais créer d'ordre.

### Job C - Reports / Dashboard

Objectif : rendre le comportement du logiciel visible.

Fonctions :

- afficher P&L simulé ;
- afficher positions virtuelles ;
- afficher deltas leaders ;
- afficher refus `no-trade` ;
- afficher activité des leaders ;
- afficher statut archive/runtime ;
- afficher audit sécurité ;
- exporter rapports locaux.

---

## 5. Modes du logiciel

### 5.1 Observation

Lecture seule des données publiques ou locales :

- REST `/info` ;
- WebSocket read-only ;
- imports manuels ;
- données SQLite ;
- fixtures de tests.

### 5.2 Simulation locale

Mode par défaut visible dans le dashboard.

Caractéristiques :

- capital virtuel de départ : 1000 USDT ;
- aucune monnaie réelle ;
- aucun mock USDC testnet actif ;
- aucun ordre ;
- P&L local ;
- frais, spread, slippage et latence intégrés ;
- positions virtuelles conservées jusqu'à fermeture leader correspondante.

### 5.3 Paper mock USDC

Mode conceptuel de simulation paper.

Il reste local et ne doit pas créer d'ordre. Le terme "mock USDC" désigne l'unité de simulation, pas un solde réel manipulé par le logiciel.

### 5.4 Testnet futur verrouillé

Préparé seulement par documentation et garde-fous.

Non implémenté comme executor actif :

- pas de clé ;
- pas de signature ;
- pas d'appel `/exchange` ;
- pas d'ordre ;
- pas d'activation par défaut.

### 5.5 Mainnet

Impossible dans la version actuelle.

---

## 6. Lanceur principal

Le lanceur unique est :

```text
LANCER_HYPERSMART.cmd
```

Utilisation :

1. double-cliquer sur `LANCER_HYPERSMART.cmd` ;
2. attendre l'ouverture du dashboard ;
3. garder la fenêtre console ouverte ;
4. appuyer sur `R` puis Entrée pour afficher un statut rapide ;
5. fermer proprement avec `Q` puis Entrée.

Le lanceur :

- force `HL_ENV=paper` ;
- désactive mainnet ;
- désactive testnet execution ;
- démarre le serveur local ;
- démarre le poller read-only ;
- ouvre le dashboard ;
- conserve les logs visibles ;
- arrête les processus HyperSmart au moment de quitter.

Le serveur UI tourne par défaut sur :

```text
http://127.0.0.1:8792/#simulationPanel
```

---

## 7. Dashboard

Le dashboard est read-only. Il est pensé comme un écran principal de contrôle de simulation.

Sections principales :

- Simulation ;
- Copy dry-run ;
- Données analysées ;
- Activité ;
- Mode expert.

### 7.1 Onglet Simulation

L'onglet Simulation affiche :

- P&L bot ;
- capital virtuel ;
- P&L latent ;
- P&L réalisé ;
- metagraphe local ;
- décisions récentes ;
- positions virtuelles ;
- refus no-trade ;
- deltas leaders ;
- consensus ;
- wallets suivis.

### 7.2 Metagraphe

Le metagraphe affiche les bougies Heikin-Ashi du P&L simulé.

Il ne doit pas :

- effacer l'historique de session à chaque refresh ;
- fermer une position parce que le P&L est rouge ;
- inventer une entrée si aucun signal n'est exploitable ;
- afficher un profit garanti.

Politique de position :

- une position virtuelle reste ouverte jusqu'à un delta leader `REDUCE` ou `CLOSE` correspondant ;
- une position n'est jamais fermée uniquement parce que le latent est négatif ;
- si la fermeture leader n'existe pas, la position reste suivie ;
- si le prix de marché manque, l'unrealized P&L peut être neutre ou basé sur le dernier prix disponible.

### 7.3 Decision tape

La bande de décisions affiche :

- action simulée ;
- wallet leader ;
- coin ;
- direction ;
- P&L simulé ;
- edge restant ;
- score de risque ;
- raison de refus ou raison de replay local.

Cette bande est essentielle pour comprendre pourquoi le bot agit ou refuse.

---

## 8. Simulation locale persistante

La simulation ne doit pas repartir à 1000 USDT après une coupure temporaire ou un refresh.

État runtime :

```text
data/runtime/ui_simulation_state.json
```

Ce fichier contient uniquement :

- timestamp de début de session ;
- capital virtuel initial ;
- clés de deltas déjà traitées ;
- positions virtuelles ouvertes ;
- ledger des décisions de simulation.

Il ne contient :

- aucune clé privée ;
- aucun secret ;
- aucun ordre ;
- aucune donnée d'exécution.

Le fichier est volontairement dans `data/runtime/`, jamais dans `logs/`.

---

## 9. Détection des deltas

Le moteur cherche à classifier les changements de position.

Règles par taille signée :

- ancien 0, nouveau > 0 : `OPEN_LONG` ;
- ancien 0, nouveau < 0 : `OPEN_SHORT` ;
- ancien > 0, nouveau positif plus grand : `INCREASE` / `ADD` ;
- ancien < 0, nouveau plus négatif : `INCREASE` / `ADD` ;
- ancien > 0, nouveau positif plus petit : `REDUCE` ;
- ancien < 0, nouveau négatif moins grand : `REDUCE` ;
- ancien > 0, nouveau 0 : `CLOSE_LONG` ;
- ancien < 0, nouveau 0 : `CLOSE_SHORT` ;
- flip long vers short : `UNKNOWN` ;
- flip short vers long : `UNKNOWN`.

Règles par fill :

- `dir = Open Long` : open long ou add ;
- `dir = Open Short` : open short ou add ;
- `dir = Close Long` : reduce ou close long ;
- `dir = Close Short` : reduce ou close short ;
- contradiction : `UNKNOWN` ;
- données insuffisantes : `UNKNOWN`.

Un delta `UNKNOWN` ne doit jamais créer d'intention de simulation.

---

## 10. SignalCandidate et edge restant

Un `SignalCandidate` représente une opportunité de simulation locale.

Champs conceptuels :

- `candidate_id` ;
- `leader_wallet` ;
- `coin` ;
- `action_type` ;
- `observed_at` ;
- `leader_fill_time` ;
- `leader_reference_price` ;
- `current_mid` ;
- `spread_bps` ;
- `slippage_bps` ;
- `fee_bps` ;
- `latency_ms` ;
- `liquidity_score` ;
- `leader_score` ;
- `signal_freshness_score` ;
- `copy_degradation_bps` ;
- `edge_remaining_bps` ;
- `paper_mode` ;
- `decision` ;
- `refusal_reasons`.

Formule prudente :

```text
edge_remaining_bps =
  leader_expected_edge_bps
  * leader_consistency_factor
  * signal_freshness_factor
  - delay_cost_bps
  - spread_bps
  - slippage_bps
  - fee_bps
  - liquidity_penalty_bps
  - adverse_selection_penalty_bps
  - crowding_penalty_bps
  - funding_penalty_bps
```

Refus obligatoires :

- edge absent ;
- edge négatif ;
- edge inférieur au seuil ;
- signal trop vieux ;
- liquidité trop faible ;
- copy degradation trop élevée ;
- prix invalide ;
- side inconnu ;
- asset bloqué ;
- maximum de positions atteint.

---

## 11. No-trade report

Le `no_trade_report` explique pourquoi le bot ne simule pas.

Raisons fréquentes :

- `TRUNCATED_ADDRESS_REJECTED` ;
- `INVALID_ADDRESS_REJECTED` ;
- `INSUFFICIENT_HISTORY` ;
- `INSUFFICIENT_CLOSED_PNL` ;
- `PNL_CONCENTRATION_TOO_HIGH` ;
- `ONE_BIG_WIN_RISK` ;
- `LOW_CONSISTENCY` ;
- `MAX_DRAWDOWN_TOO_HIGH` ;
- `STALE_SIGNAL` ;
- `EDGE_UNMEASURABLE` ;
- `EDGE_REMAINING_TOO_LOW` ;
- `SPREAD_TOO_WIDE` ;
- `SLIPPAGE_TOO_HIGH` ;
- `LIQUIDITY_TOO_LOW` ;
- `COPY_DEGRADATION_TOO_HIGH` ;
- `UNKNOWN_DELTA` ;
- `REDUCE_OR_CLOSE_NOT_ENTRY` ;
- `NO_MATCHING_PAPER_POSITION_FOR_CLOSE` ;
- `DUPLICATE_FILL` ;
- `BLOCKED_ASSET` ;
- `MAX_OPEN_PAPER_TRADES_REACHED` ;
- `NETWORK_READ_DISABLED` ;
- `SOURCE_UNAVAILABLE` ;
- `RATE_LIMIT_GUARD`.

Un refus n'est pas un échec caché. C'est une protection mesurée.

---

## 12. Discovery et wallets

Le moteur de découverte utilise plusieurs sources :

- imports manuels ;
- leaderboard ;
- données déjà collectées ;
- WebSocket public trades ;
- explorer public si disponible proprement ;
- fills locaux ;
- wallets déjà stockés.

Validation :

- seules les adresses complètes sont utilisables ;
- les adresses tronquées sont refusées ;
- les wallets sans historique suffisant restent en observation ;
- un seul gros trade ne suffit pas ;
- un PnL concentré est pénalisé ;
- un historique récent mais trop court est pénalisé.

---

## 13. WebSocket read-only

Le WebSocket sert à observer, pas à exécuter.

Contraintes :

- read-only ;
- duration bornée ;
- pas de boucle infinie ;
- shortlist seulement ;
- maximum de users uniques ;
- déduplication ;
- heartbeat ;
- reconnect/backoff ;
- aucune signature ;
- aucun `/exchange`.

Le flux public trades peut alimenter :

- wallets vus ;
- wallets promus ;
- activité récente ;
- contexte de marché.

---

## 14. Backtesting et replay

Le backtest local sert à rejouer des deltas historiques.

Il doit inclure :

- délais de copie ;
- frais ;
- spread ;
- slippage ;
- latence ;
- fills manqués ;
- fills partiels ;
- drawdown ;
- equity curve ;
- refus no-trade rétrospectifs.

Le backtest ne prouve jamais un profit futur.

---

## 15. Paper portfolio local

Le portefeuille virtuel est local.

Il suit :

- positions virtuelles ;
- size ;
- prix moyen ;
- coûts d'entrée ;
- P&L latent ;
- P&L réalisé ;
- coûts totaux ;
- ouvertures ;
- fermetures ;
- refus.

Le capital de simulation par défaut est :

```text
1000 USDT
```

Ce n'est pas un solde réel.

---

## 16. Runtime et archive propre

Règle :

- `logs/` contient des logs texte ;
- `data/` contient la DB et les données runtime ;
- aucune DB active dans `logs/` ;
- aucune archive sale ;
- aucun ZIP/7Z/RAR à la racine du projet.

Bouton archive :

```text
CREER_ARCHIVE_PROPRE.cmd
```

Script :

```text
tools/create_clean_archive.ps1
```

L'archive propre est créée sur le Bureau, pas dans le projet.

Exclusions :

- `.git/` ;
- `data/` ;
- `logs/` ;
- `.venv/` ;
- caches ;
- SQLite ;
- `.env` ;
- archives imbriquées ;
- fichiers temporaires.

---

## 17. Commandes utiles

Initialisation :

```powershell
python -m hl_observer init-db
```

UI :

```powershell
python -m hl_observer ui --host 127.0.0.1 --port 8792
```

Lanceur Windows :

```powershell
.\LANCER_HYPERSMART.cmd
```

Safety audit :

```powershell
python -m hl_observer safety-audit
```

Copy run dry-run :

```powershell
python -m hl_observer copy-run --interval 300 --dry-run
```

Copy run avec lecture réseau explicite :

```powershell
python -m hl_observer copy-run --interval 300 --dry-run --network-read
```

Scan public read-only :

```powershell
python -m hl_observer live-public-scan --network-read --store
```

Archive propre :

```powershell
.\CREER_ARCHIVE_PROPRE.cmd
```

---

## 18. Tests

Tests ciblés récents :

```powershell
python -m pytest -q tests/test_hypersmart_single_launcher.py tests/test_ui_simulation_persistence.py tests/test_ui_copy_dashboard.py tests/test_realtime_magic_score.py
```

Tests UI sécurité :

```powershell
python -m pytest -q tests/test_ui_no_dead_buttons.py tests/test_ui_safe_actions.py
```

Suite complète :

```powershell
python -m pytest -q
```

La suite complète peut être longue car plusieurs tests UI et scans locaux initialisent l'application.

---

## 19. Audit sécurité

La commande principale est :

```powershell
python -m hl_observer safety-audit
```

L'audit vérifie notamment :

- pas de secrets évidents ;
- pas de `.env` commit ;
- pas d'ordre mainnet ;
- pas de source runtime utilisant `/exchange` ;
- présence du verrou `live_executor_disabled` ;
- mainnet désactivé dans les exemples ;
- tests de sécurité présents.

---

## 20. Structure du dépôt

Répertoires principaux :

```text
src/hl_observer/
  analysis/
  autoscan.py
  collection/
  copying/
  explorer/
  following/
  hyperliquid/
  markets/
  risk/
  runtime/
  security/
  signals/
  storage/
  ui/
  wallets/

hyper_smart_observer/
  app/
  audit/
  backtesting/
  copy_mode/
  dashboard/
  hyperliquid_client/
  paper_trading/
  risk_engine/
  scoring/
  storage/

tests/
docs/
tools/
config/
```

---

## 21. Sources de recherche intégrées

Les idées de conception documentées dans le projet proviennent de recherches sur :

- architecture en 3 jobs : leaderboard, copy loop, reporting ;
- copy-observer read-only ;
- WebSocket monitoring ;
- position sizing proportionnel plafonné ;
- filtres de liquidité et slippage ;
- refus no-trade ;
- replay/backtest local ;
- dashboard read-only.

Le projet ne copie pas aveuglément ces systèmes. Il en retient les parties vérifiables et les encadre par sécurité.

---

## 22. Pourquoi le P&L peut rester à zéro

Le P&L reste à zéro si :

- aucun delta frais n'est détecté ;
- les deltas sont trop vieux ;
- l'edge restant est trop faible ;
- la copy degradation est trop forte ;
- le prix est manquant ;
- la liquidité est insuffisante ;
- le bot voit seulement des réductions/fermetures sans position virtuelle correspondante ;
- les positions sont refusées par risk gate.

Ce comportement est volontaire. Le logiciel ne doit pas inventer une position juste pour faire bouger le graphe.

---

## 23. Pourquoi le P&L peut être négatif

Un P&L négatif en simulation n'est pas forcément un bug.

La simulation applique :

- frais ;
- spread ;
- slippage ;
- latence ;
- pénalité de dégradation ;
- taille plafonnée ;
- refus de signaux faibles.

L'objectif du metagraphe est justement de montrer les pertes possibles pour améliorer les règles, pas de maquiller la courbe.

---

## 24. Ce qui a été corrigé récemment

Stabilisation simulation :

- état de session persistant ;
- ledger de décisions persistant ;
- positions virtuelles persistantes ;
- delta keys déjà traitées ;
- graphe basé sur le ledger de session ;
- pas de fermeture automatique en P&L rouge ;
- maintien des positions jusqu'à `REDUCE` ou `CLOSE` leader correspondant.

Stabilisation UI :

- retry API pour panneaux secondaires ;
- conservation du dernier payload simulation ;
- decision tape visible ;
- metagraphe plus stable ;
- console de lancement visible.

Stabilisation launcher :

- un seul lanceur racine ;
- console visible ;
- status rapide avec `R` ;
- arrêt propre avec `Q` ;
- serveur et poller attachés au superviseur.

---

## 25. Limites connues

Le projet reste expérimental.

Limites :

- aucune garantie de profit ;
- dépendance à la qualité des données publiques ;
- difficulté à suivre tous les wallets sans rate limit ;
- risque de signaux trop vieux ;
- slippage réel inconnu ;
- liquidité approximée si carnet insuffisant ;
- reconstruction de positions parfois ambiguë ;
- certains wallets peuvent hedge ailleurs ;
- PnL historique non prédictif ;
- pas d'exécution testnet active ;
- pas d'exécution mainnet.

---

## 26. Prochaine phase recommandée

Priorités techniques :

1. persister aussi des snapshots de metagraphe agrégés par minute ;
2. ajouter un panneau de source health plus visible ;
3. améliorer la détection des closes partiels ;
4. ajouter un mode replay live contrôlé pour déboguer les décisions ;
5. enrichir les filtres de liquidité avec BBO/L2 ;
6. comparer les politiques de hold/exit en backtest ;
7. afficher les paramètres de risk en UI read-only ;
8. renforcer l'archive audit avant release.

Priorité produit :

- rendre la simulation encore plus lisible ;
- expliquer chaque refus ;
- mesurer les coûts ;
- accepter moins de signaux mais mieux documentés ;
- ne jamais forcer un P&L positif artificiel.

---

## 27. Rappel final

HyperSmart Observer n'est pas un bouton magique.

C'est un laboratoire local pour observer Hyperliquid, analyser des wallets publics, rejouer des comportements, mesurer des hypothèses, et refuser tout ce qui n'est pas assez propre.

Le logiciel doit rester :

- read-only côté données ;
- simulation-only côté P&L ;
- safe-by-default côté risque ;
- transparent côté dashboard ;
- strict côté exécution.

Score != signal.

Simulation != ordre.

Historique != profit futur.

P&L vert != garantie.

P&L rouge != bug.
