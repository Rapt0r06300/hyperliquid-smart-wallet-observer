# NOTE V6 — Version renforcée pour Codex

Cette version conserve le contenu précédent et ajoute un supplément V6 en fin de fichier. Le périmètre est strict : **Hyperliquid uniquement**, **mock USDC / testnet uniquement pour l’exécution**, mainnet en lecture seule, aucune validation sans preuve mesurée.

---

# Hyperliquid Smart‑Wallet Observer

## 1. Résumé exécutif

Ce document constitue la feuille de route pour le développement d’un **bot d’observation et d’analyse de portefeuilles Hyperliquid**.  Notre objectif est de comprendre comment des développeurs ont pu associer les modèles Claude (Claude Opus / Claude Code) à la création de bots de trading et, à terme, de mettre en place notre propre prototype.  La plateforme retenue est **Hyperliquid** : son carnet d’ordres on‑chain et la visibilité des positions/fills rendent possible l’analyse des portefeuilles publics.  Ce projet doit rester expérimental : aucune stratégie ne doit être acceptée sans mesure chiffrée, la priorité est la recherche, le test et la gestion du risque.

## 2. Objectif du projet

Construire un logiciel expérimental capable de :

* Observer et analyser les portefeuilles publics Hyperliquid : positions, fills, ordres ouverts et delta de position.
* Identifier les wallets performants, suivre leur activité (ouverture, ajout, réduction et fermeture de position) et calculer des scores (performance, risque, régularité, copiabilité, toxicité).
* Détecter des signaux exploitables (par exemple des clusters de whales ou des déséquilibres de carnet) et les filtrer en fonction de la liquidité, du spread, de l’âge du signal et d’un risk engine strict.
* Simuler ces signaux en **paper trading** et en backtest afin de mesurer leur rentabilité hors frais et slippage, avant toute utilisation en testnet.
* Utiliser **Claude** comme assistant de recherche et de génération de code hors chemin critique (analyse, génération de scripts, backtests), mais jamais pour prendre des décisions de trading en temps réel.
* Intégrer un risk engine pour limiter l’exposition, imposer des stops, surveiller le drawdown et déclencher un kill switch en cas d’anomalie.

## 3. Plateforme retenue : Hyperliquid

Hyperliquid a été choisie car elle met son carnet d’ordres et ses transactions **on‑chain**, ce qui permet de consulter l’état de marché et les positions de chaque portefeuille via des points d’API REST et WebSocket.  La documentation précise que les bots bénéficient d’un flux identique à celui des traders humains : l’ordre book natif et l’état des comptes sont exposés via JSON‑RPC et WebSockets, et les deux couches d’exécution (HyperCore pour le carnet de trading et HyperEVM pour les contrats) fournissent des appels 【737980683913393†screenshot】.  Les développeurs doivent néanmoins prévoir une infrastructure fiable : choisir un nœud RPC, consommer les flux WebSocket et respecter les limites de débit.  Cette transparence est l’une des principales différences avec des exchanges centralisés comme MEXC, où les positions internes ne sont pas publiques.

**Pourquoi pas MEXC ou Polymarket ?**  MEXC ne publie pas les positions internes des comptes ; il est donc impossible de suivre les « gros wallets » de manière fiable.  Polymarket fonctionne sur un réseau différent (paris prédictifs) et n’est pas accessible en France.  Hyperliquid reste la meilleure option pour un observateur de portefeuilles.

## 4. Pourquoi Hyperliquid plutôt que MEXC ou Polymarket

* **Transparence des portefeuilles :** les adresses sont publiques, et l’API permet de récupérer les `userFills`, `openOrders` et `positions` par adresse.
* **Carnet d’ordres on‑chain :** l’état du marché est observable, ce qui facilite la simulation et les backtests.
* **API et WebSocket officielles** qui exposent les données de marché et l’état des portefeuilles.  La documentation insiste sur l’importance de consommer les flux WebSocket en continu et d’envoyer des ordres via RPC 【737980683913393†screenshot】.
* **Testnet et faucet** : Hyperliquid propose un testnet avec des fonds fictifs (mock USDC), permettant de tester nos stratégies en conditions quasi réelles sans risquer de capital.  Un petit dépôt sur le mainnet (5‑10 USDC) est nécessaire pour accéder au faucet.
* **Écosystème de trackers** : des sites comme HyperTracker affichent déjà les statistiques des portefeuilles (PnL total, nombre de trades, régularité, etc.) et des leaderboards.  Ils signalent que 1,6 million de portefeuilles sont suivis et fournissent des API pour récupérer des données nettoyées【673285023975845†L52-L90】.

## 5. État de la recherche sur les bots Claude

Les discussions en ligne autour des « bots Claude » se divisent en deux catégories :

1. **Promotions virales** qui affirment qu’un agent immobilier du Nebraska aurait généré 249 000 $ de profit en un mois grâce à un bot Claude.  Ces publications sont majoritairement marketing : elles promettent un gain visé avec preuves et incitent à acheter un « guide ».  Aucune preuve sérieuse n’a été trouvée pour confirmer ces gains.  Les posts se contentent de montrer des captures d’écran de PnL sans détails sur la logique du bot et sans mention des frais ni du slippage.  Selon le site Whaleportal, copier un whale n’est pas une garantie de profit : les whales peuvent perdre, et leurs positions peuvent être des hedge ou des arbitrages difficiles à reproduire【530999352951990†L18-L31】.
2. **Articles techniques** qui utilisent Claude pour automatiser la recherche et la génération de code.  Ces développeurs se servent de Claude pour : créer des clients API, générer des scripts de collecte de données, analyser les logs, écrire des tests et proposer des améliorations.  Claude n’est **jamais** placé dans le chemin critique de la prise de décision : il reste un assistant hors temps réel.

## 6. Comment Claude est utilisé par les développeurs

* **Architecte logiciel :** Claude aide à structurer le projet en modules (collecte des données, stockage, scoring, stratégies, risk engine, exécution), à définir les interfaces et à rédiger un plan Codex.
* **Générateur de code :** Claude peut écrire des clients API (HTTP et WebSocket), des parseurs JSON, des simulateurs de carnet d’ordres, des scripts d’insertion en base de données ou des dashboards.  Il sert aussi à générer des tests unitaires et des scripts CLI.  Cependant, les ordres réels sont exécutés par du code déterministe.
* **Analyste de données :** Claude peut analyser un jeu de données (liste de portefeuilles, historique de trades), calculer des métriques (PnL, drawdown, Sharpe) et proposer des scores.  Ses suggestions doivent être vérifiées via backtest.
* **Relecture et débogage :** Claude peut lire des logs, signaler des incohérences et suggérer des corrections.
* **Assistant de backtest :** Claude aide à concevoir des simulateurs, à détecter les biais (look‑ahead, survivorship) et à analyser les résultats.  Il ne doit pas choisir de trades en temps réel.

## 7. Ce que Claude peut faire

* Générer du code Python pour interagir avec l’API Hyperliquid (clients, parseurs, WebSocket).
* Structurer le projet en modules clairs et documentés.
* Aider à collecter et nettoyer les données de marché et des portefeuilles.
* Proposer des formules pour calculer des métriques (expectancy, profit factor, Kelly fraction prudente).
* Produire des rapports et des tableaux récapitulatifs.
* Détecter des bugs dans les scripts et suggérer des améliorations.

## 8. Ce que Claude ne doit pas faire

* **Prendre des décisions de trading en temps réel.**  En raison de sa latence et de son caractère non déterministe, Claude n’est pas adapté pour exécuter des ordres en direct.
* **Gérer des clés privées ou des fonds.**  Les clés API doivent être utilisées uniquement pour la lecture ou l’envoi d’ordres via un module séparé et sécurisé.  Claude ne doit jamais avoir accès à une seed phrase ou à des permissions de retrait.
* **Promettre des gains.**  Claude ne peut pas valider une stratégie comme « à très forte probabilité après validation ».  Toute idée doit être testée avec des données et un risk engine.

## 9. Objectif de gains maximisés et validation critique : analyse critique professionnelle

Plusieurs publications virales promettent des profits garantis grâce à des bots de wallet‑following.  Voici quelques exemples :

* **“No loss trading bot” / “100 % win rate trading bot” :** ces messages affirment qu’en suivant les whales, on obtient un profit assuré.  Or, copier un whale ne garantit rien : les whales peuvent réaliser des hedges, des arbitrages complexes ou simplement se tromper.  Les frais, la latence et la liquidité réduisent la rentabilité.
* **“Guaranteed daily profit” / “Infinite money glitch” :** ces promesses ressemblent à des schémas marketing et ne citent jamais de code ni de méthodes.  Les frais d’exécution et l’impact du marché annulent toute « glitch ».
* **“Claude made me rich” :** aucune preuve vérifiable.  Ces posts utilisent le nom de Claude pour attirer l’attention.  Claude est un assistant de code, pas un oracle des marchés.

Conclusion : **toute stratégie de copy trading ou de suivi de whales doit être validée par des mesures chiffrées, en conditions défavorables**.  Tout avantage potentiel doit être validé par un backtest, un paper trading et un testnet, et accompagné d’un risk engine strict.

## 10. Données Hyperliquid exploitables

Hyperliquid expose plusieurs points d’accès :

* **Marchés et prix :** l’API REST permet de récupérer la liste des contrats (BTC‑USDC, ETH‑USDC, etc.), leurs prix, funding rates et open interest.
* **Carnet d’ordres L2** (l2Book) : via WebSocket, on peut obtenir les volumes d’achats et de ventes par niveau de prix pour chaque contrat.
* **Trades publics** : le flux WebSocket `trades` permet de recevoir les transactions exécutées sur chaque marché.
* **État d’un wallet (user state) :** pour une adresse, l’API `info` renvoie les positions ouvertes, l’exposition, l’équité (PNL), les ordres en cours et les fills【673285023975845†L24-L41】.
* **Historique de fills** (`userFills` et `userFillsByTime`) : ces endpoints fournissent l’historique des trades d’une adresse (quantité, direction, prix, timestamp).  Les trades étant publics, on peut reconstituer les entrées et sorties de chaque portefeuille.
* **Ordres ouverts (`openOrders`)** : l’API retourne les ordres en cours d’un portefeuille (prix, quantité, type, expiration).  Cela permet de détecter les intentions futures.
* **Funding et liquidation** : la documentation mentionne des endpoints pour consulter le funding rate et les liquidations en cours, utiles pour évaluer les risques.
* **Testnet et faucet** : un endpoint dédié permet d’obtenir des fonds fictifs (mock USDC) pour tester les stratégies après un petit dépôt sur le mainnet.

## 11. Stratégies étudiées

Nous avons répertorié plusieurs stratégies potentielles.  Pour chacune, nous détaillons le principe, les données nécessaires et les risques.  Certaines sont à garder, d’autres à rejeter ou à explorer.

### 11.1 Wallet‑following filtré

**Principe :** suivre les wallets affichant un PnL élevé et régulier, détecter leurs entrées (achats), sorties (ventes ou réduction), et imiter leurs mouvements avec des tailles réduites.  L’analyse doit distinguer les entrées nettes (augmentation de position) des simples ajustements ou hedges.

**Données :** `userFills`, `userFillsByTime`, `openOrders`, carnet d’ordres, liquidité, spread.

**Risques :** suivre trop tard ; copier un portefeuille qui hedges ; latence ; frais ; slippage ; liquidité insuffisante ; whales manipulatrices.  Cette stratégie est **gardée** mais uniquement après un scoring rigoureux des wallets (voir sections 16 et 17) et un filtrage du spread/slippage.

### 11.2 Copy trading intelligent

**Principe :** copier les trades d’un portefeuille choisi en ajustant la taille et en appliquant un stop‑loss et un take‑profit.  Refuser de copier les signaux trop vieux ou sur des marchés illiquides.  **Gardée** en complément du wallet‑following.

### 11.3 Whale tracking et cluster de whales

**Principe :** surveiller les portefeuilles avec de très grosses positions et détecter quand plusieurs whales ouvrent la même position.  Un cluster de whales indique un possible mouvement significatif.  **À explorer**, car la liquidité et l’impact de ces positions peuvent être difficiles à reproduire.

### 11.4 Order book imbalance et microstructure

**Principe :** détecter un déséquilibre entre la profondeur acheteuse et vendeuse (OBI) et l’utiliser comme signal de momentum court terme.  **À explorer**, car cela nécessite un accès rapide au carnet d’ordres (WebSocket) et des algorithmes de microstructure.

### 11.5 Funding‑rate strategy et arbitrage

**Principe :** exploiter les écarts de funding rate entre le spot et le perp pour réaliser une stratégie neutre.  **À explorer**, car Hyperliquid propose des contrats perpétuels, mais les données de funding et les frais doivent être analysés.

### 11.6 Market making limité

**Principe :** placer des ordres d’achat et de vente à la fois pour capter le spread.  **Rejetée** dans la première version car la gestion de l’inventaire et l’exposition au marché nécessitent une expertise supplémentaire.

### 11.7 Statistical arbitrage et mean reversion

**Principe :** utiliser des modèles statistiques (z‑score, cointegration) pour parier sur le retour à la moyenne entre deux actifs.  **À explorer** dans une phase avancée.

### 11.8 Liquidation tracking

**Principe :** identifier les zones de liquidation potentielles (beaucoup de positions à levier élevé) et parier sur un squeeze.  **À explorer** sous réserve de données suffisantes.

### 11.9 Strategies rejetées

* **Martingale / levier élevé :** le principe d’augmenter la taille après chaque perte est trop risqué.
* **Copie aveugle de n’importe quel wallet :** sans scoring ni filtre, cette approche est vouée à l’échec.
* **Stratégie basée uniquement sur des signaux X/Twitter** : très volatile et non testable.

## 12. Stratégies retenues

* **Wallet‑following filtré** avec scoring des portefeuilles.
* **Copy trading intelligent** avec gestion du risque (stop‑loss et take‑profit partiels).
* **Sortie anticipée / prise de profit partielle** : sortir avant le portefeuille suivi ou fixer un take‑profit pour éviter de rester trop longtemps.
* **Filtres de spread et de liquidité** : n’entrer que si le spread et la profondeur du carnet sont acceptables.
* **Paper trading + backtest + testnet** avant toute exécution réelle.

## 13. Stratégies rejetées

* **Martingale / levier élevé**.
* **Copy trading aveugle** sans scoring ni filtre.
* **Objectif de gains maximisés et validation critique**.
* **Utilisation directe de Claude pour exécuter des ordres en live**.

## 14. Stratégies à explorer

* **Order book imbalance / microstructure**.
* **Funding‑neutral** et arbitrage de funding.
* **Liquidation clusters**.
* **Clustering de whales** (analyse de corrélations entre plusieurs portefeuilles).
* **Statistical arbitrage (pairs trading)**.

## 15. Wallet‑following : méthode complète

1. **Collecte des données** : récupérer la liste des wallets via les leaderboards Hyperliquid et les trackers (HyperTracker), puis récupérer leurs `userFills`, `positions`, `openOrders` et `userFillsByTime`.
2. **Calcul des métriques** : pour chaque wallet, calculer le PnL total/net, le drawdown max, le profit factor, le nombre de trades, la régularité et l’exposition moyenne.
3. **Filtrage** : écarter les wallets dangereux (martingale, drawdown énorme, gain unique, hedge, levier élevé, marchés illiquides).
4. **Classement** : appliquer un scoring (voir sections 17 et 18) et garder les portefeuilles au score le plus élevé.
5. **Observation** : surveiller les entrées et sorties des wallets sélectionnés via `userFills` et `openOrders`.
6. **Détection de signaux** : déclencher un signal lorsqu’un wallet augmente significativement sa position (delta positif), ou diminue (delta négatif).  Vérifier le carnet, le spread, la profondeur et la latence.
7. **Exécution en paper trading** : simuler le trade avec une taille réduite, appliquer un stop‑loss et un take‑profit partiel, puis enregistrer le PnL.
8. **Analyse et ajustement** : utiliser les données du paper trading pour ajuster les filtres (ex. tolérance au spread, taille maximale).
9. **Passage au testnet** : lorsque la stratégie est stable en paper trading (PnL positif, drawdown contrôlé), l’exécuter en testnet.

## 16. Découverte et sélection des wallets à suivre

La sélection des portefeuilles est critique :

* **Sources** : leaderboard Hyperliquid, HyperTracker, CoinGlass, dashboards Hyperdash/HyperStats.
* **Critères principaux** : PnL total et net élevés, régularité (gain sur 7/30/90 jours), drawdown raisonnable, taille moyenne des positions compatible avec le capital, nombre de trades suffisant.
* **Critères d’exclusion** : martingale, average down dangereux, surlevier, drawdown énorme, dépendance à un seul trade, positions illiquides, changements de comportement fréquents, scores de toxicité élevés.
* **Méthode** :
  1. Récupérer un large échantillon de wallets via l’API et les trackers.
  2. Calculer les métriques de performance et de risque pour chaque wallet.
  3. Filtrer les portefeuilles selon les critères d’exclusion.
  4. Classer les portefeuilles restants par score final.
  5. Observer sans copier pendant un certain temps (lecture seule).
  6. Commencer à simuler (paper trading) sur les meilleurs wallets.

## 17. Scoring des wallets

Nous définissons plusieurs scores :

* **Score de performance :** PnL total, PnL net, profit factor, expectancy, Sharpe approximatif, nombre de trades, performance récente.
* **Score de risque :** drawdown max/moyen, pertes consécutives, taille moyenne, exposition, levier estimé, distance de liquidation.
* **Score de régularité :** performance sur 7/30/90 jours, dépendance à un seul trade, distribution des gains.
* **Score de copiabilité :** liquidité des actifs tradés, spread moyen, slippage estimé, taille compatible avec notre capital, fréquence des trades, profondeur du carnet et possibilité de sortie.
* **Score de timing :** rapidité d’entrée et de sortie, temps moyen entre entrée et profit/perte, comportement lors des sorties (sort‑il avant un squeeze ?).
* **Score de toxicité :** présence de martingale, average down dangereux, levier élevé, comportement erratique, drawdown caché, gains trop concentrés, rôle de hedge ou de manipulation.

Le score final est une combinaison pondérée :

```
score_final = 0.22 * score_performance
              + 0.22 * score_risque_inverse
              + 0.18 * score_regularite
              + 0.18 * score_copiabilite
              + 0.10 * score_timing
              - 0.10 * score_toxicite
```

Les portefeuilles dépassant un certain seuil de score final sont sélectionnés pour l’observation et le paper trading.

## 18. Scoring des signaux

Chaque signal (entrée ou sortie d’un wallet) est évalué avant exécution :

* **Fraîcheur** : le signal doit être récent (ex. moins de 1 500 ms).  Un signal trop vieux est rejeté.
* **Taille de position** : vérifier la taille du trade par rapport à la profondeur du carnet.  Une taille trop grande entraîne du slippage.
* **Direction** : long ou short.  Vérifier la cohérence avec la tendance et le funding.
* **Liquidité et spread** : ne pas entrer si le spread est trop large ou si la profondeur est insuffisante.
* **Volatilité récente** : éviter les marchés trop volatils où le slippage est imprévisible.
* **Distance de liquidation** : éviter les trades avec un risque de liquidation immédiate.
* **Nombre de wallets alignés** : un signal est plus crédible s’il est confirmé par plusieurs wallets indépendants.
* **Score du wallet source** : seuls les wallets avec un score de confiance élevé peuvent déclencher un testnet.
* **Contexte de marché** : régime haussier/baissier, funding positif/négatif, présence d’événements macro.

Décisions possibles : `IGNORE`, `OBSERVE`, `PAPER_TRADE`, `TESTNET_ALLOWED`, ou `REJECT` pour divers motifs (trop tardif, illiquide, trop risqué, spread trop large, slippage trop élevé, wallet toxique, régime de marché défavorable).

## 19. Analyse du carnet d’ordres

L’analyse du carnet d’ordres (order book) est cruciale pour évaluer le spread, la liquidité et l’équilibre entre l’offre et la demande.  Le flux WebSocket `l2Book` d’Hyperliquid fournit les volumes d’achats et de ventes par niveau de prix.  Un **imbalance** important (BidVolume − AskVolume) peut indiquer un biais directionnel à très court terme, mais reste bruité.  L’order book est utilisé pour :

* **Évaluer la profondeur** : s’assurer que la taille du trade visé représente un faible pourcentage du volume disponible.
* **Calculer le spread** : trop élevé → signal rejeté.  Les frais et la latence aggravent le coût d’entrée.
* **Détecter des ordres cachés ou du spoofing** : volume anormalement élevé suivi d’une annulation rapide.
* **Définir un prix d’entrée** : on utilise la meilleure offre/demande ou un prix limite légèrement plus prudent.

## 20. Gestion du spread et du slippage

Le **spread** est la différence entre le meilleur prix d’achat et de vente ; le **slippage** est l’écart entre le prix attendu et le prix d’exécution.  Nos filtres :

* **Spread maximum** : par exemple 0,10 % du prix.
* **Slippage maximum estimé** : par exemple 0,15 % de la position.  Si la profondeur du carnet ne permet pas de respecter ce seuil, le trade est rejeté.
* **Taille maximale par trade** : fixer une limite (ex. 5 USDC) pour le paper trading ; augmenter prudemment ensuite.

## 21. Risk engine professionnel

Un **risk engine** garantit que l’exposition reste limitée et que les pertes sont contrôlées.  Exemples de règles :

