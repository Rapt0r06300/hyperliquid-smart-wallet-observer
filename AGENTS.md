# AGENTS.md — dYdX Smart-Wallet Observer

Ce fichier définit les règles obligatoires pour tout agent IA ou outil automatisé travaillant sur ce dépôt.

Le projet est désormais centré sur **dYdX v4 uniquement**.

---

## 1. Mission du projet

Construire un logiciel local qui :

- observe des wallets/subaccounts dYdX v4 ;
- collecte des fills publics et données de marché en lecture seule ;
- reconstruit les événements OPEN / ADD / REDUCE / CLOSE ;
- score les comptes, signaux et contextes de marché ;
- refuse par défaut les signaux risqués ou non mesurables ;
- simule localement en paper ;
- produit des rapports clairs ;
- interdit toute exécution réelle.

Le projet est un outil R&D local de simulation, pas un service financier et pas un bot réel.

---

## 2. Règles absolues

Un agent ne doit jamais :

```text
- demander une seed phrase ;
- demander une clé privée ;
- écrire une clé privée dans un fichier ;
- stocker un secret en base ;
- logger un secret ;
- coder une fonctionnalité de retrait ;
- activer une exécution réelle ;
- contourner le risk engine ;
- désactiver les garde-fous ;
- supprimer les tests de sécurité ;
- placer un ordre réel ;
- promettre un gain ;
- présenter un wallet comme magique ;
- mettre un LLM dans le hot path décisionnel.
```

Doctrine :

```text
READ ONLY
PAPER ONLY
SIMULATION ONLY
DENY BY DEFAULT
SCORE IS NOT SIGNAL
PAPER TRADE IS NOT ORDER
HISTORICAL PNL IS NOT FUTURE PROFIT
```

---

## 3. Architecture prioritaire

Le code dYdX doit rester dans :

```text
hyper_smart_observer/dydx_v4/
```

Modules importants :

```text
config.py
live_observer.py
fast_scanner.py
fast_scan_integration.py
wallet_discovery.py
wallet_harvester.py
leaderboard.py
selection.py
signals.py
edge_calculator.py
consensus.py
cluster_detector.py
market_flow.py
adaptive_exits.py
risk_policy.py
backtest.py
no_trade.py
storage.py
cli.py
```

Ne pas ajouter de nouvelle plateforme sans demande explicite.
Ne pas réintroduire l'ancien périmètre.

---

## 4. Scanners et moteur

Les scanners doivent :

- respecter les limites publiques ;
- rester read-only ;
- utiliser des fenêtres bornées ;
- dédupliquer les fills ;
- mesurer l'âge réel du signal ;
- refuser les données incomplètes ;
- journaliser les `NO_TRADE` ;
- éviter les boucles infinies non bornées ;
- être testables sans réseau.

Le moteur doit :

- pénaliser one-big-win ;
- pénaliser drawdown élevé ;
- vérifier la fraîcheur ;
- vérifier la liquidité ;
- vérifier les coûts de copie ;
- vérifier le consensus ;
- refuser les signaux non mesurables ;
- ne jamais transformer un score en ordre.

---

## 5. Stockage et rapports

Stocker raw JSON + données normalisées quand utile.

Éléments importants :

```text
wallets
subaccounts
fills
position_events
signals
rejected_signals
paper_trades
risk_events
no_trade_decisions
api_health
websocket_events
backtest_runs
reports
```

Chaque refus doit expliquer :

- ce qui a été observé ;
- pourquoi ce n'est pas simulable ;
- quelle donnée manque ;
- quelle action suivante est recommandée.

---

## 6. Tests

Avant de considérer une modification terminée :

```powershell
python -m pytest -q tests/dydx_v4
python -m pytest -q
```

Si la suite complète échoue à cause d'un ancien module non encore migré, documenter précisément l'échec et ne pas prétendre que tout est vert.

---

## 7. Nettoyage du dépôt

Le dépôt doit rester propre :

- supprimer les docs obsolètes ;
- supprimer les modules spécifiques à l'ancien périmètre ;
- conserver seulement les modules génériques utiles ;
- éviter les noms publics incohérents ;
- ne pas casser volontairement la couche dYdX ;
- ne pas supprimer les garde-fous.

Priorité actuelle : dYdX-only, simulation-only, GitHub propre.