* Mode `lecture_seule` par défaut ; le mode `live` doit être explicitement activé après les tests.
* Pas de **levier** dans la phase initiale ; on peut envisager du levier faible après validation.
* **Taille maximale par ordre :** 5 USDC en paper trading ; à adapter sur testnet.
* **Perte maximale quotidienne et hebdomadaire :** par ex. 10 USDC/jour et 25 USDC/semaine.
* **Drawdown maximal :** 5 %.
* **Nombre maximal de positions ouvertes :** 2.
* **Spread et slippage maximums :** 0,10 % et 0,15 %.
* **Âge maximal du signal :** 1 500 ms.
* **Profondeur minimale du carnet :** 5 000 USDC (pour éviter les marchés illiquides).
* **Stop‑loss obligatoire** (ex. 0,8 % sous le prix d’entrée) et **take‑profit partiel** (ex. 1,2 %) ; la moitié de la position est sécurisée à 0,6 %.
* **Trailing stop** pour protéger les gains.
* **Kill switch** en cas d’erreur API, de reconnexion WebSocket, de latence excessive (> 1 s) ou d’incohérence dans les ordres.

Un exemple de configuration YAML est fourni pour paramétrer ces règles.  Les clés API utilisées devront être lues à partir d’un fichier `.env` et ne doivent jamais permettre de retirer des fonds.

## 22. Mathématiques essentielles et formules

Nous utiliserons plusieurs mesures statistiques pour évaluer les performances et les risques :

* **Expectancy** : \(E = (WinRate × AverageWin) − (LossRate × AverageLoss)\).  Permet d’estimer la rentabilité moyenne d’une stratégie.
* **Profit Factor (PF)** : \(PF = GrossProfit / GrossLoss\).  Un PF > 1 indique une stratégie théoriquement rentable.
* **Kelly Criterion prudente** : \(f^\* = (b p − q)/b\), où \(b\) est le ratio payoff, \(p\) la probabilité de gain et \(q = 1 − p\).  Nous appliquerons seulement une fraction (10 %–25 %) de la taille Kelly pour limiter le risque.
* **Max Drawdown** : \(MDD = (PeakEquity − TroughEquity)/PeakEquity\).  Permet de mesurer la pire chute de capital.
* **Sharpe approximatif** : \(Sharpe = (MeanReturn − RiskFreeRate) / StdReturn\).  Indique le rapport rendement/volatilité.
* **Order Book Imbalance** : \(OBI = (BidVolume − AskVolume) / (BidVolume + AskVolume)\).  Sert à détecter les pressions à court terme.

Chaque formule sera testée sur nos données de backtest et de paper trading.  Nous vérifierons la validité statistique (par exemple via des simulations Monte Carlo) et ajusterons les paramètres en conséquence.  Aucun résultat ne sera considéré comme définitif sans tests robustes.

## 23. Protocole de backtest professionnel

Un bon backtest doit :

* **Utiliser des données historiques** de prix, carnet et trades, en incluant les périodes de marché variées (haussier, baissier, volatil, calme).
* **Séparer** la période de calibration (train) de la période de validation (test) et inclure un jeu out‑of‑sample.
* **Simuler les frais et le slippage** en fonction du spread et de la profondeur réelle.
* **Prendre en compte la latence** et les retards de WebSocket.
* **Inclure les partial fills** et les rejets d’ordres.
* **Éviter les biais** : survivorship (ne pas sélectionner les meilleurs wallets en regardant la fin de la période), look‑ahead (ne pas utiliser l’information future), data snooping.
* **Utiliser un walk‑forward** : recalibrer les paramètres périodiquement et tester sur la période suivante.
* **Effectuer des simulations Monte Carlo** en réarrangeant l’ordre des trades pour estimer la distribution du drawdown.

Une stratégie est acceptée pour le testnet si elle obtient :

* Un PnL net positif après frais et slippage sur plusieurs périodes.
* Un drawdown maximal raisonnable (ex. < 5 %).
* Un profit factor supérieur à un seuil à définir (ex. > 1,2).
* Une performance pas concentrée sur un seul trade.
* Un ratio gain/perte stable dans différents régimes de marché.

## 24. Paper trading local

Le **paper trading** est la première étape pratique : il simule les entrées, sorties, frais et slippage, sans placer d’ordres réels.  Pour chaque signal :

* Calculer le prix d’entrée en fonction du carnet (L2) et du spread.
* Appliquer la taille maximale prédéfinie et les règles de risk engine.
* Enregistrer le PnL réalisé et non réalisé, le drawdown et la durée du trade.
* Tester différentes variantes (take‑profit partiel, trailing stop, sortie anticipée).
* Conserver des logs détaillés pour analyse (heure, prix, taille, PnL).

Le passage en testnet n’est envisagé que si le paper trading obtient des résultats réguliers et positifs.

## 25. Testnet Hyperliquid

Le testnet d’Hyperliquid permet d’exécuter des ordres avec des **mock USDC**.  Pour y accéder :

1. **Créer une adresse** compatible (Arbitrum One) et déposer un petit montant (6 à 10 USDC) sur le mainnet pour accéder au faucet.
2. **Réclamer des mock USDC** via le faucet testnet.
3. **Configurer les clés API** du testnet dans le fichier `.env` (permissions de trading mais pas de retrait).
4. **Exécuter la stratégie** en conditions réelles (latence, ordre book, fills), tout en respectant le risk engine.

Le testnet sert à valider l’intégration de l’API, la gestion des ordres et la réconciliation entre l’état local et l’état du compte.

## 26. Dépôt minimal pour débloquer le testnet

Selon la documentation Hyperliquid, un dépôt d’au moins **5 USDC** sur le mainnet (réseau Arbitrum One) est requis pour réclamer des mock USDC via le faucet【673285023975845†L24-L41】.  Nous recommandons de déposer **6 à 10 USDC** (avec un petit montant d’ETH pour les frais) afin de garantir la réception des fonds et de garder une marge.  Ce dépôt ne sert pas à trader en réel ; il n’est utilisé que pour débloquer le testnet.

## 27. Architecture logicielle

Le projet sera organisé comme suit :

* **config/** : fichiers de configuration exemple (`settings.example.yaml`, `risk_limits.example.yaml`, `wallets.example.yaml`).
* **src/** : code source principal.
  * **collectors/** : modules pour récupérer les informations via API (info, userFills, userFillsByTime), maintenir la connexion WebSocket (market data, l2Book, userEvents) et stocker les données.
  * **storage/** : base de données (SQLite ou PostgreSQL), modèles, migrations, et classes d’accès.
  * **wallets/** : gestion des listes de portefeuilles, calcul des métriques, découverte de nouveaux wallets, listes blanches/noires.
  * **scoring/** : calcul des scores (performance, risque, régularité, copiabilité, timing, toxicité) et combinaison en score final.
  * **signals/** : détection et scoring des signaux d’entrée/sortie.
  * **strategies/** : implémentations des stratégies (wallet‑following, copy trading, order book filters).  Chaque stratégie doit être testable et désactivable.
  * **risk/** : moteur de risque, modules de position sizing, contrôles de slippage/spread, garde‑fous (stale data, latence, liquidation) et kill switch.
  * **execution/** : exécutants (paper executor, testnet executor, live executor désactivé), routeur d’ordres et réconciliation.
  * **backtest/** : moteur de backtest et modules de Monte Carlo pour tester les stratégies sur des données historiques.
  * **dashboard/** : front‑end pour visualiser les résultats et surveiller les positions (optionnel, plus tard).
  * **alerts/** : notifications Telegram/Discord.
  * **reports/** : génération de rapports quotidiens (PnL, drawdown, performances par portefeuille).
  * **llm/** : politiques d’usage de Claude, templates de prompts, modules pour résumer les rapports.
  * **utils/** : fonctions utilitaires (journalisation, gestion du temps, mathématiques, sécurité).
* **tests/** : tests unitaires et d’intégration pour chaque module.
* **scripts/** : scripts pour lancer l’observateur, le paper trading, le backtest, le testnet et l’audit de sécurité.

## 28. Pipeline complet

1. **Chargement de la configuration** (fichiers YAML).
2. **Validation sécurité** : vérifier que les clés API ont des permissions limitées et qu’aucune seed phrase n’est présente.
3. **Connexion API / WebSocket** en lecture seule pour collecter marchés, carnets, trades et events utilisateurs.
4. **Collecte des données** en continu (marchés, prix, carnets, trades publics, wallets suivis).
5. **Reconstruction des positions** pour chaque wallet (à partir des fills et des ordres ouverts).
6. **Calcul des deltas de position** (augmentation/diminution).
7. **Détection de signaux** d’entrée/sortie via les changements de delta.
8. **Scoring des wallets** (section 17).
9. **Scoring des signaux** (section 18).
10. **Filtres de spread/liquidité/slippage**.
11. **Simulation d’ordres** via le risk engine (taille, stop, TP).
12. **Exécution en paper trading** (phase initiale).
13. **Réconciliation** : vérifier que les ordres simulés correspondent aux fills simulés.
14. **Enregistrement des logs et du PnL**.
15. **Backtest/replay** sur données historiques pour évaluer les stratégies.
16. **Exécution sur testnet** lorsque les critères sont remplis.
17. **Audit régulier** (logs, anomalies, sécurité).
18. **Optimisation** des paramètres (score, filtres, risk engine) en fonction des résultats.

## 29. Schéma de base de données

Nous recommandons d’utiliser une base de données relationnelle (PostgreSQL) pour stocker :

* **wallets** (id, adresse, date de découverte, scores, statut de surveillance).
* **wallet_metrics** (wallet_id, timestamp, pnl_total, pnl_net, drawdown, profit_factor, …).
* **wallet_scores** (wallet_id, timestamp, score_performance, score_risque, score_regularite, score_copiabilite, score_timing, score_toxicite, score_final).
* **markets** (symbole, tick_size, lot_size, funding_rate, open_interest).
* **prices** (market_id, timestamp, prix, funding_rate).
* **orderbook_snapshots** (market_id, timestamp, levels_up_to_n).
* **trades** (market_id, price, size, direction, timestamp).
* **positions** (wallet_id, market_id, size, entry_price, liquidation_price, timestamp).
* **position_deltas** (wallet_id, market_id, delta_size, delta_value, timestamp).
* **signals** (wallet_id, market_id, type, size, price, timestamp, status).
* **signal_scores** (signal_id, freshness, spread, slippage, liquidity, combined_score, decision).
* **paper_orders**, **paper_fills** (simulation des ordres et résultats de paper trading).
* **testnet_orders**, **testnet_fills** (ordres placés en testnet).
* **risk_events** (type d’événement, message, timestamp).
* **strategy_runs** (stratégie, date, résultat, commentaires).
* **backtest_runs** (stratégie, période, performance, drawdown).
* **daily_reports** (date, pnl_total, drawdown, remarques).
* **source_references** (source_id, url, description, fiabilité).

Ce schéma permettra de calculer des métriques, de générer des rapports et de reconstituer les décisions du bot.

## 30. API / WebSocket Hyperliquid

Le bot utilisera principalement :

* **API REST `info`** pour récupérer les marchés, les positions, les fills et les ordres ouverts d’un wallet.
* **API REST `exchange`** pour placer, modifier ou annuler des ordres (testnet et paper simulator uniquement).  Les types d’ordres disponibles incluent Market, Limit, Post‑Only, IOC, GTC et Trigger orders (TP/SL).
* **WebSocket `market`** pour recevoir les mises à jour des carnets d’ordres (`l2Book`), des trades (`trades`) et de l’open interest.
* **WebSocket `user`** pour recevoir les événements propres à un wallet (confirmations d’ordres, fills, positions, liquidation, funding).

Les appels doivent gérer les reconnections, le throttling et la validation des signatures (hmac).  Le bot doit utiliser un système de **schedule cancel** (dead man switch) pour annuler les ordres en cas de coupure réseau.

## 31. Dashboard

À terme, un petit dashboard (par exemple Streamlit) pourra afficher :

* La liste des wallets suivis, leurs scores et leurs positions.
* Les signaux en attente et leur état (paper, testnet).
* Les performances du paper trading (PnL par stratégie, drawdown).
* L’état du risk engine (exposition actuelle, pertes journalières).
* Les journaux d’événements (erreurs API, killswitch).  

Ce dashboard n’est pas indispensable pour la première version du bot.

## 32. Alertes

Des notifications Telegram ou Discord seront envoyées lors des événements suivants :

* Détection d’un signal important (entrée ou sortie) par un wallet de confiance.
* Déclenchement ou clôture d’un trade en paper ou testnet.
* Dépassement d’un seuil de risque (perte journalière, drawdown, slippage).
* Activation du kill switch.

Les messages devront résumer la raison de l’alerte et inclure un lien vers les logs ou le dashboard pour plus de détails.

## 33. Sécurité

La sécurité est primordiale :

* **Aucune seed phrase ou clé privée** ne doit être incluse dans le code ou le README.  Les clés API doivent être stockées dans des variables d’environnement (`.env`) et avoir des permissions minimales (lecture ou trade sans retrait).
* **Pas de retrait via API**.  Les clés doivent être configurées uniquement pour la lecture et, en testnet, pour l’exécution des ordres mock.  Les dépôts et retraits doivent rester manuels.
* **Journalisation et audit** : chaque action (collecte de données, signal, exécution) doit être loguée avec un horodatage.  Un audit régulier des journaux permettra de détecter les anomalies.
* **Kill switch** : en cas d’erreur critique (timeout API, incohérence, latence élevée), tous les ordres en cours doivent être annulés et le système doit passer en mode lecture seule.

## 34. Légalité France/UE à vérifier

Nous devons vérifier les obligations légales en France et dans l’UE pour l’utilisation d’un bot de trading sur des actifs cryptographiques :

* Hyperliquid n’est pas actuellement régulé en France et n’est pas sur la liste blanche de l’AMF.  L’utilisation doit rester personnelle et expérimentale.
* Tout dépôt réel sur Hyperliquid se fait à ses propres risques.  Le testnet permet de limiter ce risque.
* Les gains éventuels doivent être déclarés conformément à la réglementation fiscale française.

## 35. Repos GitHub utiles

* **chainstacklabs/hyperliquid‑trading‑bot** : un exemple de bot sur Hyperliquid qui explique comment configurer un compte testnet, paramétrer des stratégies via YAML, et limiter le levier【775600124067867†L221-L236】.  Le projet utilise `uv` pour gérer l’environnement et met en avant la prudence (stop‑loss, take‑profit, drawdown max).
* **Hyperliquid SDK (GitHub)** : bibliothèques Python/Tsx permettant de se connecter à l’API et au WebSocket.  Utile pour bâtir nos clients et simulateurs.
* **Hypertracker API** : API payante fournissant des données nettoyées sur les portefeuilles et PnL.  À évaluer pour importer rapidement les leaderboards.
* **Autres projets** : on peut consulter des repos de bots de copy trading, de market making et de backtest pour s’inspirer de leur architecture.  Attention à ne pas copier des stratégies non testées.

## 36. Sources classées

| Score | Source | Description |
| ---- | ------ | ----------- |
| 5/5 | Documentation Hyperliquid | Spécifie les endpoints, les contraintes et les flux WebSocket【737980683913393†screenshot】. |
| 4/5 | Article Chainstack | Explique pourquoi l’ordre book on‑chain d’Hyperliquid et ses deux couches d’exécution rendent possible l’automatisation, et insiste sur l’importance des flux WebSocket et d’une bonne infrastructure【737980683913393†screenshot】. |
| 4/5 | Hypertracker | Présente un leader board et des stats sur 1,6 million de wallets ; fournit des API pour récupérer les PnL et les cohortes de smart money【673285023975845†L52-L90】. |
| 3/5 | Repos GitHub de trading bots | Donnent des exemples de code et de configuration, mais sont souvent limités aux scripts de base. |
| 2/5 | Threads X/Twitter | Offrent des idées mais sans vérification ; à utiliser uniquement comme pistes. |
| 1/5 | Posts viraux “Claude a fait 250 000 $” | Pure marketing ; à écarter. |

## 37. Feuille de route Codex

**Phase 0 – Recherche et cadrage** : terminer la collecte d’informations, affiner les critères de sélection des wallets et valider les contraintes légales.  Comprendre les formules mathématiques et la microstructure.  Examiner les sources officielles pour le testnet et le faucet.

**Phase 1 – Initialisation du projet Python** : créer le dépôt avec la structure de dossiers décrite, configurer `pyproject.toml` et installer les dépendances (HTTPX, WebSocket, SQLAlchemy, etc.).

**Phase 2 – Configuration et sécurité** : mettre en place la lecture des fichiers `.env` et des YAML de configuration.  Valider que les clés API n’ont pas de permission de retrait.  Implémenter un `AuditSafety` script qui vérifie que l’exécution live est désactivée.

**Phase 3 – Client Hyperliquid lecture seule** : coder un client HTTP et WebSocket qui récupère les marchés, carnets, trades publics, état des portefeuilles et events utilisateurs.  Implémenter la reconnexion automatique et la gestion des limites.

**Phase 4 – Base de données** : définir les schémas (voir section 29) et implémenter les modules de stockage.  Écrire des migrations.

**Phase 5 – Collecte et profiling des wallets** : développer des scripts pour découvrir les wallets (leaderboards), calculer les métriques et mettre à jour la base de données.

**Phase 6 – Scoring des wallets** : coder les classes de scoring selon les formules définies ; ajouter des tests unitaires pour valider les calculs.

**Phase 7 – Détection et scoring des signaux** : implémenter la logique de détection des deltas de positions et le scoring des signaux.  Ajouter des filtres de spread, slippage et liquidité.

**Phase 8 – Risk engine** : coder le moteur de risque avec les règles mentionnées (mode lecture seule, size max, stops, kill switch, etc.) et le connecter au simulateur.

**Phase 9 – Paper executor** : simuler les ordres en respectant la profondeur du carnet et en appliquant les frais, le spread et le slippage.  Enregistrer les résultats en base.

**Phase 10 – Backtest/replay** : créer un moteur de backtest capable de rejouer l’historique des fills et des carnets.  Intégrer Monte Carlo et walk‑forward.

**Phase 11 – Dashboard et alertes** : développer un petit dashboard et configurer les alertes Telegram/Discord.

**Phase 12 – Testnet executor** : coder l’exécuteur testnet qui envoie les ordres mock via l’API, gère la réconciliation et applique le risk engine.  Tester avec 1 000 mock USDC.

**Phase 13 – Optimisation et audit** : analyser les résultats, ajuster les paramètres, auditer les logs et s’assurer que la conformité et la sécurité sont respectées.

**Phase 14 – Préparation live désactivée** : préparer, mais ne pas activer, un exécuteur live ; il restera désactivé tant que la réglementation et les tests ne seront pas validés.

## 38. Prompt Codex final

*Créer une section séparée dans le README (non visible ici) avec le prompt destiné à Codex.*  Ce prompt demandera à Codex de générer le code en suivant la structure du projet, de respecter les règles de sécurité, de coder les tests, de commencer par la lecture seule et de ne jamais activer le live par défaut.  Le prompt listera également les fichiers à créer et les commandes de test.

## 39. Checklist avant tout argent réel

1. README.md est complet et toutes les sections sont présentes.
2. Les sources et stratégies ont été documentées et classées.
3. Les clés API ont des permissions limitées ; pas de retrait.
4. Le code a été testé (unit tests et intégration) et audité.
5. Le mode live est désactivé et nécessite une activation manuelle.
6. Le paper trading est positif sur une longue période et un grand nombre de trades ; drawdown contrôlé.
7. Le backtest a été réalisé avec des données variées ; profit factor et Sharpe sont acceptables.
8. Le testnet est positif ; aucune erreur critique n’a été détectée ; la réconciliation fonctionne.
9. Le risk engine a été testé (stops, kill switch, latence, slippage, liquidation guard).
10. Les obligations légales ont été vérifiées.

## 40. Zones encore incertaines

* Disponibilité de certaines données (liquidations en temps réel) via l’API Hyperliquid.
* Qualité et coût des API tierces (Hypertracker API) pour récupérer des PnL précis.
* Complexité de l’arbitrage funding‑neutral et de l’order book imbalance.
* Règlementation future sur les bots de trading en France.

## 41. Prochaines étapes

1. Poursuivre la recherche pour valider les formules avancées et collecter davantage de données sur les wallets et leurs stratégies.
2. Élargir la recherche aux forums techniques et aux papers académiques sur la microstructure des marchés et l’analyse du carnet d’ordres.
3. Commencer le développement de la base de données et des clients API.
4. Implémenter le moteur de collecte et le calcul des métriques.
5. Tester les scores de wallets sur un échantillon et ajuster les poids.
6. Développer un simulateur de trading pour paper trading et backtest.


---

# SUPPLÉMENT V5 — Version Codex Ultra Complète, Hyperliquid Mock USDC Only

> Cette section ne remplace pas le contenu précédent : elle le **renforce**.  
> Elle traduit l’objectif “max de gains” en une approche professionnelle : **maximiser l’espérance positive mesurable**, **minimiser les pertes évitables**, **refuser par défaut**, **tester en paper**, puis **exécuter uniquement en testnet mock USDC**.  
> Aucune phrase de ce fichier ne doit être interprétée comme une promesse de profit garanti.

## V5.0 Périmètre final non négociable

Le projet doit désormais être compris ainsi :

```text
Plateforme codée : Hyperliquid uniquement.
Mode d'exécution : mock USDC testnet uniquement.
Mainnet : autorisé en lecture seule uniquement si nécessaire pour consulter des données publiques / débloquer faucet manuellement.
Polymarket : casebook de recherche seulement, aucune intégration de trading.
MEXC : exclu du code, sauf mention historique dans les recherches.
Objectif : construire un système testnet/paper qui maximise l'edge mesurable, pas un bot miracle.
```

### Formulation correcte de l’objectif “max de gains”

À ne jamais écrire comme une vérité :

```text
gain visé avec preuves
perte réelle neutralisée dans le MVP
bot imparable
argent sûr
profit quotidien assuré
```

À écrire et coder à la place :

```text
maximiser l'edge net mesurable ;
réduire drastiquement les pertes évitables ;
refuser les signaux faibles ;
mesurer le coût réel d'exécution ;
chercher une espérance positive après frais, slippage, latence et refus ;
valider longtemps en paper puis testnet mock USDC.
```

Le vrai protocole V5 :

```text
Profitability-Max Protocol =
  Edge brut détecté
- frais estimés
- spread
- slippage
- coût de latence
- pénalité d'incertitude
- pénalité de régime de marché
- pénalité de crowding/copybots
- pénalité d'erreur API/WS
= edge_remaining

Si edge_remaining <= seuil_minimum : REFUS.
```

## V5.1 Ce que les recherches sur le “bot miracle” suggèrent vraiment

Le “bot miracle” Twitter/X semble mélanger plusieurs familles de techniques :

1. **Wallet discovery massif** : scanner énormément de wallets pour trouver quelques profils très performants.
2. **Wallet profiling** : détecter les traders réguliers, ceux qui ont une vraie discipline, pas seulement un gros coup.
3. **Signal freshness** : copier seulement si l’information arrive encore à temps.
4. **Liquidity-aware copy** : ne copier que si le carnet permet d’entrer et surtout de sortir.
5. **Exit engine** : ne pas seulement copier l’entrée ; prévoir sortie partielle, sortie sur réduction du leader, trailing stop, time stop.
6. **No-trade engine** : savoir ne pas trader est une partie centrale de l’edge.
7. **Arbitrage structurel** : très important sur Polymarket, mais non transposable tel quel à Hyperliquid.
8. **Market making / rebates** : possible en théorie, mais hors MVP car plus risqué et plus complexe.
9. **LLM hors hot path** : Claude/Codex aide à coder, analyser, générer des rapports et trouver des patterns, mais ne décide pas des ordres.
10. **Marketing viral** : les captures de PnL et threads X ne sont pas des preuves.

### Traduction en modules Codex

```text
wallet_discovery.py
wallet_profiler.py
wallet_toxicity.py
wallet_cluster.py
position_delta_detector.py
signal_builder.py
signal_scoring.py
edge_remaining.py
copy_degradation.py
exit_engine.py
no_trade_filters.py
risk_engine.py
paper_executor.py
testnet_executor.py
reconciliation_guard.py
```

## V5.2 Architecture mentale du logiciel final

Le logiciel ne doit pas fonctionner comme :

```text
wallet rentable détecté → copie automatique
```

Il doit fonctionner comme :

```text
1. Observer un grand nombre d'adresses en REST/polling.
2. Calculer leurs statistiques historiques.
3. Éliminer les wallets toxiques.
4. Construire une shortlist.
5. Mettre seulement les meilleurs en WebSocket user-specific.
6. Détecter les deltas de position.
7. Construire un signal.
8. Estimer si le signal est encore exploitable.
9. Mesurer le carnet et la liquidité.
10. Estimer frais, spread, slippage, latence, partial fill.
11. Calculer edge_remaining.
12. Passer toutes les gates du risk engine.
13. Simuler en paper.
14. Enregistrer résultats et refus.
15. Tester en testnet mock USDC uniquement si paper convaincant.
```

## V5.3 Contrats de données à donner à Codex

Codex doit créer des modèles Pydantic ou dataclasses explicites. Aucun dictionnaire flou ne doit circuler partout.

### WalletCandidate

```python
class WalletCandidate:
    address: str
    source: str
    first_seen_ms: int
    last_seen_ms: int | None
    tags: list[str]
    notes: str | None
    is_active: bool
    raw_json: dict | None
```

### WalletSnapshot

```python
class WalletSnapshot:
    address: str
    ts_ms: int
    account_value: float | None
    total_notional_position: float | None
    margin_used: float | None
    withdrawable: float | None
    positions_count: int
    raw_json: dict
```

### PositionState

```python
class PositionState:
    wallet: str
    coin: str
    side: str  # LONG | SHORT | FLAT
    size: float
    entry_px: float | None
    mark_px: float | None
    liquidation_px: float | None
    unrealized_pnl: float | None
    leverage: float | None
    ts_ms: int
    raw_json: dict
```

### PositionDelta

```python
class PositionDelta:
    wallet: str
    coin: str
    ts_ms: int
    previous_size: float
    current_size: float
    delta_size: float
    delta_notional: float
    action: str  # OPEN_LONG, INCREASE_LONG, REDUCE_LONG, CLOSE_LONG, FLIP, etc.
    confidence: float
    reason: str
```

### Signal

```python
class Signal:
    id: str
    wallet: str
    coin: str
    direction: str  # LONG | SHORT
    signal_type: str
    source_delta_id: str
    created_ms: int
    observed_ms: int
    age_ms: int
    wallet_score: float
    signal_score: float
    decision: str
    reject_reason: str | None
    raw_context: dict
```

### MarketContext

```python
class MarketContext:
    coin: str
    ts_ms: int
    mid_px: float
    best_bid: float
    best_ask: float
    spread_bps: float
    depth_bid_usdc_10bps: float
    depth_ask_usdc_10bps: float
    estimated_slippage_bps: float
    recent_volatility_bps: float | None
    funding_rate: float | None
    open_interest: float | None
    raw_l2_book: dict
```

### EdgeEstimate

```python
class EdgeEstimate:
    signal_id: str
    expected_move_bps: float
    fees_bps: float
    spread_cost_bps: float
    slippage_bps: float
    latency_penalty_bps: float
    uncertainty_penalty_bps: float
    crowding_penalty_bps: float
    edge_remaining_bps: float
    accepted: bool
    reason: str
```

### PaperTrade

```python
class PaperTrade:
    id: str
    signal_id: str
    coin: str
    side: str
    entry_ts_ms: int
    entry_px_model: float
    entry_px_after_slippage: float
    size_usdc: float
    fees_usdc: float
    status: str  # OPEN | CLOSED | REJECTED | PARTIAL | EXPIRED
    exit_ts_ms: int | None
    exit_px_model: float | None
    exit_px_after_slippage: float | None
    realized_pnl_usdc: float | None
    pnl_after_costs_usdc: float | None
    mfe_bps: float | None
    mae_bps: float | None
```

## V5.4 États du système

Codex doit coder des états explicites, pas des booléens dispersés.

### AppMode

```text
READ_ONLY
SHADOW
PAPER
TESTNET_CHECK
TESTNET_DRY_RUN
TESTNET_ACTIVE_MOCK_ONLY
```

Interdit dans le MVP :

```text
MAINNET_ACTIVE
LIVE_TRADING
REAL_MONEY
```

### CollectorState

```text
STOPPED
BOOTING
SYNCING_REST
SYNCED
WS_CONNECTING
WS_LIVE
WS_RECONNECTING
STALE
DEGRADED
ERROR
```

### SignalLifecycle

```text
DETECTED
ENRICHED_WITH_MARKET_CONTEXT
SCORED
REJECTED
PAPER_ACCEPTED
PAPER_OPENED
PAPER_CLOSED
TESTNET_CANDIDATE
TESTNET_REJECTED
TESTNET_SENT
TESTNET_RECONCILED
```

### KillSwitchState

```text
ARMED
TRIGGERED_API_ERROR
TRIGGERED_WS_RECONNECT
TRIGGERED_LATENCY
TRIGGERED_RECONCILIATION
TRIGGERED_DAILY_LOSS
TRIGGERED_MANUAL
CLEARED_MANUALLY
```

## V5.5 Wallet discovery avancé

Le bot doit découvrir les wallets par couches.

### Sources autorisées dans le MVP

1. Liste manuelle dans `config/wallets.example.yaml`.
2. Import CSV local.
3. Adresses collectées depuis des sources externes copiées manuellement.
4. APIs officielles Hyperliquid si disponibles.
5. Trackers externes uniquement comme amorce manuelle, pas comme vérité.

### Source of truth

```text
La source de vérité pour scorer un wallet = données récupérées/rejouées via Hyperliquid.
Un tracker externe peut proposer une adresse, mais ne doit pas décider du score final.
```

### Pipeline de découverte

```text
candidate_pool
→ basic_validity_check(address format)
→ rest_snapshot_check
→ recent_activity_check
→ minimum_history_check
→ minimum_trades_check
→ risk/toxicity prefilter
→ wallet_score
→ shortlist
→ premium_ws_candidate
```

### Critères minimums initiaux recommandés

```yaml
wallet_discovery:
  min_trades_7d: 10
  min_trades_30d: 30
  min_active_days_30d: 5
  min_wallet_score_for_shortlist: 70
  max_toxicity_score: 35
  min_copyability_score: 65
  reject_if_single_trade_pnl_concentration_gt_pct: 60
  reject_if_max_drawdown_gt_pct: 35
  reject_if_avg_market_depth_too_low: true
```

## V5.6 Wallet scoring V5 — plus intelligent

Le scoring doit éviter de confondre **chance** et **skill**.

### Score final V5

```text
wallet_score_v5 =
  0.14 * net_performance_score
+ 0.12 * profit_factor_score
+ 0.10 * drawdown_inverse_score
+ 0.10 * consistency_score
+ 0.09 * copyability_score
+ 0.09 * timing_score
+ 0.08 * liquidity_score
+ 0.08 * exit_quality_score
+ 0.07 * regime_robustness_score
+ 0.06 * sample_confidence_score
+ 0.05 * recent_momentum_score
- 0.08 * toxicity_score
```

### Sample confidence

Un wallet avec 5 trades gagnants ne doit pas battre un wallet avec 400 trades propres. Ajouter :

```text
sample_confidence = min(1, log(1 + trades_count) / log(1 + target_trade_count))
adjusted_score = raw_score * sample_confidence
```

### Wilson / Bayesian shrinkage

Pour éviter les faux winrates :

```text
winrate_adjusted = shrink(winrate_observed, prior=0.50, strength=20)
```

Codex peut implémenter simple :

```python
adjusted_winrate = (wins + prior * strength) / (trades + strength)
```

### Concentration penalty

```text
pnl_concentration = largest_trade_profit / total_profit
if pnl_concentration > 0.50: strong penalty
```

### Martingale / averaging down detection

Détecter :

```text
position increases while unrealized PnL < 0
position increases repeatedly against price movement
average entry worsens repeatedly
position size grows after each adverse move
```

Pénaliser fortement :

```text
martingale_penalty = count_bad_adds / total_adds
```

## V5.7 Signal scoring V5 — copier moins, copier mieux

Un signal n’est exploitable que si l’edge reste présent au moment où nous pouvons agir.

### Signal score V5

```text
signal_score_v5 =
  0.16 * wallet_score
+ 0.14 * freshness_score
+ 0.12 * delta_quality_score
+ 0.11 * liquidity_score
+ 0.10 * spread_score
+ 0.10 * slippage_score
+ 0.08 * orderbook_confirmation_score
+ 0.07 * cluster_confirmation_score
+ 0.06 * regime_score
+ 0.06 * exit_feasibility_score
+ 0.05 * edge_remaining_score
- 0.10 * crowding_risk_score
```

### Freshness score

```text
freshness_score = max(0, 1 - (signal_age_ms / max_signal_age_ms))
```

Si `signal_age_ms > max_signal_age_ms`, décision immédiate :

```text
REJECT_TOO_LATE
```

### Delta quality

Un bon delta est :

```text
clair
significatif
pas déjà entièrement pricé
pas juste une poussière d'ordre
pas un flip incohérent
pas un ajout toxique dans drawdown
```

### Crowding risk

Le bot doit estimer que d’autres copybots peuvent suivre le même wallet. Indices :

```text
wallet très populaire
mouvement de prix immédiat après son fill
spread qui s'élargit après le signal
carnet qui se vide vite
augmentation anormale du volume après le signal
```

Si crowding élevé : réduire taille ou refuser.

## V5.8 Market microstructure filters

Le bot doit intégrer le carnet avant tout paper/testnet.

### Métriques de carnet

```text
best_bid
best_ask
mid
spread_bps
bid_depth_5bps
ask_depth_5bps
bid_depth_10bps
ask_depth_10bps
bid_depth_25bps
ask_depth_25bps
orderbook_imbalance
expected_fill_price
estimated_slippage_bps
```

### Formule OBI

```text
OBI = (bid_volume - ask_volume) / (bid_volume + ask_volume)
```

Utilisation : filtre, jamais signal autonome dans le MVP.

### Slippage model simple

Pour un ordre d’achat simulé :

```text
parcourir ask levels jusqu'à remplir size_usdc
avg_fill = sum(price_i * size_i) / sum(size_i)
slippage_bps = (avg_fill - mid) / mid * 10000
```

Pour un ordre de vente : parcourir bid levels.

### Refus microstructure

```text
if spread_bps > max_spread_bps: REJECT_SPREAD_TOO_WIDE
if estimated_slippage_bps > max_slippage_bps: REJECT_SLIPPAGE_TOO_HIGH
if depth_10bps < min_depth_usdc: REJECT_TOO_ILLIQUID
if book_age_ms > max_book_age_ms: REJECT_STALE_BOOK
```

## V5.9 Exit engine — ce qui manque souvent aux copybots

Les copybots perdent souvent parce qu’ils copient l’entrée mais ratent la sortie.

Codex doit créer un `exit_engine.py` avec plusieurs règles désactivables/configurables.

### Règles de sortie paper/testnet

```text
EXIT_LEADER_REDUCED
EXIT_LEADER_CLOSED
EXIT_LEADER_FLIPPED
EXIT_TAKE_PROFIT_PARTIAL
EXIT_TRAILING_STOP
EXIT_TIME_STOP
EXIT_MAX_MAE
EXIT_EDGE_DECAY
EXIT_MARKET_REGIME_CHANGED
EXIT_KILL_SWITCH
```

### Exemple config

```yaml
exit_engine:
  exit_if_leader_reduces_pct: 40
  exit_if_leader_closes: true
  exit_if_leader_flips: true
  partial_take_profit:
    enabled: true
    first_tp_bps: 60
    first_tp_size_pct: 50
  trailing_stop:
    enabled: true
    activation_bps: 80
    trail_bps: 35
  time_stop:
    enabled: true
    max_holding_seconds: 1800
  max_mae_bps: 80
```

## V5.10 No-trade analytics

Un bot qui maximise le gain ne doit pas maximiser le nombre de trades. Il doit maximiser :

```text
qualité des trades acceptés + qualité des refus.
```

Chaque signal refusé doit être rejoué en paper fantôme :

```text
rejected_signal_shadow_outcome
```

Objectif : mesurer si les refus étaient intelligents.

Métriques :

```text
rejected_would_have_won
rejected_would_have_lost
false_reject_rate
good_reject_rate
bad_accept_rate
no_trade_precision
```

Si beaucoup de refus auraient gagné : les seuils sont peut-être trop stricts.  
Si beaucoup d’acceptations perdent : les seuils sont trop laxistes.

## V5.11 Backtest réaliste V5

Le backtest doit simuler le monde imparfait, pas le monde idéal.

À simuler :

```text
fee_model
spread_model
slippage_model
latency_model
partial_fill_model
non_fill_model
reject_model
stale_signal_model
book_depth_model
ws_reconnect_gap
rate_limit_delay
```

### Walk-forward

```text
train window → tune thresholds
validation window → choose config
out-of-sample window → final score
roll forward
```

### Monte Carlo

Randomiser :

```text
ordre des trades
slippage
latence
partial fills
signaux manqués
```

### Critères d’échec automatique

```text
profit_factor < 1.2
max_drawdown > seuil
edge_remaining_median <= 0
PnL concentré sur moins de 3 trades
performance négative après slippage stress x2
performance négative si 20% signaux manqués
bad_accept_rate élevé
```

## V5.12 Testnet mock USDC execution — ultra verrouillé

L’exécution testnet doit être conçue comme un laboratoire.

### Conditions de démarrage testnet

```text
HL_ENV=testnet
HL_ENABLE_TESTNET_EXECUTION=true
HL_TESTNET_PRIVATE_KEY present
HL_ENABLE_MAINNET_EXECUTION=false
--confirm-testnet-only présent
--max-mock-usdc défini
safety-audit OK
paper metrics OK
kill switch ARMED
scheduleCancel ready
```

### Jamais automatique

Même en testnet :

```text
pas d'ordre automatique sans signal loggé
pas de boucle infinie qui place des ordres
pas de levier > 1 au début
pas de market order au début sauf test explicite
préférence limit IOC ou ALO selon contexte
reduceOnly obligatoire pour les sorties
cloid obligatoire pour idempotence
```

### CLoid / idempotency

Chaque ordre testnet doit avoir un client order id :

```text
cloid = hash(run_id + signal_id + side + coin + attempt_index)
```

Le duplicate guard refuse tout ordre avec le même `signal_id + side + coin` si déjà actif.

### scheduleCancel

Codex doit implémenter ou prévoir :

```text
schedule_cancel_arm(seconds=30)
schedule_cancel_clear()
```

But : annuler tous les ordres ouverts si le bot ne renouvelle pas le heartbeat d’exécution.

## V5.13 Stratégies Hyperliquid à implémenter en priorité

### 1. Filtered leader delta copy

```text
leader delta détecté
→ score wallet OK
→ signal frais
→ book OK
→ edge_remaining OK
→ paper trade
```

Décision : MVP.

### 2. Leader reduce/close exit

```text
si leader réduit fortement ou ferme
→ sortir partiellement ou totalement en paper/testnet
```

Décision : MVP.

### 3. Delayed copy after pullback

Au lieu de copier immédiatement après un fill visible, attendre un micro-pullback si le prix a déjà bougé.

```text
if price_moved_too_much_after_signal:
    wait_for_pullback_or_reject
```

Décision : exploration V1/V2.

### 4. Multi-wallet consensus

```text
plusieurs wallets forts alignés sur même coin/direction dans courte fenêtre
→ cluster_score augmente
```

Décision : exploration, pas nécessaire pour première passe Codex.

### 5. Toxic wallet inverse

Suivre les wallets qui perdent pour faire l’inverse est dangereux, car les frais et le timing peuvent détruire l’edge.

Décision : rejet MVP, recherche plus tard.

### 6. Market making

Plus complexe : inventaire, adverse selection, quote management.

Décision : hors MVP.

## V5.14 Critères de réussite “max gains” sans promesse mensongère

Le projet sera considéré performant en testnet/paper si :

```text
edge_remaining_median > 0
profit_factor_net > 1.2 en paper réaliste
max_drawdown sous seuil
bad_accept_rate faible
no_trade_precision élevée
copy_degradation contrôlée
PnL non concentré sur un seul wallet
PnL non concentré sur un seul trade
résiste à slippage x2
résiste à latency +500ms
résiste à 20% signaux manqués
aucune erreur de reconciliation
aucun ordre dupliqué
aucun secret dans logs
```

## V5.15 Priorité de codage Codex révisée

Ne pas demander à Codex de tout coder d’un coup en mode désordonné.  
Mais le README/AGENTS doivent lui permettre de le faire par phases cohérentes.

### Sprint Codex 1 — socle sûr

```text
structure projet
configs
Pydantic settings
database SQLite
logging
CLI doctor/init-db/safety-audit
tests sécurité mainnet interdit
```

### Sprint Codex 2 — collecte lecture seule

```text
REST info client
allMids/l2Book/clearinghouseState/openOrders/userFills/userFillsByTime/orderStatus
pagination
raw_json
repositories
collect-once
```

### Sprint Codex 3 — wallet intelligence

```text
wallet snapshots
position states
position deltas
wallet metrics
wallet scoring
wallet toxicity
```

### Sprint Codex 4 — signals + risk

```text
signal builder
market context
signal scoring
edge remaining
risk gates
rejected_signals
```

### Sprint Codex 5 — paper trading + metrics

```text
paper executor
fill simulator
exit engine
MFE/MAE
copy degradation
no trade analytics
reports
```

### Sprint Codex 6 — WebSocket + shortlist

```text
market ws
user ws shortlist max 10
reconnect/resync
stale guard
```

### Sprint Codex 7 — testnet mock USDC locked

```text
testnet-check
testnet executor disabled by default
manual unlock
cloid
reduceOnly exits
scheduleCancel
reconciliation
```

## V5.16 Prompt Codex final V5

```text
Tu es Codex en mode ingénieur logiciel senior Python, architecte trading-system, quant researcher et auditeur sécurité.

Lis intégralement README.md et AGENTS.md avant toute modification.

Périmètre absolu : Hyperliquid uniquement. Exécution uniquement testnet mock USDC. Mainnet autorisé seulement en lecture seule. Aucun Polymarket/MEXC dans le code d'exécution.

Objectif : construire un logiciel local `hyperliquid-smart-wallet-observer` capable d'observer des adresses Hyperliquid, reconstruire positions/fills/open orders, détecter des deltas de position, scorer wallets/signaux, estimer l'edge exécutable, refuser par défaut, simuler en paper trading, puis préparer un testnet executor mock USDC ultra verrouillé.

Ne promets jamais de gain visé avec preuves. Traduis l’objectif de performance en `edge_remaining`, `profit_factor_net`, `copy_degradation`, `no_trade_precision`, `MFE/MAE`, drawdown et robustesse au stress.

Contraintes absolues :
- aucune seed phrase ;
- aucune clé privée mainnet ;
- aucune fonctionnalité de retrait ;
- aucun appel /exchange mainnet ;
- mainnet execution impossible même si une variable est mal configurée ;
- testnet executor désactivé par défaut ;
- LLM hors hot path ;
- risk engine déterministe ;
- chaque ordre testnet doit avoir cloid/idempotence ;
- reduceOnly obligatoire pour sorties ;
- scheduleCancel prévu pour dead man switch ;
- raw JSON stocké pour audit.

Priorité de livraison :
1. structure projet + configs + CLI + DB + sécurité ;
2. collecte REST read-only ;
3. wallet profiler + deltas ;
4. scoring wallets/signaux + edge_remaining ;
5. risk engine + rejected_signals ;
6. paper executor + exit engine + métriques ;
7. WS market + WS shortlist 10 wallets max ;
8. testnet executor mock USDC verrouillé.

À la fin, fournis :
- fichiers créés/modifiés ;
- commandes exécutées ;
- résultats des tests ;
- confirmation mainnet impossible ;
- confirmation testnet désactivé par défaut ;
- risques restants ;
- prochaine phase recommandée.
```

---

# ANNEXE V5 — Source discipline et hiérarchie de preuve

## Niveau 1 — Source de vérité

```text
Données récupérées directement via Hyperliquid API/WS
Logs locaux
Base locale
Résultats paper/testnet
```

## Niveau 2 — Sources officielles

```text
Docs Hyperliquid
SDK officiel Hyperliquid
Docs Claude Code sécurité
Docs MCP sécurité
```

## Niveau 3 — Sources utiles mais non décisives

```text
Trackers Hyperliquid
Repos GitHub de bots
Dashboards tiers
Articles techniques
```

## Niveau 4 — Hypothèses uniquement

```text
Threads X/Twitter
Captures de PnL
Posts viraux
Guides privés DM
Claims de bot miracle
```

Règle : aucune décision de code critique ne doit dépendre d’une source de niveau 4.


---

# SUPPLÉMENT V6 — Reconstruction maximale du “bot miracle” en version Hyperliquid mock USDC uniquement

> Ce supplément est **cumulatif** : il ne remplace pas les sections précédentes. Il ajoute une couche plus opérationnelle pour Codex. Les règles les plus strictes priment. Le projet reste **Hyperliquid uniquement** côté code, avec exécution **testnet/mock USDC uniquement**. Polymarket, MEXC, X/Twitter et les bots viraux restent des **sources de recherche** et des **casebooks**, jamais des cibles d’exécution.

## V6.1 Objectif réel : maximiser l’espérance sans promettre de gain visé avec preuves

L’objectif “max de gains” doit être traduit en termes codables et testables :

```text
maximiser edge_remaining positif
+ minimiser copy_degradation
+ minimiser drawdown
+ maximiser no_trade_precision
+ maximiser la qualité d’exit
+ éviter les trades non copiables
+ éviter les wallets toxiques
+ éviter les phases de marché défavorables
+ exécuter uniquement en mock USDC / testnet pendant le MVP
```

Il est interdit de coder ou d’écrire dans l’interface :

```text
gain visé avec preuves
zéro perte garanti
bot miracle prouvé
stratégie à très forte probabilité après validation
revenu journalier assuré
```

Mais il est obligatoire de coder un système qui fait **tout ce qui est raisonnablement possible** pour empêcher les pertes évitables : refus par défaut, scoring strict, paper trading, testnet, kill switch, simulation de frais, slippage, partial fill, non-fill, dégradation de copie, et journaux complets.

## V6.2 Hypothèse réaliste du “bot miracle” Twitter/X

La reconstruction la plus crédible du bot viral est une combinaison en couches :

```text
1. Discovery massive de wallets publics
2. Nettoyage et normalisation des données
3. Filtrage des wallets chanceux ou toxiques
4. Détection de wallets robustes sur plusieurs fenêtres temporelles
5. Suivi rapide des changements de position
6. Vérification du carnet et de la liquidité
7. Rejet des signaux trop vieux ou déjà consommés
8. Simulation d’entrée au prix réellement disponible
9. Sortie partielle ou anticipée
10. Journalisation du PnL réel après frais et slippage
11. Optimisation prudente des paramètres
12. Boucle de reporting assistée par LLM hors hot path
```

Ce qui donne l’impression de magie n’est pas “Claude clique sur acheter”, mais la combinaison :

```text
données publiques + vitesse + scoring + filtres + refus massifs + microstructure + exécution disciplinée
```

## V6.3 Ce que Codex doit comprendre sur “copier un wallet”

Copier un wallet ne signifie pas refaire exactement le même ordre. Le bot doit d’abord comprendre **ce que signifie l’action du wallet**.

### Types d’événements wallet à reconstruire

```text
WALLET_NEW_POSITION
WALLET_INCREASE_POSITION
WALLET_REDUCE_POSITION
WALLET_CLOSE_POSITION
WALLET_FLIP_POSITION
WALLET_CANCEL_ORDER
WALLET_PLACE_LIMIT_ORDER
WALLET_PLACE_TRIGGER_ORDER
WALLET_TAKE_PROFIT_BEHAVIOR
WALLET_STOP_LOSS_BEHAVIOR
WALLET_ADD_IN_PROFIT
WALLET_ADD_IN_DRAWDOWN
WALLET_AVERAGE_DOWN_PATTERN
WALLET_PANIC_EXIT
WALLET_HEDGE_LIKE_BEHAVIOR
```

### Interprétation attendue

Un delta de position positif n’est pas automatiquement un bon signal. Codex doit coder une couche d’interprétation :

```text
Si wallet augmente une position gagnante avec faible slippage → possible conviction.
Si wallet augmente une position perdante plusieurs fois → possible martingale / averaging down.
Si wallet réduit après MFE élevé → prise de profit propre.
Si wallet ferme après MAE élevé → possible stop tardif.
Si wallet flip rapidement → signal puissant mais risqué.
Si wallet place des limites proches du mid → intention potentielle mais non garantie.
Si wallet a open orders mais pas de fills → ne pas considérer comme trade confirmé.
```

## V6.4 Pipeline V6 de reproduction wallet-following

Codex doit implémenter le pipeline comme une machine à états, pas comme une fonction unique.

```text
RAW_API_EVENT
  ↓ normalize
NORMALIZED_WALLET_EVENT
  ↓ reconstruct
POSITION_STATE_TRANSITION
  ↓ classify
WALLET_ACTION_CLASSIFIED
  ↓ score wallet
WALLET_CONFIDENCE_CONTEXT
  ↓ score signal
SIGNAL_CANDIDATE
  ↓ risk gates
REJECTED_SIGNAL ou PAPER_ORDER_CANDIDATE
  ↓ simulate fill
PAPER_FILL / PAPER_NON_FILL / PAPER_PARTIAL_FILL
  ↓ manage exit
PAPER_POSITION_LIFECYCLE
  ↓ metrics
DAILY_LEARNING_REPORT
```

### États d’un signal

```text
DETECTED
NORMALIZED
WAITING_FOR_MARKET_CONTEXT
SCORING
REJECTED_PRE_RISK
RISK_CHECKING
REJECTED_BY_RISK
PAPER_ORDER_CREATED
PAPER_ORDER_PARTIAL
PAPER_ORDER_FILLED
PAPER_POSITION_OPEN
PAPER_EXIT_PLANNED
PAPER_EXIT_PARTIAL
PAPER_POSITION_CLOSED
TESTNET_CANDIDATE
TESTNET_BLOCKED_BY_DEFAULT
```

Chaque transition doit être stockée dans `signal_lifecycle_events`.

## V6.5 Nouvelle table obligatoire : `signal_lifecycle_events`

Ajouter au schéma DB :

```text
signal_lifecycle_events
- id
- signal_id
- previous_state
- new_state
- reason
- timestamp_ms
- source_event_id
- wallet
- coin
- raw_json
- config_hash
- run_id
```

Objectif : pouvoir reconstruire pourquoi le bot a refusé, simulé ou promu un signal.

## V6.6 Modèle de vérité : ne jamais croire une source unique

Le bot doit distinguer plusieurs niveaux de vérité :

```text
TRUTH_LEVEL_0_X_CLAIM          = post X / marketing / capture non auditée
TRUTH_LEVEL_1_TRACKER          = HyperTracker / Hyperdash / CoinGlass / leaderboard tiers
TRUTH_LEVEL_2_HYPERLIQUID_API  = données officielles REST/WS
TRUTH_LEVEL_3_LOCAL_REPLAY     = données rejouées localement
TRUTH_LEVEL_4_PAPER_EXECUTION  = simulation réaliste avec coûts
TRUTH_LEVEL_5_TESTNET_EXEC     = exécution mock USDC vérifiée
```

Règle : un wallet ne peut jamais passer en candidat testnet si son score repose uniquement sur `TRUTH_LEVEL_0` ou `TRUTH_LEVEL_1`.

## V6.7 Wallet scoring V6 — skill vs chance

Le scoring doit chercher à séparer la compétence de la chance.

### Nouvelles métriques wallet

```text
sample_size_score              # nombre de trades suffisant
pnl_concentration_score         # pénalise 1 seul gros trade
time_consistency_score          # régularité dans le temps
regime_diversity_score          # performance dans plusieurs régimes
trade_reproducibility_score     # trades copiables avec petit capital
exit_discipline_score           # sorties propres, pas seulement entrées
drawdown_recovery_score         # récupère sans martingale ?
loss_cutting_score              # coupe vite les mauvais trades ?
add_behavior_score              # ajoute intelligemment ou average down ?
liquidity_compatibility_score   # marchés assez profonds
latency_sensitivity_score       # edge trop sensible à la vitesse ?
```

### Flags d’exclusion wallet

```text
FLAG_SINGLE_BIG_WIN
FLAG_LOW_SAMPLE_SIZE
FLAG_HIGH_DRAWDOWN
FLAG_MARTINGALE_LIKE
FLAG_AVERAGE_DOWN_IN_LOSS
FLAG_OVERLEVERAGED
FLAG_ILLIQUID_MARKETS
FLAG_TOO_FAST_TO_COPY
FLAG_TOO_BIG_TO_COPY
FLAG_HEDGE_SUSPECTED
FLAG_STYLE_DRIFT
FLAG_RECENT_PERFORMANCE_COLLAPSE
FLAG_PNL_FROM_UNREPRODUCIBLE_TRADES
```

### Score final V6 recommandé

```text
wallet_score_v6 =
  0.14 * net_performance_score
+ 0.12 * sample_size_score
+ 0.12 * risk_inverse_score
+ 0.10 * regularity_score
+ 0.10 * copyability_score
+ 0.09 * exit_discipline_score
+ 0.08 * liquidity_compatibility_score
+ 0.08 * timing_score
+ 0.07 * regime_diversity_score
+ 0.05 * drawdown_recovery_score
+ 0.05 * loss_cutting_score
- 0.10 * toxicity_penalty
- 0.08 * concentration_penalty
- 0.07 * latency_sensitivity_penalty
```

Le score doit être plafonné si un flag critique est présent. Exemple : un wallet `FLAG_MARTINGALE_LIKE` ne peut pas dépasser 60/100 même si son PnL est élevé.

## V6.8 Signal scoring V6 — ne pas copier le passé

Un signal doit être refusé si l’edge est déjà consommé.

### Signaux à refuser automatiquement

```text
REJECT_PRICE_ALREADY_MOVED_TOO_MUCH
REJECT_LEADER_FILL_TOO_OLD
REJECT_NO_ORDERBOOK_DEPTH
REJECT_SPREAD_TOO_WIDE
REJECT_SLIPPAGE_TOO_HIGH
REJECT_WALLET_EDGE_NOT_REPRODUCIBLE
REJECT_MFE_ALREADY_CONSUMED
REJECT_VOLATILITY_SPIKE
REJECT_FUNDING_CONTEXT_BAD
REJECT_OPEN_INTEREST_CAP_RISK
REJECT_ORACLE_DISTANCE_RISK
REJECT_RECENT_WS_RECONNECT
REJECT_DATA_GAP_DETECTED
REJECT_RATE_LIMIT_RISK
REJECT_TESTNET_DISABLED
```

### Formule signal V6

```text
signal_score_v6 =
  0.16 * wallet_score_v6
+ 0.14 * freshness_score
+ 0.12 * orderbook_depth_score
+ 0.10 * spread_score
+ 0.10 * slippage_score
+ 0.09 * delta_quality_score
+ 0.08 * exit_plan_score
+ 0.07 * market_regime_score
+ 0.06 * cluster_confirmation_score
+ 0.05 * edge_remaining_score
+ 0.03 * funding_context_score
- 0.10 * crowding_penalty
- 0.10 * already_moved_penalty
```

## V6.9 `edge_remaining` devient le décideur économique principal

Aucun signal ne doit être simulé si `edge_remaining <= 0`.

```text
edge_remaining = gross_expected_edge
                 - estimated_entry_spread_cost
                 - estimated_exit_spread_cost
                 - estimated_entry_slippage
                 - estimated_exit_slippage
                 - estimated_fees
                 - latency_penalty
                 - partial_fill_penalty
                 - adverse_selection_penalty
                 - uncertainty_penalty
```

### `uncertainty_penalty`

```text
uncertainty_penalty augmente si :
- wallet historique insuffisant
- market regime instable
- API data incomplète
- orderbook mince
- WS reconnect récent
- signal non confirmé
- forte volatilité
- forte sensibilité à la latence
```

## V6.10 Copy degradation : mesurer l’échec réel de copie

La plupart des copy bots meurent parce que le trade copié est moins bon que celui du leader.

```text
copy_degradation_entry = signed_price_diff(our_entry, leader_entry, side)
copy_degradation_exit  = signed_price_diff(leader_exit, our_exit, side)
copy_degradation_total = copy_degradation_entry + copy_degradation_exit + fees + slippage
```

Objectif : si la dégradation moyenne devient trop forte pour un wallet, ce wallet doit être déclassé même s’il reste profitable pour lui-même.

Ajouter `wallet_copy_degradation_score` et `wallet_copyability_decay_7d`.

## V6.11 Exit engine V6

Le “bot miracle” probable gagne surtout parce qu’il sait sortir, pas seulement entrer.

### Sorties possibles

```text
EXIT_LEADER_REDUCED
EXIT_LEADER_CLOSED
EXIT_PARTIAL_TAKE_PROFIT
EXIT_TRAILING_STOP
EXIT_STOP_LOSS
EXIT_TIME_STOP
EXIT_EDGE_DECAY
EXIT_ORDERBOOK_THINNING
EXIT_VOLATILITY_SPIKE
EXIT_CLUSTER_REVERSAL
EXIT_KILL_SWITCH
EXIT_RECONCILIATION_UNCERTAIN
```

### Règle de sortie multi-couches

```text
Si leader réduit fortement → sortie partielle simulée.
Si leader ferme → sortie totale simulée.
Si edge_remaining devient négatif → sortie simulée.
Si orderbook depth chute → sortie prudente.
Si MFE atteint puis recule → trailing stop.
Si MAE dépasse seuil → stop-loss.
Si signal trop vieux sans progression → time stop.
```

## V6.12 Modèle d’exécution paper réaliste

Le paper trading doit être pessimiste, pas optimiste.

### Modèle fill V6

```text
paper_fill_price = mid_price
                 + side_sign * half_spread
                 + side_sign * estimated_slippage
                 + side_sign * latency_cost
```

### Partial fill V6

```text
fillable_size = min(requested_size, available_depth_at_or_better_than_limit * fill_haircut)
partial_fill_ratio = fillable_size / requested_size
```

`fill_haircut` doit être configurable et pessimiste. Exemple : 0.30 à 0.70 selon profondeur/volatilité.

### Non-fill V6

Refuser ou enregistrer `PAPER_NON_FILL` si :

```text
limit price non atteint
spread trop large
book bouge avant simulation
available_depth insuffisante
latency penalty annule l’edge
```

## V6.13 Delayed-copy intelligent

Copier immédiatement n’est pas toujours optimal. Le bot doit tester plusieurs modes en paper :

```text
COPY_IMMEDIATE_PESSIMISTIC
COPY_AFTER_PULLBACK
COPY_ONLY_IF_BOOK_CONFIRMS
COPY_ONLY_IF_SECOND_WALLET_CONFIRMS
COPY_REDUCED_SIZE
COPY_OBSERVE_ONLY
```

Le mode par défaut du MVP est `COPY_OBSERVE_ONLY` puis `PAPER_TRADE`.

## V6.14 Cluster de wallets : confirmation sans foule

Un cluster peut améliorer le signal, mais peut aussi indiquer un crowding dangereux.

### Score cluster

```text
cluster_score =
  + wallets_independent_count
  + average_wallet_score
  + time_alignment_score
  + symbol_liquidity_score
  - crowding_risk
  - same_source_risk
  - copybot_swarm_risk
```

### Flags cluster

```text
CLUSTER_CONFIRMED
CLUSTER_TOO_CROWDED
CLUSTER_SAME_BEHAVIOR_BOTLIKE
CLUSTER_LATE_ENTRY_RISK
CLUSTER_EXIT_REVERSAL
```

## V6.15 Détection martingale / averaging down

Codex doit coder un détecteur de comportement dangereux.

### Patterns suspects

```text
Le wallet ajoute à une position perdante plusieurs fois.
La taille augmente lorsque le MAE augmente.
Le prix moyen se déplace contre la position.
Le wallet réduit rarement les pertes.
Le PnL final positif masque un énorme drawdown.
```

### Métriques

```text
avg_down_count
avg_down_notional_ratio
loss_add_frequency
max_unrealized_drawdown_before_profit
recovery_without_adds_ratio
```

Si un wallet gagne surtout par averaging down, il doit être pénalisé.

## V6.16 Détection de changement de comportement wallet

Un wallet peut devenir mauvais. Le système doit détecter la dérive.

```text
style_drift_score = distance(metrics_recent_7d, metrics_baseline_30d_or_90d)
```

Signaux :

```text
augmentation soudaine du levier
nouveaux actifs illiquides
fréquence de trades anormale
drawdown récent anormal
changement de durée moyenne de position
perte de qualité des exits
copy_degradation en hausse
```

Si `style_drift_score` dépasse le seuil, wallet repasse en `OBSERVE_ONLY`.

## V6.17 Mode “anti-perte maximale” en 14 couches

Pour répondre à l’objectif “tout faire pour ne pas perdre”, le logiciel doit accumuler les protections :

```text
1. Aucun mainnet dans MVP
2. Testnet mock USDC uniquement pour exécution
3. Lecture seule sans clé par défaut
4. Refus par défaut
5. Scoring wallet conservateur
6. Scoring signal conservateur
7. Edge remaining obligatoire > 0
8. Slippage/spread/liquidité obligatoires
9. Paper fill pessimiste
10. Non-fill et partial-fill réalistes
11. Exit engine multi-couches
12. Kill switch / scheduleCancel testnet
13. Reconciliation guard
14. No-trade analytics
```

## V6.18 Données à ajouter au schéma DB

Ajouter :

```text
leader_trade_snapshots
copy_attempts
copy_degradation_by_wallet
edge_remaining_snapshots
paper_position_lifecycle
paper_exit_events
wallet_style_drift
wallet_martingale_flags
cluster_events
cluster_member_events
orderbook_depth_metrics
latency_measurements
non_fill_events
partial_fill_events
execution_quality_reports
parameter_experiments
experiment_results
```

## V6.19 Contrats Pydantic à demander à Codex

Codex doit créer des modèles stricts :

```python
class WalletSnapshot(BaseModel): ...
class WalletMetrics(BaseModel): ...
class WalletScore(BaseModel): ...
class PositionDelta(BaseModel): ...
class SignalCandidate(BaseModel): ...
class SignalScore(BaseModel): ...
class RiskDecision(BaseModel): ...
class PaperOrder(BaseModel): ...
class PaperFill(BaseModel): ...
class PaperPositionLifecycle(BaseModel): ...
class ExecutionQualityReport(BaseModel): ...
class NoTradeDecision(BaseModel): ...
```

Chaque modèle doit inclure : `timestamp_ms`, `source`, `run_id`, `config_hash`, et lorsque pertinent `raw_json`.

## V6.20 Configuration V6 plus complète

Ajouter dans `risk_limits.example.yaml` :

```yaml
profitability:
  require_edge_remaining_positive: true
  min_edge_remaining_bps: 5
  uncertainty_penalty_enabled: true
  max_copy_degradation_bps: 12
  max_wallet_copy_degradation_7d_bps: 20
  min_exit_quality_score: 60

copy_modes:
  default_mode: "observe_only"
  allow_immediate_copy_paper: false
  allow_delayed_copy_paper: true
  allow_pullback_copy_paper: true
  allow_cluster_confirmed_copy_paper: true
  allow_testnet_copy: false

wallet_filters:
  min_sample_trades: 50
  max_pnl_concentration_percent: 35
  max_drawdown_percent: 15
  reject_martingale_like: true
  reject_low_liquidity_wallets: true
  reject_style_drift: true

execution_simulation:
  pessimistic_fill_model: true
  fill_haircut_default: 0.5
  latency_penalty_ms: 300
  simulate_non_fills: true
  simulate_partial_fills: true
  simulate_exit_slippage: true
```

## V6.21 CLI additionnelle V6

Ajouter les commandes :

```bash
python -m hl_observer wallet-audit --wallet 0x...
python -m hl_observer wallet-drift-report
python -m hl_observer cluster-detect
python -m hl_observer signal-replay --signal-id ...
python -m hl_observer experiment-run --config config/experiments/example.yaml
python -m hl_observer edge-report
python -m hl_observer no-trade-report
python -m hl_observer copy-degradation-report
python -m hl_observer exit-quality-report
python -m hl_observer martingale-report
```

## V6.22 Tests supplémentaires obligatoires V6

Ajouter :

```text
test_wallet_flag_single_big_win_caps_score
test_wallet_martingale_caps_score
test_wallet_style_drift_demotes_to_observe
test_signal_rejected_if_edge_remaining_negative
test_signal_rejected_if_price_already_moved
test_signal_rejected_if_mfe_already_consumed
test_signal_rejected_if_orderbook_depth_thins
test_partial_fill_pessimistic_model
test_non_fill_recorded_not_ignored
test_exit_on_leader_reduce
test_exit_on_leader_close
test_trailing_exit_after_mfe_reversal
test_time_stop_closes_stale_paper_position
test_copy_degradation_penalizes_wallet
test_cluster_confirmation_increases_score_but_crowding_penalizes
test_no_trade_decision_becomes_positive_label_if_trade_would_have_lost
test_testnet_order_requires_confirm_testnet_only
test_testnet_order_requires_schedule_cancel_when_enabled
test_cloid_required_for_testnet_order
test_idempotency_prevents_duplicate_testnet_order
```

## V6.23 Critères d’acceptation Codex pour une livraison réussie

Une livraison Codex est refusée si :

```text
- elle crée un chemin mainnet execution
- elle demande une clé privée mainnet
- elle ne crée pas les tests de sécurité
- elle confond Polymarket YES/NO avec Hyperliquid
- elle trade en testnet sans risk decision explicite
- elle ne stocke pas les raisons de refus
- elle calcule un PnL sans frais/slippage
- elle ne gère pas partial fill / non-fill en paper
- elle ne journalise pas les événements critiques
- elle ne fournit pas les commandes de test
```

## V6.24 Plan de travail Codex recommandé pour éviter l’échec

Ne pas demander à Codex de tout coder en une seule passe. Demander des lots sûrs :

```text
Lot 1 — Scaffolding + config + sécurité + tests mainnet forbidden
Lot 2 — REST read-only + stockage raw JSON
Lot 3 — DB + repositories + pagination userFillsByTime
Lot 4 — Wallet snapshots + deltas
Lot 5 — Wallet scoring V6 + flags toxicité
Lot 6 — Signal lifecycle + signal scoring V6
Lot 7 — Risk engine + edge_remaining
Lot 8 — Paper executor pessimiste + fill simulator
Lot 9 — Exit engine + MFE/MAE
Lot 10 — Reports + dashboard minimal
Lot 11 — WS market data
Lot 12 — WS shortlist user-specific limité à 10 wallets
Lot 13 — Testnet executor verrouillé + scheduleCancel + cloid + idempotence
```

## V6.25 Résumé final V6 pour Codex

```text
Tu ne construis pas un bot magique.
Tu construis un système d’observation, scoring, refus, simulation et testnet.
Le profit potentiel vient de la qualité des refus, de la sélection des wallets, de l’exécution pessimiste et de la mesure honnête de l’edge.
Le MVP ne doit jamais exposer d’argent réel.
Tout signal incertain est rejeté.
```



---

# SUPPLÉMENT V7 — Profitability-Max Testnet Protocol, reproduction intelligente des wallets et feuille de route Codex renforcée

> Cette section **ne supprime rien** de ce qui précède. Elle ajoute une couche plus précise pour Codex : comment transformer les recherches sur le “bot miracle” en architecture Hyperliquid testnet/mock USDC, avec un objectif de rendement maximal **mesuré**, mais sans promesse de gain visé avec preuves.
>
> **Périmètre V7 strict :** Hyperliquid uniquement pour le code ; exécution uniquement en testnet/mock USDC ; mainnet uniquement en lecture de données publiques ; Polymarket/X/MEXC uniquement comme casebook de recherche, jamais comme cible de code MVP.

## V7.0 — Décision centrale : maximiser l’espérance testable, pas promettre un gain

Le projet doit viser le **maximum de gains potentiels en testnet** en construisant un système qui :

```text
1. détecte plus tôt les bons signaux ;
2. refuse plus vite les mauvais signaux ;
3. copie seulement si l’edge restant est encore positif ;
4. sort mieux que le simple miroir aveugle ;
5. mesure la performance après coûts simulés ;
6. ne transforme jamais un signal incertain en ordre ;
7. ne met jamais d’argent réel dans le MVP.
```

La version professionnelle du “bot miracle” n’est pas une promesse de profit. C’est un pipeline :

```text
wallet discovery massif
→ validation des adresses
→ backfill fills/orders/positions
→ profil comportemental
→ score skill vs chance
→ détection delta position
→ validation carnet/liquidité/spread/slippage
→ edge_remaining
→ paper execution pessimiste
→ testnet mock USDC
→ rapport de vérité
```

**Règle économique V7 :**

```text
Un signal n’est pas intéressant parce qu’un bon wallet l’a pris.
Un signal est intéressant uniquement si l’edge restant après délai, spread, slippage, frais, liquidité et risque de sortie est positif.
```

Formule de décision centrale :

```text
edge_remaining_bps = expected_move_bps
                   - spread_cost_bps
                   - estimated_slippage_bps
                   - latency_decay_bps
                   - fees_bps
                   - adverse_selection_penalty_bps
                   - exit_cost_bps
                   - uncertainty_penalty_bps
```

Décision :

```text
if edge_remaining_bps <= min_required_edge_bps:
    REJECT_EDGE_TOO_WEAK
else:
    continue_risk_gates
```

## V7.1 — Reconstruction du “bot miracle” en 15 briques réalistes

Les recherches disponibles convergent vers une architecture probable. À intégrer dans le logiciel sous forme de modules, même si chaque module est d’abord simple :

| Brique | Rôle réel | Transposition Hyperliquid |
|---|---|---|
| Wallet discovery | Trouver des adresses candidates | Leaderboards, trackers externes comme amorceurs, listes manuelles, API officielle pour validation |
| Backfill historique | Mesurer le passé du wallet | `userFills`, `userFillsByTime`, `openOrders`, `historicalOrders`, `clearinghouseState` |
| Profil comportemental | Comprendre le style du wallet | fréquence, taille, actifs, holding time, levier estimé, drawdown |
| Skill vs luck | Séparer talent de coup de chance | shrinkage bayésien, Wilson lower bound, concentration PnL |
| Delta de position | Détecter ce qui change vraiment | OPEN/INCREASE/REDUCE/CLOSE/FLIP |
| Signal freshness | Éviter les copies trop tardives | âge en ms, price move depuis entrée leader, decay exponentiel |
| Liquidity-aware copy | Copier seulement si le carnet le permet | `l2Book`, profondeur, spread, slippage simulé |
| Delayed copy | Ne pas courir après le prix | attente pullback contrôlée, confirmation carnet |
| Cluster wallets | Renforcer si plusieurs wallets indépendants alignés | vote pondéré + anti-crowding |
| Toxicity detection | Éviter martingale et surlevier | ajout dans drawdown, tailles croissantes, liquidation proche |
| Exit engine | Sortir mieux qu’un miroir naïf | TP partiel, trailing, leader reduce, max hold, fail-fast |
| Paper executor | Tester sans argent | simulation pessimiste fees/spread/slippage/non-fill |
| Testnet executor | Vérifier l’intégration réelle | mock USDC, `cloid`, reduce-only, scheduleCancel |
| Dashboard vérité | Voir si l’edge existe vraiment | PnL net, copy_degradation, no_trade_precision |
| Audit sécurité | Empêcher les catastrophes | secrets, mainnet disabled, kill switch, tests |

## V7.2 — Funnel de wallets : du scan large à la shortlist premium

Hyperliquid impose de ne pas suivre tout le monde en WebSocket user-specific. Le design doit donc être un **entonnoir** :

```text
CANDIDATE_POOL
  → BACKFILL_OK
  → METRICS_OK
  → WALLET_SCORE_OK
  → TOXICITY_LOW
  → COPYABILITY_OK
  → SHORTLIST_REST
  → PREMIUM_WS_MAX_10
  → PAPER_ELIGIBLE
  → TESTNET_ELIGIBLE
```

### V7.2.1 États d’un wallet

```text
DISCOVERED                # adresse trouvée, pas encore validée
VALIDATED_ADDRESS          # format/adresse OK
BACKFILL_IN_PROGRESS       # récupération historique
BACKFILL_INCOMPLETE        # historique incomplet, observation seulement
OBSERVE_ONLY               # suivi sans signal exploitable
SCORING_READY              # metrics calculables
SHORTLIST_REST             # suivi REST régulier
PREMIUM_WS                 # max 10 wallets user-specific WS/IP
PAPER_CANDIDATE            # signaux autorisés en paper
TESTNET_CANDIDATE          # signaux autorisés en testnet mock USDC
BLACKLISTED                # toxicité, erreur, scam, comportement dangereux
DEGRADED                   # ancien bon wallet qui se dégrade
```

### V7.2.2 Règles de promotion

Un wallet ne peut monter d’un niveau que si :

```text
min_trades >= seuil
min_active_days >= seuil
closed_pnl_sample_ok == true
pnl_concentration_score <= seuil
max_drawdown <= seuil
toxicity_score <= seuil
copyability_score >= seuil
liquidity_score >= seuil
recent_degradation == false
```

Aucun wallet ne doit passer en `PREMIUM_WS` uniquement parce qu’il est viral sur X/Twitter.

## V7.3 — Skill vs chance : méthodes statistiques obligatoires

Le bot doit punir les wallets dont la performance semble venir d’un seul coup.

### V7.3.1 Shrinkage bayésien simple

```text
shrunk_expectancy = (n / (n + k)) * observed_expectancy
                 + (k / (n + k)) * population_expectancy
```

- `n` = nombre de trades du wallet ;
- `k` = force du prior, par exemple 30 à 100 trades ;
- `population_expectancy` = moyenne prudente, souvent 0 ou légèrement négative après coûts.

Utilité : un wallet avec 5 trades gagnants ne doit pas être noté comme un génie.

### V7.3.2 Wilson lower bound pour winrate

Le winrate brut est trompeur. Utiliser une borne basse Wilson pour éviter de sur-noter les petits échantillons.

```text
wilson_lower_bound(win_count, total_count, confidence=0.95)
```

Décision : utiliser la borne basse, pas le winrate brut, dans `performance_score`.

### V7.3.3 Concentration PnL

```text
pnl_concentration = max_trade_profit / total_profit_positive
```

Ou version Herfindahl :

```text
pnl_hhi = sum((trade_profit_i / gross_profit_positive)^2)
```

Pénaliser :

```text
if pnl_concentration > 0.35:
    penalty_one_big_trade
if pnl_hhi > seuil:
    penalty_concentrated_pnl
```

### V7.3.4 Dégradation temporelle

Un wallet rentable mais récemment mauvais doit être dégradé.

```text
recent_vs_long_term_ratio = expectancy_7d / max(expectancy_90d, epsilon)
```

Décision :

```text
if expectancy_7d < 0 and expectancy_30d deteriorates:
    wallet_state = DEGRADED
```

## V7.4 — Détection de toxicité wallet

Un wallet peut gagner beaucoup mais être impossible à copier.

### Signaux de toxicité

```text
martingale_pattern_detected
averaging_down_in_drawdown
position_size_increases_after_loss
liquidation_distance_too_low
high_leverage_estimated
asset_illiquidity
one_big_win_dependency
erratic_flip_frequency
hedge_incomplete_suspicion
copy_degradation_high
exit_quality_bad
```

### Martingale / averaging down

Détection simple :

```text
if position_increases and unrealized_pnl_negative and price_moved_against_position:
    averaging_down_event += 1

if size_after_loss > size_before_loss * martingale_multiplier_threshold:
    martingale_suspect += 1
```

Pénalité :

```text
toxicity_score += averaging_down_event_weight
wallet_score -= toxicity_penalty
```

## V7.5 — Détection du signal : ne pas copier le trade, copier le contexte

Un signal doit être un objet riche, pas juste `wallet bought BTC`.

### V7.5.1 États de signal

```text
DETECTED
ENRICHING
REJECTED
OBSERVE_ONLY
PAPER_ELIGIBLE
PAPER_OPENED
PAPER_CLOSED
TESTNET_ELIGIBLE
TESTNET_OPENED
TESTNET_CLOSED
EXPIRED
INVALIDATED_BY_REDUCE
INVALIDATED_BY_REGIME
```

### V7.5.2 Champs minimaux d’un signal

```yaml
signal:
  id: string
  source_wallet: address
  coin: string
  side: long|short
  action: open|increase|reduce|close|flip
  detected_at_ms: int
  leader_fill_time_ms: int|null
  leader_entry_px: float|null
  current_mid_px: float
  current_best_bid: float
  current_best_ask: float
  spread_bps: float
  estimated_slippage_bps: float
  orderbook_depth_usdc: float
  wallet_score: float
  toxicity_score: float
  delta_notional_usdc: float
  signal_age_ms: int
  price_move_since_leader_bps: float
  edge_remaining_bps: float
  decision: enum
  rejection_reason: string|null
```

### V7.5.3 Décisions V7 supplémentaires

```text
REJECT_EDGE_TOO_WEAK
REJECT_PRICE_ALREADY_MOVED
REJECT_COPY_DEGRADATION_TOO_HIGH
REJECT_EXIT_NOT_CLEAR
REJECT_CROWDING_RISK
REJECT_WALLET_DEGRADED
REJECT_SAMPLE_TOO_SMALL
REJECT_ONE_BIG_WIN_WALLET
REJECT_MARTINGALE_PATTERN
REJECT_UNKNOWN_POSITION_STATE
REJECT_ORDERBOOK_STALE
WAIT_FOR_PULLBACK
WAIT_FOR_CONFIRMATION
```

## V7.6 — Signal decay : le signal perd sa valeur avec le temps

Le bot doit estimer que l’edge se dégrade dès que le wallet leader a déjà bougé le marché.

```text
freshness_score = exp(-signal_age_ms / half_life_ms)
```

Exemple :

```text
half_life_ms = 1500 pour signaux très courts
half_life_ms = 10000 pour swing plus lent
```

Décision :

```text
if signal_age_ms > max_signal_age_ms:
    REJECT_TOO_LATE

if price_move_since_leader_bps > max_chase_bps:
    REJECT_PRICE_ALREADY_MOVED
```

## V7.7 — Liquidity-aware copy : entrer seulement si le carnet accepte notre taille

Le bot doit simuler le prix moyen d’exécution à partir du carnet.

### V7.7.1 Slippage estimé depuis le carnet

Pour un long, consommer les asks jusqu’à `order_size_usdc`. Pour un short, consommer les bids.

```text
vwap_execution_price = sum(level_price * filled_size) / sum(filled_size)
estimated_slippage_bps = abs(vwap_execution_price - mid_price) / mid_price * 10000
```

Refus :

```text
if estimated_slippage_bps > max_estimated_slippage_bps:
    REJECT_SLIPPAGE_TOO_HIGH

if available_depth_usdc < min_orderbook_depth_usdc:
    REJECT_TOO_ILLIQUID
```

### V7.7.2 Copy size adaptatif

```text
base_size = min(max_trade_size_usdc, wallet_delta_notional * copy_ratio)
liquidity_size_cap = available_depth_usdc * max_depth_usage_ratio
score_adjusted_size = base_size * signal_confidence
final_size = min(base_size, liquidity_size_cap, score_adjusted_size)
```

`final_size` doit rester mock/testnet uniquement.

## V7.8 — Delayed-copy intelligent : ne pas courir après le prix

Le bot ne doit pas copier immédiatement si le prix a déjà trop bougé.

Modes :

```text
DIRECT_COPY        # seulement si signal ultra frais et carnet OK
WAIT_PULLBACK      # attendre retour partiel vers prix leader
OBSERVE_ONLY       # surveiller sans entrer
NO_TRADE           # rejet définitif
```

Règle :

```text
if price_move_since_leader_bps <= max_direct_chase_bps:
    mode = DIRECT_COPY
elif price_move_since_leader_bps <= max_pullback_watch_bps:
    mode = WAIT_PULLBACK
else:
    mode = REJECT_PRICE_ALREADY_MOVED
```

Entrée pullback :

```text
pullback_entry_px = leader_entry_px + direction * allowed_pullback_bps
```

Le pullback expire vite :

```text
if now - signal_time > pullback_ttl_ms:
    EXPIRED
```

## V7.9 — Cluster de wallets : utile, mais attention au crowding

Plusieurs wallets alignés peuvent renforcer un signal. Mais s’ils sont trop corrélés, ils peuvent représenter un seul acteur ou un crowded trade.

### Score cluster

```text
cluster_score = weighted_sum(wallet_score_i * independence_weight_i)
```

### Pénalité crowding

```text
crowding_risk = cluster_notional / recent_market_depth
```

Décision :

```text
if cluster_agreement >= seuil and crowding_risk <= seuil:
    cluster_confirms_signal
else if crowding_risk > seuil:
    REJECT_CROWDING_RISK
```

## V7.10 — Exit engine : le gain vient souvent de la sortie

La copie naïve échoue souvent à la sortie. Le logiciel doit comparer plusieurs règles.

### Sorties obligatoires en simulation

```text
EXIT_LEADER_REDUCE      # le wallet leader réduit
EXIT_LEADER_CLOSE       # le wallet leader ferme
EXIT_PARTIAL_TP_1       # premier take profit partiel
EXIT_PARTIAL_TP_2       # second take profit partiel
EXIT_TRAILING_STOP      # protection du gain
EXIT_MAX_HOLD_TIME      # temps maximum dépassé
EXIT_EDGE_DECAY         # edge restant devient négatif
EXIT_REGIME_FLIP        # régime de marché change
EXIT_KILL_SWITCH        # incident système
EXIT_STOP_LOSS          # perte max trade atteinte
```

### Score exit_quality

```text
exit_quality_vs_mfe = realized_pnl / max_possible_pnl_during_trade
exit_quality_vs_leader = our_exit_pnl / leader_exit_pnl_estimated
```

But : ne pas seulement gagner, mais savoir si le bot sort trop tôt, trop tard, ou correctement.

## V7.11 — Profitability-Max Protocol en testnet/mock USDC

Le protocole de maximisation doit être appliqué dans cet ordre :

```text
1. protection système ;
2. qualité de données ;
3. refus des signaux faibles ;
4. edge_remaining positif ;
5. sizing faible et adaptatif ;
6. sortie structurée ;
7. journalisation complète ;
8. comparaison multi-stratégies ;
9. promotion seulement après preuve ;
10. jamais de relâchement des garde-fous pour “faire plus de trades”.
```

### Objectifs de validation en mock USDC

Ces seuils ne sont pas des promesses, mais des critères de promotion :

```yaml
promotion_criteria:
  minimum_paper_days: 21
  minimum_paper_signals: 300
  minimum_paper_trades: 50
  minimum_testnet_days: 14
  minimum_testnet_trades: 30
  profit_factor_min: 1.20
  max_drawdown_percent_max: 5.0
  edge_remaining_positive_ratio_min: 0.65
  copy_degradation_bps_median_max: 10
  no_trade_precision_min: 0.60
  reconciliation_error_count_max: 0
  duplicate_order_count_max: 0
  secret_leak_count_max: 0
```

Si ces seuils ne sont pas atteints : rester en observation/paper/testnet, ne pas promouvoir.

## V7.12 — Modèles Pydantic à demander à Codex

Codex doit créer des modèles stricts pour éviter les dictionnaires flous.

```python
class WalletCandidate(BaseModel):
    address: str
    source: str
    discovered_at_ms: int
    tags: list[str] = []
    reliability_score: float = 0.0

class WalletScore(BaseModel):
    address: str
    ts_ms: int
    performance_score: float
    risk_inverse_score: float
    regularity_score: float
    copyability_score: float
    timing_score: float
    liquidity_score: float
    stability_score: float
    toxicity_score: float
    final_score: float
    state: str

class PositionDelta(BaseModel):
    wallet: str
    coin: str
    ts_ms: int
    previous_size: float
    current_size: float
    delta_size: float
    delta_notional_usdc: float
    action: str
    side: str

class SignalCandidate(BaseModel):
    signal_id: str
    wallet: str
    coin: str
    side: str
    action: str
    detected_at_ms: int
    signal_age_ms: int
    wallet_score: float
    toxicity_score: float
    spread_bps: float
    estimated_slippage_bps: float
    orderbook_depth_usdc: float
    price_move_since_leader_bps: float
    edge_remaining_bps: float
    decision: str
    rejection_reason: str | None = None

class RiskDecision(BaseModel):
    signal_id: str
    allowed: bool
    decision: str
    failed_gates: list[str]
    max_size_usdc: float
    reason: str
```

## V7.13 — Tables DB supplémentaires V7

Ajouter ou prévoir :

```text
wallet_state_transitions
wallet_skill_estimates
wallet_toxicity_events
wallet_degradation_events
wallet_cluster_memberships
signal_lifecycle_events
signal_decay_metrics
orderbook_depth_metrics
slippage_simulations
edge_estimates
pullback_watchlist
exit_decisions
exit_quality_metrics
strategy_variant_results
promotion_decisions
codex_audit_runs
```

Chaque table critique doit avoir :

```text
id
run_id
ts_ms
source
config_hash
raw_json si applicable
```

## V7.14 — Nouvelles commandes CLI utiles

```bash
python -m hl_observer research-summary
python -m hl_observer wallet-backfill --address 0x...
python -m hl_observer wallet-state --address 0x...
python -m hl_observer wallet-promote --address 0x... --dry-run
python -m hl_observer cluster-detect
python -m hl_observer signal-watch
python -m hl_observer pullback-watch
python -m hl_observer compare-exits
python -m hl_observer no-trade-report
python -m hl_observer edge-report
python -m hl_observer promote-testnet-candidates --dry-run
python -m hl_observer codex-audit
```

## V7.15 — Tests supplémentaires obligatoires

```text
test_wallet_not_promoted_with_small_sample
test_wallet_penalized_for_one_big_win
test_wallet_penalized_for_martingale_pattern
test_wallet_degraded_after_recent_negative_expectancy
test_signal_rejected_when_edge_remaining_below_threshold
test_signal_rejected_when_price_already_moved
test_signal_waits_for_pullback_when_chase_too_high
test_signal_expires_when_pullback_ttl_exceeded
test_cluster_signal_penalized_by_crowding
test_copy_size_capped_by_orderbook_depth
test_exit_on_leader_reduce
test_exit_quality_vs_mfe_calculated
test_no_trade_precision_counts_good_refusals
test_paper_executor_uses_pessimistic_fill_model
test_testnet_order_requires_confirm_testnet_only
test_testnet_order_uses_cloid_idempotency
test_schedule_cancel_requested_when_testnet_orders_open
test_reject_if_orderbook_snapshot_stale
test_reject_if_ws_recently_reconnected
test_reject_if_agent_wallet_used_as_account_address
```

## V7.16 — Batches Codex recommandés

Ne pas demander à Codex de tout coder en une seule passe géante. Utiliser ces lots :

### Batch 1 — Fondations sécurité + config + CLI

- structure projet ;
- config Pydantic ;
- `.env.example` ;
- `doctor` ;
- `safety-audit` ;
- tests mainnet forbidden.

### Batch 2 — Hyperliquid REST read-only + DB raw

- `InfoClient` ;
- `allMids`, `l2Book`, `clearinghouseState`, `openOrders`, `userFills`, `userFillsByTime`, `orderStatus` ;
- stockage raw JSON ;
- pagination.

### Batch 3 — Wallet backfill + deltas

- snapshots ;
- position deltas ;
- state transitions ;
- wallet metrics baseline.

### Batch 4 — Wallet scoring V7

- skill vs luck ;
- toxicity ;
- copyability ;
- promotion states.

### Batch 5 — Signal engine V7

- signal candidate ;
- edge_remaining ;
- decay ;
- liquidity-aware copy ;
- pullback watch.

### Batch 6 — Paper trading pessimiste

- fill simulator ;
- cost model ;
- partial fills ;
- no-fill ;
- exit engine.

### Batch 7 — Dashboard + reports

- wallet table ;
- signals ;
- rejections ;
- edge reports ;
- no-trade analytics.

### Batch 8 — Testnet mock USDC verrouillé

- testnet check ;
- order builder ;
- cloid ;
- reduce-only ;
- cancel ;
- scheduleCancel ;
- jamais mainnet.

### Batch 9 — Backtest/replay

- replay event-sourced ;
- walk-forward ;
- Monte Carlo ;
- strategy comparisons.

## V7.17 — Prompt Codex V7 prêt à coller

```text
Tu es Codex en mode ingénieur logiciel senior Python, architecte trading-system, quant researcher et auditeur sécurité.

Lis README.md et AGENTS.md entièrement.

Périmètre absolu : Hyperliquid uniquement. Exécution uniquement testnet/mock USDC. Mainnet seulement read-only. Aucun trading réel. Aucun retrait. Aucune clé mainnet.

Objectif : construire un logiciel local qui maximise la qualité des signaux et l’espérance testable en mock USDC, sans jamais relâcher la sécurité.

Tu dois implémenter par petits lots, avec tests, en respectant la roadmap V7 :
1. sécurité/config/CLI ;
2. REST read-only + DB raw ;
3. wallet backfill + deltas ;
4. wallet scoring skill-vs-luck ;
5. signal scoring avec edge_remaining ;
6. paper trading pessimiste ;
7. dashboard/reports ;
8. testnet mock USDC verrouillé ;
9. backtest/replay.

Contraintes :
- pas de mainnet exchange endpoint ;
- pas de live executor actif ;
- pas de seed phrase ;
- pas de clé privée mainnet ;
- pas de secret dans les logs ;
- pas de LLM dans le hot path ;
- tout signal incertain = rejet ;
- tout ordre testnet doit nécessiter HL_ENV=testnet, HL_ENABLE_TESTNET_EXECUTION=true et --confirm-testnet-only ;
- utiliser cloid pour idempotence ;
- utiliser reduce-only pour les sorties ;
- prévoir scheduleCancel/dead man's switch en testnet ;
- stocker raw_json + données normalisées ;
- tests obligatoires avant livraison.

À la fin de chaque lot, donne :
- fichiers créés/modifiés ;
- commandes exécutées ;
- résultats des tests ;
- risques restants ;
- confirmation que mainnet execution est impossible ;
- résumé en français.
```

## V7.18 — Ce que Codex ne doit pas essayer d’optimiser

Interdictions d’optimisation dangereuses :

```text
ne pas augmenter le levier pour améliorer le PnL ;
ne pas baisser min_wallet_score pour obtenir plus de trades ;
ne pas augmenter max_slippage pour entrer plus souvent ;
ne pas ignorer stale signals ;
ne pas supprimer les refus ;
ne pas ignorer les frais ;
ne pas supposer fill complet ;
ne pas transformer Polymarket YES/NO en Hyperliquid ;
ne pas utiliser un thread X comme vérité ;
ne pas coder mainnet “pour plus tard” activable par config simple.
```

Le chemin vers le maximum de gains testables passe par :

```text
data quality > wallet quality > signal quality > edge_remaining > execution quality > exit quality > risk containment
```

Pas par :

```text
plus de trades > plus de levier > plus de risque
```
---

# SUPPLÉMENT V8 — Profitability-Max / Wallet Replication Engineering

> Cette section ajoute une couche d’ingénierie orientée **maximisation des gains simulés et testnet**, en restant dans le périmètre décidé : **Hyperliquid uniquement**, **mock USDC uniquement pour l’exécution**, **mainnet lecture seule**, **aucune exposition réelle dans le MVP**.  
> L’objectif opérationnel est de rendre le logiciel beaucoup plus intelligent que du copy trading basique : il doit sélectionner les wallets, filtrer les signaux, attendre les meilleures conditions, sortir proprement et mesurer l’edge restant après tous les coûts.

## V8.1 Changement d’angle : “copier un wallet” est trop simple

Un logiciel vraiment ambitieux ne doit pas faire :

```text
wallet A achète → le bot achète immédiatement
```

Il doit faire :

```text
wallet A agit
→ le bot identifie le type exact d’action
→ vérifie si ce wallet est encore robuste
→ vérifie si le trade est copiable
→ calcule l’edge restant
→ attend éventuellement un meilleur prix
→ simule plusieurs sorties
→ refuse si le moindre coût détruit l’edge
→ paper trade / testnet seulement si le trade passe toutes les portes
```

La différence entre un bot faible et un bot fort est donc :

```text
Bot faible = copie vite.
Bot fort = copie uniquement quand il reste un avantage mesurable.
```

## V8.2 Reconstitution réaliste du “bot miracle” en 20 briques

Les récits viraux autour des bots Claude / Polymarket / smart wallets doivent être traduits en architecture technique. La reconstruction la plus solide est :

1. **Discovery massive** : récupérer des wallets depuis leaderboards, trackers, adresses connues, historiques de gros PnL.
2. **Backfill historique** : aspirer autant de fills/positions/orders que possible.
3. **Normalisation** : transformer les données hétérogènes en événements standard.
4. **Déduplication** : éviter de compter deux fois un fill, un delta ou un order update.
5. **Wallet profiling** : comprendre le style du wallet.
6. **Skill vs chance** : isoler les wallets réellement robustes.
7. **Toxicity detection** : exclure martingale, averaging down, surlevier, one-shot PnL.
8. **Market compatibility** : vérifier que les marchés tradés ont assez de liquidité.
9. **Signal detection** : détecter ouverture, ajout, réduction, fermeture, flip long/short.
10. **Signal freshness** : mesurer si le signal est encore exploitable.
11. **Order book context** : vérifier spread, profondeur, OBI, volatilité et slippage.
12. **Crowding check** : éviter les trades déjà copiés par trop de monde.
13. **Edge calculation** : calculer `edge_remaining_bps`.
14. **Entry planner** : choisir market/IOC simulé, limit, delayed copy ou no trade.
15. **Exit planner** : définir take-profit partiel, trailing, stop, sortie si leader réduit.
16. **Paper execution pessimiste** : simuler un prix moins bon que l’idéal.
17. **Reconciliation** : comparer état théorique et état réel/testnet.
18. **No-trade analytics** : mesurer la qualité des refus.
19. **Adaptive scoring** : dégrader les wallets dont la copie se détériore.
20. **Feedback loop** : rapports, dashboards, ajustement des seuils.

## V8.3 Objectif “gains optimaux et sûrs” : ce que l’on peut contrôler

Le logiciel doit maximiser ce qui est contrôlable :

```text
- qualité des wallets suivis ;
- fraîcheur des signaux ;
- coût d’entrée ;
- coût de sortie ;
- slippage ;
- taille des positions ;
- perte maximale simulée ;
- qualité du stop ;
- qualité de sortie ;
- stabilité API/WS ;
- taux de refus intelligent ;
- edge_remaining positif ;
- stress tests ;
- durée de validation.
```

Le README et le code doivent donc éviter une obsession du winrate brut. Un winrate élevé avec pertes énormes est mauvais. Un winrate plus modéré avec petites pertes, bons gains moyens, drawdown contrôlé et edge_remaining positif est supérieur.

## V8.4 Profitability-Max Protocol

Le protocole V8 pour viser le maximum de gains en environnement contrôlé :

```text
1. Ne garder que les wallets dont le score final est élevé sur plusieurs fenêtres.
2. Ne jamais promouvoir un wallet sur un seul gros trade.
3. Exiger un edge_remaining positif avant paper/testnet.
4. Refuser les signaux trop vieux.
5. Refuser les marchés sans profondeur.
6. Refuser les spreads larges.
7. Refuser si le prix a déjà trop bougé depuis l’action du wallet.
8. Diminuer la taille quand la volatilité augmente.
9. Sortir partiellement vite quand le trade part bien.
10. Couper vite quand le trade invalide l’hypothèse.
11. Dégrader automatiquement un wallet si la copie devient mauvaise.
12. Mesurer les refus pour améliorer les seuils.
13. Tester en régime haussier, baissier, range, forte volatilité et faible liquidité.
14. Promouvoir seulement les stratégies qui restent positives après coûts pessimistes.
15. Exécuter uniquement en mock USDC dans le MVP.
```

## V8.5 Score wallet V8 : modèle complet

Le score wallet doit être plus sévère que dans les versions précédentes.

```text
wallet_score_v8 =
  0.16 * net_performance_score
+ 0.14 * risk_adjusted_score
+ 0.12 * consistency_score
+ 0.12 * copyability_score
+ 0.10 * timing_score
+ 0.10 * exit_quality_score
+ 0.08 * liquidity_score
+ 0.08 * regime_robustness_score
+ 0.06 * freshness_of_edge_score
+ 0.04 * data_quality_score
- 0.12 * toxicity_penalty
- 0.08 * crowding_penalty
```

### V8.5.1 net_performance_score

Mesure uniquement la performance utile :

```text
net_pnl_estimated = gross_pnl - fees - estimated_slippage - funding_cost
```

Ne pas classer un wallet sur PnL brut seul.

### V8.5.2 risk_adjusted_score

Inclure :

```text
max_drawdown
avg_drawdown
tail_loss
loss_streak
liquidation_distance
exposure_concentration
leverage_proxy
```

### V8.5.3 consistency_score

Un wallet robuste doit gagner sur plusieurs fenêtres :

```text
7d
14d
30d
90d si données disponibles
par régime de marché
par actif
```

### V8.5.4 copyability_score

Le wallet est utile seulement si ses trades sont copiables :

```text
position_size_compatible
asset_liquidity_ok
spread_ok
depth_ok
time_to_move_sufficient
exit_liquidity_ok
not_too_big
not_too_crowded
```

### V8.5.5 exit_quality_score

Beaucoup de bots entrent correctement mais sortent mal. Le score de sortie doit mesurer :

```text
leader_exits_before_reversal
leader_reduces_into_strength
leader_holds_losers_too_long
leader_uses_stop_like_behavior
leader_lets_profit_decay
```

### V8.5.6 toxicity_penalty

Pénalités fortes :

```text
one_big_win_dependency
martingale_pattern
averaging_down_pattern
high_leverage_proxy
illiquid_asset_preference
panic_exit_pattern
style_drift
hedge_incomplete
copy_degradation_rising
drawdown_hidden_by_unrealized_pnl
```

## V8.6 Détection “skill vs chance”

Codex doit coder une méthode pour empêcher qu’un wallet chanceux soit promu.

### Indicateurs de chance

```text
- moins de N trades ;
- plus de 50 % du PnL vient d’un seul trade ;
- performance concentrée sur un seul actif ;
- performance concentrée sur une seule journée ;
- winrate élevé mais average loss énorme ;
- PnL positif mais MFE/MAE instable ;
- forte exposition non réalisée ;
- drawdown important masqué par une position gagnante ;
- comportement de martingale.
```

### Méthodes de correction

```text
bayesian_shrinkage_winrate
wilson_lower_bound
pnl_concentration_penalty
minimum_sample_size_gate
bootstrap_confidence_interval
walk_forward_validation
regime_split_validation
```

Exemple :

```text
if trades_count < 50:
    wallet_state = OBSERVE_ONLY

if top_1_trade_pnl_share > 0.35:
    apply one_big_win_penalty

if wilson_lower_bound_winrate < threshold:
    do not promote to paper/testnet
```

## V8.7 Score signal V8

```text
signal_score_v8 =
  0.14 * wallet_score_v8
+ 0.13 * signal_freshness
+ 0.12 * delta_quality
+ 0.11 * liquidity_depth_score
+ 0.10 * spread_score
+ 0.10 * slippage_score
+ 0.09 * orderbook_confirmation
+ 0.08 * regime_alignment
+ 0.07 * cluster_confirmation
+ 0.06 * exit_plan_quality
+ 0.05 * funding_context
+ 0.05 * testnet_replay_similarity
- 0.12 * crowding_risk
- 0.10 * late_entry_penalty
```

### Décisions V8

```text
IGNORE
OBSERVE_ONLY
PAPER_CANDIDATE
PAPER_TRADE
TESTNET_CANDIDATE
TESTNET_ALLOWED
REJECT_TOO_LATE
REJECT_EDGE_NEGATIVE
REJECT_EDGE_TOO_SMALL
REJECT_TOO_ILLIQUID
REJECT_SPREAD_TOO_WIDE
REJECT_SLIPPAGE_TOO_HIGH
REJECT_WALLET_TOXIC
REJECT_WALLET_UNPROVEN
REJECT_MARKET_REGIME_BAD
REJECT_CROWDING_TOO_HIGH
REJECT_EXIT_PLAN_WEAK
REJECT_DATA_GAP
REJECT_WS_RECENTLY_RECONNECTED
REJECT_RECONCILIATION_UNCERTAIN
REJECT_DUPLICATE_ORDER_RISK
REJECT_API_UNSTABLE
```

## V8.8 Edge remaining : métrique centrale

`edge_remaining_bps` devient la métrique principale.

```text
expected_edge_bps =
  leader_expected_move_bps
+ cluster_confirmation_bps
+ orderbook_confirmation_bps
+ regime_bonus_bps

costs_bps =
  taker_fee_bps
+ spread_cost_bps
+ estimated_slippage_bps
+ latency_decay_bps
+ adverse_selection_bps
+ funding_expected_cost_bps

edge_remaining_bps = expected_edge_bps - costs_bps
```

Règle :

```text
if edge_remaining_bps <= min_edge_required_bps:
    reject signal
```

Exemples de seuils initiaux testnet :

```yaml
profitability:
  min_edge_required_bps: 8
  strong_edge_bps: 20
  elite_edge_bps: 35
  edge_decay_half_life_ms: 1200
  reject_if_price_moved_bps: 12
  reject_if_spread_bps_above: 6
  reject_if_slippage_bps_above: 10
```

## V8.9 Signal decay : un bon signal vieillit très vite

Le copy-trading perd souvent son avantage à cause de la latence.

```text
decayed_edge = raw_edge * exp(- signal_age_ms / half_life_ms)
```

Paramètres :

```yaml
signal_decay:
  half_life_ms_default: 1200
  half_life_ms_high_volatility: 500
  half_life_ms_low_volatility: 2500
  reject_after_ms_default: 3500
  reject_after_ms_high_volatility: 1200
```

Codex doit permettre de calibrer ces seuils en paper trading.

## V8.10 Delayed Copy intelligent

Copier immédiatement peut être mauvais si le leader a déjà déplacé le prix. Le bot doit tester un mode delayed-copy :

```text
leader_buy_detected
→ attendre pullback léger
→ entrer seulement si edge_remaining reste positif
→ annuler si le prix part trop loin
```

États :

```text
IMMEDIATE_COPY
DELAYED_COPY_WAITING_PULLBACK
DELAYED_COPY_FILLED
DELAYED_COPY_EXPIRED
DELAYED_COPY_CANCELED_EDGE_DECAY
```

Règles :

```yaml
delayed_copy:
  enabled_in_paper: true
  enabled_in_testnet: true
  max_wait_ms: 5000
  target_pullback_bps: 4
  cancel_if_move_away_bps: 10
  require_orderbook_still_supportive: true
```

## V8.11 Cluster de wallets : confirmation et danger

Un cluster de plusieurs wallets peut améliorer la conviction, mais aussi augmenter le crowding.

### Score cluster

```text
cluster_score =
  weighted_sum(wallet_score_i * direction_agreement_i * freshness_i)
```

### Pénalité crowding

```text
crowding_penalty =
  f(number_of_followed_wallets_same_trade,
    public_visibility,
    speed_of_price_move,
    orderbook_depth_consumed)
```

Règle :

```text
cluster positif + crowding faible = signal renforcé
cluster positif + crowding fort = attendre pullback ou refuser
```

## V8.12 Sortie : le vrai moteur des gains

Un bot qui entre bien mais sort mal perd l’avantage. Le README doit demander à Codex un `exit_engine.py`.

### Sorties possibles

```text
EXIT_ON_LEADER_REDUCE
EXIT_ON_LEADER_CLOSE
EXIT_ON_CLUSTER_REVERSAL
EXIT_PARTIAL_TP_1
EXIT_PARTIAL_TP_2
EXIT_TRAILING_STOP
EXIT_TIME_STOP
EXIT_EDGE_DECAY
EXIT_ORDERBOOK_REVERSAL
EXIT_MAX_ADVERSE_EXCURSION
EXIT_RECONCILIATION_UNCERTAIN
EXIT_KILL_SWITCH
```

### Take profit partiel

```yaml
exit:
  partial_tp_1_bps: 12
  partial_tp_1_size_pct: 40
  partial_tp_2_bps: 25
  partial_tp_2_size_pct: 30
  trailing_after_tp1_bps: 8
  hard_stop_bps: 12
  max_hold_seconds: 900
```

### Exit quality

```text
exit_quality =
  realized_exit_score
  vs leader_exit
  vs best_possible_exit_after_entry
  vs stop_loss
  vs MFE
```

## V8.13 Paper trading pessimiste

Le paper trading doit pénaliser le bot, pas l’avantager.

```yaml
paper_execution:
  assume_taker_fee: true
  add_extra_slippage_bps: 3
  simulate_partial_fills: true
  simulate_non_fills: true
  simulate_latency_ms: 300
  simulate_ws_reconnect_events: true
  simulate_rejected_orders: true
  pessimistic_exit: true
```

Chaque signal doit être testé sous plusieurs scénarios :

```text
normal
high_slippage
high_latency
thin_orderbook
fast_reversal
partial_fill
api_delay
ws_reconnect
```

## V8.14 Backtest / replay orienté “survie puis profit”

Le replay doit rejouer :

```text
market prices
l2Book snapshots
trades
wallet fills
position deltas
funding snapshots
orders
rejected orders
```

Métriques de validation :

```text
net_pnl_after_costs
profit_factor
expectancy
max_drawdown
MFE/MAE
copy_degradation
edge_remaining_distribution
exit_quality_distribution
no_trade_precision
false_reject_rate
false_accept_rate
latency_sensitivity
slippage_sensitivity
wallet_decay_rate
```

## V8.15 No-trade analytics : transformer les refus en avantage

Le bot doit apprendre de ses refus.

Tables :

```text
no_trade_decisions
rejected_signals
rejection_outcome_simulation
```

Champs :

```text
signal_id
reason
wallet
coin
direction
timestamp
price_at_rejection
price_1m
price_5m
price_15m
would_have_won
would_have_lost
avoided_loss_bps
missed_gain_bps
```

Objectif :

```text
augmenter avoided_loss_bps
réduire missed_gain_bps
trouver les refus trop sévères
trouver les refus pas assez sévères
```

## V8.16 Wallet degradation : arrêter de suivre un wallet qui se dégrade

Un wallet peut être bon puis perdre son edge.

```text
wallet_degradation_score =
  recent_copy_degradation
+ recent_drawdown
+ style_drift
+ liquidity_deterioration
+ edge_remaining_decline
```

États :

```text
ACTIVE
WATCHLIST
DEGRADED
COOLDOWN
BLACKLISTED
```

Règle :

```text
si un wallet passe DEGRADED :
  plus de TESTNET_ALLOWED
  seulement OBSERVE/PAPER
```

## V8.17 Structure de fichiers V8 à demander à Codex

Ajouter ou vérifier :

```text
src/edge/
  edge_remaining.py
  signal_decay.py
  copy_degradation.py
  exit_quality.py

src/exits/
  exit_engine.py
  partial_take_profit.py
  trailing_stop.py
  leader_exit_monitor.py
  time_stop.py

src/clusters/
  wallet_clusterer.py
  crowding_detector.py
  cluster_signal_score.py

src/validation/
  no_trade_analyzer.py
  wallet_degradation.py
  skill_vs_luck.py
  bootstrap.py
  walk_forward.py

src/paper/
  pessimistic_fill_model.py
  partial_fill_model.py
  latency_model.py
  rejection_model.py

src/testnet/
  testnet_order_builder.py
  testnet_reconciliation.py
  testnet_safety_gates.py
```

## V8.18 Tables DB V8

```text
edge_metrics
signal_decay_metrics
copy_degradation_metrics
exit_quality_metrics
mfe_mae_metrics
cluster_events
crowding_events
wallet_degradation_events
skill_vs_luck_scores
delayed_copy_orders
exit_events
paper_scenarios
paper_stress_results
testnet_reconciliation_events
no_trade_outcome_checks
```

## V8.19 Commandes CLI V8

```bash
python -m hl_observer discover-wallets --source leaderboard
python -m hl_observer backfill-wallet --address 0x...
python -m hl_observer score-wallets --window 7d
python -m hl_observer score-wallets --window 30d
python -m hl_observer detect-signals --mode paper
python -m hl_observer analyze-edge
python -m hl_observer analyze-no-trades
python -m hl_observer analyze-wallet-degradation
python -m hl_observer replay --scenario high-slippage
python -m hl_observer paper-run --pessimistic
python -m hl_observer paper-report --include-rejections
python -m hl_observer testnet-run --confirm-testnet-only
python -m hl_observer safety-audit --strict
```

## V8.20 Critères de promotion d’un signal vers testnet mock USDC

Un signal ne passe en testnet que si :

```text
wallet_score_v8 >= 75
signal_score_v8 >= 80
edge_remaining_bps >= min_edge_required_bps
copy_degradation_recent acceptable
exit_quality_recent acceptable
no critical data gap
no ws reconnect recent
no api instability
liquidity depth ok
spread ok
slippage ok
market regime ok
no crowding red flag
paper scenario normal positive
paper scenario high_slippage acceptable
paper scenario high_latency acceptable
```

## V8.21 Configuration V8

```yaml
profitability_max:
  enabled: true
  mode: "testnet_only"
  min_wallet_score: 75
  min_signal_score: 80
  min_edge_remaining_bps: 8
  min_profit_factor_paper: 1.35
  min_expectancy_bps: 3
  max_copy_degradation_bps: 7
  min_exit_quality_score: 65
  max_wallet_degradation_score: 35
  require_positive_after_pessimistic_costs: true
  require_no_trade_analytics: true

skill_vs_luck:
  min_trades: 50
  max_top_trade_pnl_share: 0.35
  require_wilson_lower_bound: true
  require_bootstrap_positive: true

paper_validation:
  min_days: 14
  min_trades: 100
  stress_scenarios_required:
    - normal
    - high_slippage
    - high_latency
    - thin_book
    - fast_reversal
    - partial_fill

testnet_validation:
  enabled: true
  use_mock_usdc_only: true
  max_testnet_trade_size_usdc: 5
  max_testnet_daily_loss_usdc: 15
  require_schedule_cancel: true
  require_reduce_only_exits: true
  require_cloid: true
  require_reconciliation: true
```

## V8.22 Prompt Codex V8 — à utiliser après lecture README + AGENTS

```text
Tu es Codex en mode ingénieur logiciel senior, architecte trading-system, spécialiste market microstructure, Python backend, testing et sécurité.

Lis README.md puis AGENTS.md intégralement avant de coder.

Objectif :
améliorer / créer Hyperliquid Smart-Wallet Observer en ciblant le maximum de performance testable sur Hyperliquid, uniquement en lecture seule, paper trading et testnet mock USDC.

Important :
le but n’est pas de copier naïvement. Le but est de construire un système intelligent :
- discovery wallets ;
- backfill ;
- scoring skill vs luck ;
- signal delta ;
- edge_remaining ;
- delayed copy ;
- exit engine ;
- pessimistic paper trading ;
- testnet safety gates ;
- no-trade analytics ;
- wallet degradation.

Règles absolues :
- mainnet execution impossible dans le MVP ;
- aucune clé privée mainnet ;
- aucun retrait ;
- testnet seulement avec mock USDC ;
- aucune décision LLM dans le hot path ;
- refus par défaut si donnée manquante ou edge insuffisant ;
- chaque signal doit avoir une décision explicite ;
- chaque refus doit être stocké ;
- chaque trade paper/testnet doit être réconcilié.

Travail demandé par lots :
LOT 1 : structure projet + configs + doctor + safety-audit.
LOT 2 : client REST /info + pagination + stockage raw.
LOT 3 : WebSocket market + reconnect + stale guard.
LOT 4 : wallet discovery + wallet profiling.
LOT 5 : scoring wallet V8 + skill_vs_luck.
LOT 6 : signal detection + signal score V8.
LOT 7 : edge_remaining + signal_decay + copy_degradation.
LOT 8 : risk engine + guards.
LOT 9 : paper pessimistic executor + scenarios.
LOT 10 : exit engine complet.
LOT 11 : no-trade analytics + wallet degradation.
LOT 12 : dashboard/reporting.
LOT 13 : testnet executor locked.
LOT 14 : tests complets.

À la fin :
- lister fichiers créés/modifiés ;
- lister commandes de test ;
- confirmer que mainnet execution reste impossible ;
- confirmer que testnet est désactivé par défaut ;
- confirmer que edge_remaining gouverne l’entrée ;
- résumer les risques restants et les prochaines mesures.
```

## V8.23 Sources techniques ajoutées

Sources à conserver dans `source_references` :

```text
Hyperliquid Info endpoint:
https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint

Hyperliquid WebSocket subscriptions:
https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions

Hyperliquid Rate limits:
https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits

Hyperliquid Nonces and API wallets:
https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/nonces-and-api-wallets

Hyperliquid Exchange endpoint:
https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint

Hyperliquid Python SDK:
https://github.com/hyperliquid-dex/hyperliquid-python-sdk

Polymarket Merge Tokens:
https://docs.polymarket.com/trading/ctf/merge

Polymarket Negative Risk:
https://docs.polymarket.com/advanced/neg-risk

Claude Code Overview:
https://code.claude.com/docs/en/overview

Claude Code Security:
https://code.claude.com/docs/en/security
```
---

# SUPPLÉMENT V9 — Miracle Bot Reverse Engineering & Profitability Engine

> Cette V9 conserve tout le contenu précédent et ajoute une couche encore plus opérationnelle pour Codex.  
> Périmètre intangible : **Hyperliquid uniquement pour le code**, **exécution testnet/mock USDC uniquement**, **mainnet lecture seule**, **aucune clé mainnet**, **aucun retrait**, **aucun ordre réel dans le MVP**.  
> Objectif : transformer l’idée du “bot miracle” en une **machine de recherche de gains testnet** : trouver les meilleurs wallets, répliquer uniquement les signaux à edge mesurable, améliorer les entrées, améliorer les sorties, et refuser tout ce qui affaiblit l’avantage.

## V9.1 Vision positive : Profit Engine, pas simple copy bot

Le logiciel doit être conçu comme un **Profit Engine expérimental**.

Un copy bot basique fait :

```text
wallet détecté → copier
```

Notre système doit faire :

```text
wallet détecté
→ preuve historique
→ robustesse wallet
→ qualité du signal
→ edge restant
→ scénario d’entrée
→ scénario de sortie
→ stress test
→ paper/testnet
→ feedback loop
```

Le logiciel ne doit pas seulement “suivre les bons wallets”.  
Il doit découvrir **quand** un wallet est copiable, **quand il ne l’est plus**, **comment améliorer son prix d’entrée**, **quand sortir avant que l’edge disparaisse**, et **comment augmenter l’espérance nette en mock USDC**.

## V9.2 Hypothèse la plus forte sur le “bot miracle”

La version la plus crédible d’un bot performant observé sur X / Polymarket / smart-money tracking serait un système qui combine :

```text
1. Recherche massive de wallets.
2. Classement des wallets par PnL, régularité, volume, style.
3. Exclusion des wallets chanceux.
4. Détection des wallets qui bougent avant le marché.
5. Détection des marchés courts à forte vitesse.
6. Mesure du délai entre action du wallet et mouvement du prix.
7. Copy seulement si le mouvement n’est pas déjà consommé.
8. Position sizing réduit et contrôlé.
9. Take profit rapide sur une partie.
10. Sortie si le wallet réduit ou si le carnet se retourne.
11. Refus automatique si spread/slippage/latence détruisent l’edge.
12. Mesure continue de la dégradation de copie.
13. Mise en cooldown des wallets qui perdent leur edge.
14. Exploitation de micro-arbitrages ou mécaniques structurelles quand disponibles.
15. Dashboard + alertes + rapports pour améliorer les seuils.
```

Sur Hyperliquid, on conserve l’esprit :

```text
wallet intelligence + orderbook intelligence + edge accounting + testnet execution
```

Et on ignore ce qui est Polymarket-only :

```text
YES/NO merge
negative risk
prediction-market outcome tokens
```

## V9.3 Les 7 questions que le logiciel doit poser avant tout signal

Chaque signal doit répondre à ces questions dans l’ordre :

```text
1. Ce wallet est-il réellement fort ou seulement chanceux ?
2. Ce wallet est-il copiable avec notre taille ?
3. Le signal est-il encore frais ?
4. Le carnet permet-il d’entrer sans détruire l’edge ?
5. Le prix n’a-t-il pas déjà bougé trop loin ?
6. Avons-nous un plan de sortie supérieur au simple “attendre” ?
7. L’edge_remaining reste-t-il positif dans un scénario pessimiste ?
```

Si une réponse est insuffisante, le signal reste en observation ou paper, pas en testnet.

## V9.4 Architecture “Wallet Replication Loop”

Codex doit structurer le système autour d’une boucle claire :

```text
DISCOVER
  → BACKFILL
    → PROFILE
      → SCORE
        → MONITOR
          → DETECT_DELTA
            → COMPUTE_EDGE
              → PLAN_ENTRY
                → PLAN_EXIT
                  → RISK_GATE
                    → PAPER_OR_TESTNET
                      → RECONCILE
                        → LEARN
```

Chaque étape doit produire un objet traçable en base :

```text
DiscoveryEvent
BackfillRun
WalletProfile
WalletScore
MonitoringState
PositionDelta
SignalCandidate
EdgeEstimate
EntryPlan
ExitPlan
RiskDecision
PaperTrade
TestnetOrder
ReconciliationEvent
LearningUpdate
```

## V9.5 Modèle “Gain Assurance Score” pour testnet/mock USDC

Créer une métrique de confiance orientée performance, appelée :

```text
gain_assurance_score
```

Elle ne doit pas être une promesse verbale. Elle doit être une **mesure calculée**.

```text
gain_assurance_score =
  0.18 * edge_remaining_score
+ 0.16 * wallet_quality_score
+ 0.14 * copyability_score
+ 0.12 * exit_plan_score
+ 0.10 * liquidity_score
+ 0.10 * stress_test_score
+ 0.08 * no_trade_precision_score
+ 0.07 * regime_alignment_score
+ 0.05 * data_quality_score
- 0.10 * degradation_penalty
- 0.08 * crowding_penalty
```

États :

```text
LOW_CONFIDENCE
WATCH_ONLY
PAPER_OK
PAPER_STRONG
TESTNET_SMALL
TESTNET_STRONG
COOLDOWN
```

Seuls `TESTNET_SMALL` et `TESTNET_STRONG` peuvent générer des ordres testnet.

## V9.6 “Lead-Lag Analysis” : savoir si le wallet précède vraiment le marché

Le bot doit vérifier si un wallet a une vraie avance temporelle.

Pour chaque delta important :

```text
t0 = timestamp du fill/delta wallet
px0 = prix au moment détecté
px_10s = prix 10 secondes après
px_30s = prix 30 secondes après
px_1m = prix 1 minute après
px_5m = prix 5 minutes après
```

Pour un long :

```text
forward_return_30s_bps = (px_30s - px0) / px0 * 10000
```

Pour un short, inverse.

À stocker :

```text
leader_forward_return_10s_bps
leader_forward_return_30s_bps
leader_forward_return_1m_bps
leader_forward_return_5m_bps
```

Un wallet devient prioritaire s’il montre :

```text
forward_return positif après ses entrées
drawdown limité juste après entrée
sorties avant retournement
edge durable malgré coûts
```

## V9.7 “Copy Half-Life” : mesurer la durée de vie d’un signal

Un signal de copy trading a une durée de vie. Codex doit calculer :

```text
copy_half_life_ms
```

Méthode :

```text
edge_at_detection = edge brut estimé
edge_after_500ms
edge_after_1s
edge_after_2s
edge_after_5s
```

Si l’edge tombe vite, le bot doit :

```text
- refuser les signaux tardifs ;
- exiger un spread plus bas ;
- réduire la taille ;
- privilégier delayed copy/pullback ;
- basculer le wallet en mode observation.
```

## V9.8 Modèle “Replicable PnL” au lieu de PnL wallet

Le PnL d’un wallet ne suffit pas. Le bot doit estimer :

```text
replicable_pnl
```

Formule simplifiée :

```text
replicable_pnl =
  leader_pnl
- copy_degradation_cost
- fees
- spread_cost
- slippage_cost
- missed_fill_cost
- late_exit_cost
```

Score :

```text
replicability_ratio = replicable_pnl / leader_pnl
```

Règle :

```text
si replicability_ratio < seuil :
    wallet non prioritaire
```

Seuils initiaux :

```yaml
replicability:
  min_replicability_ratio: 0.45
  strong_replicability_ratio: 0.65
  elite_replicability_ratio: 0.80
```

## V9.9 Détection des styles de wallets

Classer chaque wallet dans un ou plusieurs styles :

```text
SCALPER_FAST
SWING_TRADER
BREAKOUT_TRADER
MEAN_REVERSION_TRADER
MOMENTUM_CHASER
LIQUIDITY_ABSORBER
HEDGER
MARTINGALE_AVERAGER
ONE_BIG_WIN
MARKET_MAKER_LIKE
EVENT_REACTIVE
UNKNOWN
```

Chaque style a une politique :

```text
SCALPER_FAST → edge très court, copy difficile, WS prioritaire seulement si ultra performant.
SWING_TRADER → plus copiable, paper/testnet favorable si liquidité bonne.
BREAKOUT_TRADER → risque de signal tardif, delayed copy recommandé.
MEAN_REVERSION_TRADER → nécessite régime range, stop strict.
MARTINGALE_AVERAGER → forte pénalité.
ONE_BIG_WIN → observation seulement.
HEDGER → difficile à copier car position visible incomplète.
```

## V9.10 Entrée : ne pas seulement copier, optimiser le prix

Types d’entrée à tester :

```text
ENTRY_IMMEDIATE_IOC_SIM
ENTRY_LIMIT_JOIN_BID_ASK
ENTRY_DELAYED_PULLBACK
ENTRY_CONFIRM_BREAKOUT
ENTRY_SKIP_IF_CHASE
ENTRY_SCALE_IN_TESTNET_SMALL
```

Règles :

```text
si prix déjà déplacé > reject_if_price_moved_bps → refus
si pullback arrive dans max_wait_ms → entrée delayed
si carnet se retourne → annulation
si spread s’élargit → annulation
```

## V9.11 Sortie : augmenter l’espérance par la gestion active

Codex doit traiter la sortie comme un module stratégique complet.

Sorties disponibles :

```text
EXIT_PARTIAL_FAST_PROFIT
EXIT_TRAILING_AFTER_PARTIAL
EXIT_LEADER_REDUCE
EXIT_LEADER_CLOSE
EXIT_CLUSTER_DIVERGENCE
EXIT_ORDERBOOK_WEAKNESS
EXIT_EDGE_DECAY
EXIT_TIME_DECAY
EXIT_VOLATILITY_SPIKE
EXIT_HARD_STOP
EXIT_KILL_SWITCH
```

Logique recommandée :

```text
1. Prendre une partie du profit rapidement si le trade part bien.
2. Remonter le stop après TP1.
3. Sortir si le leader réduit fortement.
4. Sortir si le cluster se désaligne.
5. Sortir si le carnet perd le support.
6. Sortir si l’edge_remaining devient faible.
```

## V9.12 “Profit Locking” en mock USDC

Le testnet doit intégrer un système de verrouillage des gains simulés :

```yaml
profit_locking:
  enabled: true
  lock_after_profit_bps: 15
  move_stop_to_breakeven_after_tp1: true
  reduce_size_after_consecutive_wins: false
  cooldown_after_large_win: true
  max_giveback_after_mfe_pct: 35
```

Objectif :

```text
ne pas rendre tout le MFE au marché
```

## V9.13 Détection de crowding

Le copy trading peut devenir moins bon si trop de signaux convergent.

Indicateurs de crowding :

```text
plusieurs wallets suivis entrent dans la même direction très vite
prix a déjà bougé brutalement
l2Book profondeur consommée
spread s’élargit
trades publics accélèrent
slippage estimé monte
```

Décision :

```text
crowding faible + cluster fort → renforcer conviction
crowding fort + prix déjà parti → delayed copy ou refus
```

## V9.14 Testnet tournament mode

Créer un mode pour comparer plusieurs variantes de stratégie en mock USDC :

```text
strategy_A = immediate copy
strategy_B = delayed pullback
strategy_C = partial TP fast
strategy_D = strict edge only
strategy_E = cluster confirmation only
```

Le bot exécute en paper/testnet selon des portefeuilles virtuels séparés :

```text
paper_portfolio_A
paper_portfolio_B
paper_portfolio_C
testnet_portfolio_best_only
```

Métriques :

```text
net_pnl
profit_factor
max_drawdown
edge_remaining_avg
exit_quality
copy_degradation
no_trade_precision
trade_frequency
capital_efficiency
```

## V9.15 Objectifs de progression testnet

Au lieu de demander à Codex “coder tout”, il faut le faire en niveaux :

```text
Level 0 — Read-only data correct.
Level 1 — Wallet scoring stable.
Level 2 — Signal scoring stable.
Level 3 — Paper trading positif en scénario normal.
Level 4 — Paper trading positif en scénario pessimiste.
Level 5 — Testnet small sur mock USDC.
Level 6 — Testnet tournament.
Level 7 — Testnet strong wallets only.
Level 8 — Long-run validation report.
```

Chaque niveau doit avoir un rapport.

## V9.16 Seuils de promotion V9

```yaml
promotion:
  to_watchlist:
    min_trades: 30
    min_data_days: 3
    min_data_quality_score: 70

  to_premium_ws:
    min_wallet_score: 75
    min_replicability_ratio: 0.45
    max_toxicity_score: 25
    max_one_trade_pnl_share: 0.35

  to_paper_trade:
    min_signal_score: 80
    min_edge_remaining_bps: 8
    max_signal_age_ms: 2500
    max_spread_bps: 6
    max_slippage_bps: 10

  to_testnet_small:
    min_gain_assurance_score: 78
    min_paper_days: 14
    min_paper_trades: 100
    min_profit_factor_pessimistic: 1.35
    max_drawdown_pessimistic_pct: 6
    min_no_trade_precision: 0.55
```

## V9.17 Tables DB supplémentaires

```text
lead_lag_metrics
copy_half_life_metrics
replicable_pnl_metrics
wallet_style_classifications
entry_plan_events
profit_lock_events
strategy_tournament_runs
strategy_tournament_results
promotion_level_events
gain_assurance_scores
```

## V9.18 Fichiers supplémentaires à créer

```text
src/profitability/
  gain_assurance.py
  replicable_pnl.py
  lead_lag.py
  copy_half_life.py
  strategy_tournament.py
  promotion_ladder.py

src/wallets/
  wallet_style_classifier.py
  skill_vs_chance.py

src/entries/
  entry_planner.py
  delayed_pullback.py
  chase_detector.py

src/exits/
  profit_locking.py
  orderbook_exit.py
  cluster_exit.py
```

## V9.19 Tests supplémentaires

```text
test_gain_assurance_score_calculated
test_low_gain_assurance_blocks_testnet
test_lead_lag_positive_wallet_promoted
test_lead_lag_negative_wallet_downgraded
test_copy_half_life_blocks_stale_signal
test_replicability_ratio_low_blocks_wallet
test_wallet_style_martingale_penalized
test_wallet_style_swing_more_copiable_than_scalper_when_latency_high
test_entry_plan_refuses_chase
test_delayed_pullback_entry_created
test_profit_lock_moves_stop_after_tp1
test_crowding_blocks_late_cluster_entry
test_strategy_tournament_ranks_by_net_pnl_after_costs
test_promotion_ladder_requires_pessimistic_profit_factor
```

## V9.20 Prompt Codex V9 — “Profit Engine”

```text
Tu es Codex en mode architecte Python senior, quant researcher, trading-system engineer et auditeur sécurité.

Lis README.md et AGENTS.md entièrement.

Objectif :
construire Hyperliquid Smart-Wallet Observer comme un Profit Engine testnet/mock USDC.

Tu dois maximiser l’intelligence du système :
- découverte wallets ;
- backfill ;
- scoring skill vs chance ;
- lead-lag analysis ;
- copy half-life ;
- replicable PnL ;
- wallet style classification ;
- edge_remaining ;
- gain_assurance_score ;
- entry planner ;
- delayed pullback ;
- exit engine ;
- profit locking ;
- no-trade analytics ;
- wallet degradation ;
- strategy tournament ;
- testnet mock USDC locked.

Contraintes :
- Hyperliquid uniquement côté code.
- Polymarket uniquement comme casebook, pas de module d’exécution.
- Mainnet lecture seule seulement.
- Aucun ordre mainnet.
- Aucun retrait.
- Aucune clé privée mainnet.
- Testnet désactivé par défaut.
- Testnet seulement avec mock USDC.
- Aucun LLM dans le hot path.
- Toute décision doit être loggée.
- Tout refus doit être stocké.
- Toute entrée doit avoir un exit plan.
- Tout trade testnet doit avoir cloid + reconciliation + safety gates.

Implémente par lots :
LOT 1 — structure + config + doctor + safety-audit.
LOT 2 — REST read-only + raw storage + pagination.
LOT 3 — WebSocket market + stale guard.
LOT 4 — wallet discovery + backfill.
LOT 5 — wallet profile + style classification.
LOT 6 — skill vs chance + wallet scoring.
LOT 7 — lead-lag + copy half-life + replicable PnL.
LOT 8 — signal detection + signal scoring.
LOT 9 — edge_remaining + gain_assurance_score.
LOT 10 — entry planner + delayed pullback.
LOT 11 — exit engine + profit locking.
LOT 12 — paper pessimistic executor.
LOT 13 — no-trade analytics + wallet degradation.
LOT 14 — strategy tournament.
LOT 15 — testnet executor locked.
LOT 16 — dashboard + reports.
LOT 17 — tests complets.

Livraison :
- fichiers créés/modifiés ;
- tests exécutés ;
- commandes ;
- état des garde-fous ;
- confirmation mainnet execution impossible ;
- prochaine étape recommandée.
```


---

# SUPPLÉMENT V10 — Profit Engine, Wallet Replication Lab et Testnet Tournament

> Cette V10 ne remplace pas les sections précédentes : elle ajoute une couche d’ingénierie plus ambitieuse pour que Codex construise un logiciel capable de **maximiser l’edge mesurable en mock USDC**, en s’appuyant sur une réplication intelligente des wallets, une analyse fine du lead-lag, une simulation pessimiste, un moteur de sortie avancé et un tournoi testnet contrôlé.
>
> Périmètre inchangé : **Hyperliquid uniquement côté code**, **lecture seule sur mainnet**, **exécution uniquement en testnet/mock USDC**, **aucune seed phrase**, **aucun retrait**, **aucune clé mainnet dans le projet**.

## V10.1 Idée centrale : ne pas copier le trade, copier l’avantage

Le logiciel ne doit pas chercher à reproduire mécaniquement chaque ordre d’un wallet. Il doit chercher à reproduire l’**avantage exploitable restant** après coûts.

```text
Action du wallet leader
→ délai de détection
→ mouvement déjà consommé
→ profondeur restante du carnet
→ slippage estimé
→ frais
→ probabilité de sortie propre
→ edge restant
→ décision
```

La décision correcte n’est donc pas seulement :

```text
Le wallet est bon → copier
```

mais plutôt :

```text
Le wallet est bon
+ ce trade est encore frais
+ le prix n’a pas trop bougé
+ le carnet permet l’entrée et la sortie
+ la sortie est planifiée
+ l’edge restant est supérieur aux coûts
+ le paper/testnet prouve que cette classe de signal fonctionne
→ testnet mock USDC autorisé
```

## V10.2 Modèle complet du “logiciel miracle” transposable à Hyperliquid

La meilleure reconstruction exploitable pour notre logiciel est un système en **7 moteurs**.

### Moteur 1 — Wallet Discovery Engine

Objectif : trouver beaucoup de wallets candidats, puis les réduire brutalement.

Sources candidates :

```text
- leaderboard Hyperliquid ;
- wallets repérés manuellement ;
- wallets provenant de rapports ;
- wallets découverts via gros PnL ;
- wallets actifs sur marchés liquides ;
- wallets qui apparaissent dans plusieurs fenêtres temporelles ;
- wallets observés dans des clusters de mouvement.
```

Sortie attendue :

```text
wallet_candidates(address, source, first_seen, reason, confidence)
```

### Moteur 2 — Wallet Backfill Engine

Objectif : récupérer suffisamment de données avant de juger.

À récupérer :

```text
- clearinghouseState ;
- openOrders ;
- frontendOpenOrders ;
- userFills ;
- userFillsByTime ;
- historicalOrders ;
- portfolio si utile ;
- userFunding ;
- snapshots réguliers ;
- l2Book des actifs tradés ;
- allMids ;
- candles.
```

Règle : un wallet sans historique suffisant reste `OBSERVE_ONLY`.

### Moteur 3 — Skill Detection Engine

Objectif : distinguer les wallets compétents des wallets chanceux.

Tests obligatoires :

```text
sample_size_check
one_big_win_check
pnl_concentration_check
drawdown_check
loss_streak_check
wilson_lower_bound_check
bayesian_shrinkage_check
bootstrap_stability_check
regime_split_check
asset_concentration_check
style_drift_check
```

### Moteur 4 — Signal Extraction Engine

Objectif : transformer l’activité du wallet en signaux normalisés.

Événements :

```text
LEADER_OPEN_LONG
LEADER_OPEN_SHORT
LEADER_ADD_LONG
LEADER_ADD_SHORT
LEADER_REDUCE_LONG
LEADER_REDUCE_SHORT
LEADER_CLOSE_LONG
LEADER_CLOSE_SHORT
LEADER_FLIP_LONG_TO_SHORT
LEADER_FLIP_SHORT_TO_LONG
LEADER_CANCELS_ORDERS
LEADER_PLACES_RESTING_ORDER
LEADER_AGGRESSIVE_ENTRY
LEADER_PASSIVE_ENTRY
```

### Moteur 5 — Edge Remaining Engine

Objectif : ne garder que les signaux où l’edge restant est suffisant.

```text
edge_remaining_bps =
  expected_move_bps
+ leader_quality_bonus_bps
+ cluster_confirmation_bps
+ orderbook_confirmation_bps
+ regime_bonus_bps
- fee_bps
- spread_bps
- slippage_bps
- latency_decay_bps
- adverse_selection_bps
- exit_cost_bps
```

### Moteur 6 — Entry/Exit Planner

Objectif : décider comment entrer et surtout comment sortir.

Entrées possibles :

```text
ENTRY_IMMEDIATE_IOC
ENTRY_PASSIVE_ALO
ENTRY_DELAYED_PULLBACK
ENTRY_CONFIRM_BREAKOUT
ENTRY_SKIP_CHASE
ENTRY_SKIP_THIN_BOOK
```

Sorties possibles :

```text
EXIT_PARTIAL_TP_1
EXIT_PARTIAL_TP_2
EXIT_TRAILING_STOP
EXIT_LEADER_REDUCE
EXIT_LEADER_CLOSE
EXIT_CLUSTER_REVERSAL
EXIT_EDGE_DECAY
EXIT_TIME_STOP
EXIT_ORDERBOOK_REVERSAL
EXIT_HARD_STOP
EXIT_KILL_SWITCH
```

### Moteur 7 — Learning Loop

Objectif : transformer les résultats paper/testnet en amélioration.

```text
paper_result
→ compare expected vs realized
→ update copy_degradation
→ update exit_quality
→ update wallet_degradation
→ update signal_thresholds
→ update no_trade_precision
→ promote/demote wallet
```

## V10.3 Gain Assurance Score V10

Le `Gain Assurance Score` est un score interne pour classer les signaux les plus prometteurs en **simulation et testnet mock USDC**.

```text
gain_assurance_score_v10 =
  0.16 * wallet_skill_score
+ 0.13 * lead_lag_score
+ 0.12 * edge_remaining_score
+ 0.10 * liquidity_score
+ 0.09 * low_slippage_score
+ 0.08 * exit_plan_score
+ 0.08 * copy_half_life_score
+ 0.07 * cluster_quality_score
+ 0.06 * regime_alignment_score
+ 0.06 * paper_similarity_score
+ 0.05 * testnet_replay_score
- 0.10 * crowding_penalty
- 0.10 * toxicity_penalty
- 0.08 * uncertainty_penalty
```

Interprétation :

```text
0-49   = IGNORE
50-64  = OBSERVE_ONLY
65-74  = PAPER_CANDIDATE
75-84  = PAPER_TRADE
85-91  = TESTNET_SMALL_CANDIDATE
92+    = TESTNET_PRIORITY_SIGNAL
```

## V10.4 Lead-Lag Analysis

Le bot doit mesurer si un wallet agit **avant** le mouvement ou s’il arrive déjà trop tard.

### Mesure simple

Pour chaque action du wallet :

```text
leader_event_time = t0
price_at_t0 = p0
price_after_1s = p1
price_after_5s = p5
price_after_30s = p30
price_after_2m = p2m
```

Score :

```text
lead_lag_edge_bps_5s = direction * (p5 - p0) / p0 * 10000
lead_lag_edge_bps_30s = direction * (p30 - p0) / p0 * 10000
lead_lag_edge_bps_2m = direction * (p2m - p0) / p0 * 10000
```

Un wallet intéressant doit montrer un edge après son action, pas seulement un PnL historique.

### Table à créer

```text
wallet_lead_lag_metrics(
  wallet,
  coin,
  window_ms,
  events_count,
  avg_edge_bps,
  median_edge_bps,
  positive_rate,
  p25_edge_bps,
  p75_edge_bps,
  last_updated
)
```

## V10.5 Copy Half-Life

Le `copy_half_life_ms` mesure combien de temps un signal reste exploitable.

```text
edge_after_delay = edge_initial * exp(-delay_ms / copy_half_life_ms)
```

Le bot doit calculer un half-life par wallet et par type de marché :

```text
half_life_by_wallet
half_life_by_coin
half_life_by_volatility_regime
half_life_by_signal_type
```

Règles :

```text
si half_life très court → privilégier observation ou delayed copy très stricte
si half_life moyen → paper/testnet possible avec latence mesurée
si half_life long → meilleur candidat à la réplication
```

## V10.6 Replicable PnL

Le PnL d’un wallet n’est pas le PnL que notre bot peut reproduire. Il faut donc calculer :

```text
leader_pnl = PnL réel du wallet leader
replicable_pnl = PnL estimé si notre bot l’avait suivi après délai + coûts
replication_ratio = replicable_pnl / leader_pnl
```

Un excellent wallet avec `replication_ratio` faible n’est pas utile.

Table :

```text
replicable_pnl_metrics(
  wallet,
  coin,
  window,
  leader_pnl,
  simulated_copy_pnl,
  replication_ratio,
  avg_entry_delay_ms,
  avg_copy_degradation_bps,
  avg_exit_degradation_bps
)
```

## V10.7 Copy Degradation avancée

```text
copy_degradation_bps = direction * (copy_entry_price - leader_entry_price) / leader_entry_price * 10000
```

Pour un long :

```text
si notre prix d’entrée est plus haut que le leader → dégradation
```

Pour un short :

```text
si notre prix d’entrée est plus bas que le leader → dégradation
```

Le bot doit suivre :

```text
entry_copy_degradation_bps
exit_copy_degradation_bps
total_copy_degradation_bps
copy_degradation_by_wallet
copy_degradation_by_coin
copy_degradation_by_signal_type
copy_degradation_by_time_of_day
```

## V10.8 Styles de wallets et stratégie adaptée

Codex doit classifier les wallets par style, car on ne copie pas un scalper comme un swing trader.

```text
SCALPER_FAST
MOMENTUM_BREAKOUT
MEAN_REVERSION
SWING_TREND
FUNDING_CARRY
HEDGER
MARTINGALE_RISK
ONE_BIG_WIN
ILLQUIDITY_HUNTER
NEWS_REACTIVE
UNKNOWN
```

Règles :

```text
SCALPER_FAST → exige half-life long enough + WS premium + faible latence
MOMENTUM_BREAKOUT → entrée possible seulement si not chasing
MEAN_REVERSION → delayed pullback préféré
SWING_TREND → signal moins sensible à la milliseconde
HEDGER → OBSERVE_ONLY sauf preuve que la jambe visible suffit
MARTINGALE_RISK → blacklist ou paper only
ONE_BIG_WIN → pas de promotion
ILLQUIDITY_HUNTER → refuser si book trop fin
```

## V10.9 Entry Optimizer

Le bot doit tester plusieurs modes d’entrée en paper trading.

```text
entry_modes:
  - immediate_ioc
  - passive_alo
  - delayed_pullback
  - confirm_breakout
  - midpoint_limit
  - skip_if_chase
```

### Choix initial recommandé

```text
si signal très frais + book épais + edge fort → immediate_ioc testnet possible
si signal frais mais prix déjà déplacé → delayed_pullback
si breakout avec confirmation carnet → confirm_breakout
si spread large → passive_alo ou skip
si liquidité faible → skip
```

## V10.10 Exit Optimizer

Le bot doit apprendre quelle sortie marche le mieux par style de wallet.

```text
exit_modes:
  - fixed_tp_sl
  - partial_tp_then_trailing
  - leader_reduce_mirror
  - leader_close_mirror
  - edge_decay_exit
  - time_based_exit
  - orderbook_reversal_exit
```

Métriques :

```text
exit_capture_ratio = realized_profit / MFE
profit_giveback_bps = MFE_bps - realized_profit_bps
stop_efficiency = realized_loss_bps / MAE_bps
```

Objectif : capturer une grande part du MFE et éviter de rendre trop de profit.

## V10.11 Testnet Tournament Mode

Pour viser les meilleurs gains en mock USDC, le bot doit comparer plusieurs variantes de stratégie.

Exemples de variantes :

```text
strategy_A_immediate_ioc
strategy_B_delayed_pullback
strategy_C_confirm_breakout
strategy_D_partial_tp_fast
strategy_E_trailing_wide
strategy_F_cluster_confirmed_only
strategy_G_high_edge_only
```

Chaque variante reçoit un capital mock séparé :

```text
mock_bankroll_per_strategy = 1000 USDC fictif interne ou allocation testnet simulée
```

Métriques de classement :

```text
net_pnl_mock
profit_factor
expectancy_bps
max_drawdown_bps
edge_realization_ratio
exit_capture_ratio
copy_degradation
no_trade_precision
stability_score
```

Le vainqueur n’est pas forcément celui qui gagne le plus : c’est celui qui gagne avec le meilleur ratio performance/stabilité.

## V10.12 Portfolio Allocator mock USDC

Même en testnet, il faut prévoir une logique d’allocation.

```text
allocation_score =
  0.35 * strategy_stability_score
+ 0.25 * edge_realization_score
+ 0.20 * drawdown_control_score
+ 0.20 * recent_performance_score
```

Règles :

```text
ne jamais allouer tout le mock capital à une seule stratégie
réduire allocation après drawdown
augmenter allocation après stabilité multi-scenarios
mettre en cooldown après erreurs de réconciliation
```

## V10.13 Market Regime Engine

Le bot doit détecter le régime de marché avant d’interpréter un signal wallet.

Régimes :

```text
TREND_UP
TREND_DOWN
RANGE_LOW_VOL
RANGE_HIGH_VOL
BREAKOUT
LIQUIDATION_CASCADE
THIN_LIQUIDITY
FUNDING_STRESS
UNKNOWN
```

Features :

```text
realized_volatility
candle_slope
volume_spike
spread_bps
orderbook_depth
orderbook_imbalance
open_interest_context si disponible
funding_context
recent_liquidation_proxy si disponible
```

Règle : un signal peut être bon dans un régime et mauvais dans un autre.

## V10.14 Truth Hierarchy des données

Codex doit respecter cette hiérarchie :

```text
1. Raw API/WS Hyperliquid stocké localement
2. État reconstruit localement à partir du raw
3. Métriques calculées par le bot
4. Sources externes de découverte
5. Threads X / récits viraux / captures de PnL
```

Aucun signal testnet ne doit dépendre uniquement d’une source de niveau 4 ou 5.

## V10.15 Event Sourcing obligatoire

Pour rendre les backtests/replays fiables, le logiciel doit conserver un journal append-only.

```text
raw_events(
  id,
  source,
  event_type,
  wallet,
  coin,
  exchange_ts,
  local_received_ts,
  payload_json,
  payload_hash
)
```

Tous les états normalisés doivent pouvoir être reconstruits depuis `raw_events`.

## V10.16 Contrôles anti-overfitting orientés performance

Codex doit empêcher le bot de “trouver” une stratégie qui marche seulement dans l’historique.

Contrôles :

```text
walk_forward_split
out_of_sample_period
bootstrap_resampling
parameter_sensitivity_grid
deflated_sharpe_like_check
minimum_trade_count
regime_split_validation
wallet_holdout_set
coin_holdout_set
```

Principe : si une stratégie ne marche que sur un wallet ou un actif, elle reste en exploration.

## V10.17 Paramètres YAML V10

```yaml
profit_engine_v10:
  enabled: true
  execution_scope: "mock_usdc_testnet_only"
  min_gain_assurance_score: 85
  min_edge_remaining_bps: 8
  elite_edge_remaining_bps: 25
  min_replication_ratio: 0.35
  max_entry_copy_degradation_bps: 7
  max_total_copy_degradation_bps: 12
  min_exit_capture_ratio: 0.45
  max_profit_giveback_bps: 15
  max_signal_age_ms: 2500
  min_copy_half_life_ms: 1200
  require_lead_lag_positive: true
  require_exit_plan: true
  require_market_regime_alignment: true

wallet_selection_v10:
  min_trades: 75
  min_active_days: 7
  max_top_trade_pnl_share: 0.30
  max_single_day_pnl_share: 0.45
  max_asset_pnl_concentration: 0.60
  min_wilson_lower_bound: 0.48
  blacklist_martingale: true
  blacklist_one_big_win: true
  blacklist_illiquid_only_wallets: true

strategy_tournament_v10:
  enabled_in_paper: true
  enabled_in_testnet: true
  compare_entry_modes: true
  compare_exit_modes: true
  rank_by_stability_adjusted_pnl: true
  require_positive_in_stress: true
```

## V10.18 Nouveaux fichiers à demander à Codex

```text
src/profit_engine/
  gain_assurance_score.py
  lead_lag_analysis.py
  copy_half_life.py
  replicable_pnl.py
  entry_optimizer.py
  exit_optimizer.py
  market_regime_engine.py
  strategy_tournament.py
  portfolio_allocator.py

src/event_sourcing/
  raw_event_store.py
  replay_from_events.py
  payload_hashing.py

src/validation/
  anti_overfit.py
  wallet_holdout.py
  coin_holdout.py
  parameter_sensitivity.py
```

## V10.19 Nouvelles tables DB

```text
gain_assurance_scores
lead_lag_metrics
copy_half_life_metrics
replicable_pnl_metrics
entry_optimization_results
exit_optimization_results
strategy_tournament_runs
strategy_tournament_results
portfolio_allocation_snapshots
market_regime_snapshots
raw_events
parameter_sensitivity_results
wallet_holdout_results
coin_holdout_results
```

## V10.20 Tests V10 obligatoires

```text
test_gain_assurance_score_orders_candidates
test_lead_lag_positive_required
test_copy_half_life_too_short_blocks_testnet
test_replicable_pnl_low_blocks_promotion
test_entry_copy_degradation_calculated_long
test_entry_copy_degradation_calculated_short
test_exit_capture_ratio_calculated
test_profit_giveback_penalized
test_market_regime_mismatch_rejected
test_strategy_tournament_ranks_by_stability_adjusted_pnl
test_portfolio_allocator_reduces_after_drawdown
test_raw_events_append_only
test_replay_reconstructs_state_from_raw_events
test_external_sources_never_trigger_testnet_alone
test_wallet_holdout_validation_required
test_parameter_sensitivity_detects_fragile_strategy
```

## V10.21 Prompt Codex V10

```text
Lis README.md et AGENTS.md intégralement.

Tu dois construire un système Hyperliquid mock-USDC-first orienté Profit Engine V10.

Objectif : maximiser l’edge mesurable en paper/testnet par :
- meilleure sélection de wallets ;
- lead-lag analysis ;
- copy half-life ;
- replicable PnL ;
- gain assurance score ;
- edge remaining ;
- entry optimizer ;
- exit optimizer ;
- market regime engine ;
- strategy tournament ;
- event sourcing ;
- anti-overfitting.

Tu ne dois pas coder un copy bot naïf.
Tu dois coder une architecture mesurable, testable, replayable et sécurisée.

Contraintes :
- Hyperliquid uniquement ;
- mainnet lecture seule ;
- testnet/mock USDC uniquement pour exécution ;
- pas de seed ;
- pas de clé mainnet ;
- pas de retrait ;
- pas de décision LLM dans le hot path ;
- chaque signal doit être mesuré avant action ;
- chaque action testnet doit avoir cloid + scheduleCancel + reconciliation + exit plan.

Lots :
1. Event sourcing + DB schema.
2. REST/WS collectors.
3. Wallet discovery/backfill.
4. Wallet scoring + skill vs chance.
5. Lead-lag + copy half-life + replicable PnL.
6. Signal engine + gain assurance score.
7. Edge remaining + entry optimizer.
8. Exit optimizer.
9. Paper pessimistic + strategy tournament.
10. Testnet executor locked.
11. Dashboard/reporting.
12. Full pytest + safety-audit.

À la fin de chaque lot :
- fichiers modifiés ;
- tests ajoutés ;
- commandes exécutées ;
- statut sécurité ;
- prochaines étapes.
```
