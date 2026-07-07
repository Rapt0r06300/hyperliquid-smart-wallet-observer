# HyperSmart - Audit PnL négatif simulation du 2026-06-26

Ce rapport fige la passe Codex du 2026-06-26 sur les causes du PnL négatif observé dans la simulation locale Hyperliquid. Il est volontairement factuel : aucune promesse de gain, aucune donnée inventée, aucun ordre réel. La simulation reste `LOCAL_RESEARCH_SIMULATION_ONLY`.

## Sources analysées

- Dossier de logs lu : `C:\Users\flo\Desktop\Projet invest\logs\logs à envoyer`
- Commande principale :
  - `python -m hl_observer.cli simulation-loss-report --from-logs "C:\Users\flo\Desktop\Projet invest\logs\logs à envoyer"`
- Diagnostics complémentaires :
  - `python -m hl_observer.cli action-loss-diagnostics --from-logs "C:\Users\flo\Desktop\Projet invest\logs\logs à envoyer"`
  - `python -m hl_observer.cli coin-loss-diagnostics --from-logs "C:\Users\flo\Desktop\Projet invest\logs\logs à envoyer"`

## Résultat des logs avant correction

| Mesure | Valeur |
|---|---:|
| Événements analysés | 1000 |
| Événements acceptés | 85 |
| Événements refusés | 915 |
| Événements positifs | 20 |
| Événements négatifs | 65 |
| PnL net estimé | -5.681659 USDC |
| Frais simulés | 1.648891 USDC |
| Dégradation moyenne de copie | 22.971701 bps |
| Dégradation maximale de copie | 142.199446 bps |

Les logs montrent que le problème n'est pas seulement "pas assez de wallets". Les pertes viennent surtout de signaux trop vieux, de frais trop élevés par rapport au petit edge, de liquidité insuffisante, de dégradation de copie, puis de fermetures paper qui matérialisent ces entrées faibles.

## Attribution PnL par action

| Action paper | PnL net |
|---|---:|
| `PAPER_CLOSE_REPLAYED` | -4.532966 |
| `PAPER_CONSENSUS_ENTRY_REPLAYED` | -0.591991 |
| `PAPER_CONSENSUS_REDUCE_REPLAYED` | -0.363001 |
| `PAPER_CONSENSUS_ADD_REPLAYED` | -0.150000 |
| `PAPER_CONSENSUS_CLOSE_REPLAYED` | -0.043701 |
| `NO_TRADE` | 0.000000 |

Lecture : la perte principale est matérialisée au moment des closes. Cela indique que les entrées acceptées étaient trop faibles ou trop tardives, puis que la logique de sortie n'a pas assez protégé la session. La correction doit donc agir avant l'entrée, pendant la position et au moment du close.

## Attribution PnL par coin

| Coin | PnL net |
|---|---:|
| ETH | -1.800473 |
| AAVE | -1.318115 |
| BNB | -1.110285 |
| BTC | -0.850429 |
| HYPE | -0.602357 |

Les pertes sont concentrées sur quelques marchés. La session doit donc ralentir ou exiger un edge beaucoup plus fort sur les coins qui viennent de perdre, au lieu de reprendre mécaniquement le même flux.

## Principales raisons de refus

- `EDGE_REMAINING_TOO_LOW|LIQUIDITY_TOO_LOW|SINGLE_WALLET_EDGE_TOO_LOW`
- `EDGE_REMAINING_TOO_LOW|LIQUIDITY_TOO_LOW|SINGLE_WALLET_EDGE_TOO_LOW|STALE_SIGNAL`
- `LIQUIDITY_TOO_LOW`
- `EDGE_REMAINING_TOO_LOW|STALE_SIGNAL`
- `EDGE_REMAINING_TOO_LOW|SINGLE_WALLET_EDGE_TOO_LOW`
- `COIN_SESSION_LOSS_COOLDOWN`
- `COPY_DEGRADATION_TOO_HIGH`
- `PRICE_DEVIATION_TOO_HIGH`

Lecture : le moteur voyait beaucoup de candidats, mais la majorité était soit trop tardive, soit trop peu liquide, soit déjà mangée par les coûts. Il ne faut pas "forcer" ces signaux : il faut accélérer la fraîcheur, réduire l'admission des entrées faibles, journaliser les SL/TP, et calibrer la sortie.

## Causes racines retenues

1. `LATE_ENTRY` : la fenêtre live était trop large côté `userFills`, et le poller immobilisait parfois la boucle sur un scan public long.
2. `FEES_DRAG` : les frais simulent une friction réelle qui mange les petits edges.
3. `COPY_DEGRADATION_TOO_HIGH` : retard, spread, slippage et liquidité transforment un edge brut en edge net insuffisant.
4. `EDGE_MODEL_TOO_OPTIMISTIC` : certains signaux paraissaient acceptables avant coûts, mais finissaient négatifs après frais et dégradation.
5. `NEGATIVE_EVENTS_DOMINATE` : la session acceptait encore trop de cas dont le risque n'était pas compensé.
6. `PAPER_CLOSE_REPLAYED` déficitaire : les sorties matérialisent beaucoup de pertes; il faut de meilleurs garde-fous positionnels.

## Corrections appliquées

### Fraîcheur du scan

- `tools/start_hypersmart_simulation.ps1`
  - `PublicTradeScanSeconds` abaissé de 45 s à 8 s.
  - `UserFillsMaxLiveAgeMs` abaissé de 120000 ms à 20000 ms.
- `LANCER_HYPERSMART.cmd`
  - limites de simulation réalignées avec le runtime : 60 positions max, 40 USDT par position, 1200 USDT d'exposition paper maximale.

Effet attendu : cycles plus courts, moins d'entrées déjà périmées, UI moins bloquée par de longs scans. Cela ne crée pas de PnL artificiel; cela empêche surtout d'accepter des signaux arrivés trop tard.

### Admission des fills

- `src/hl_observer/signals/fill_admission.py`
  - Ajout de la raison `STALE_SIGNAL`.
  - Les entrées trop vieilles sont refusées plus tôt.
  - Les sorties restent possibles si une position paper correspondante existe.

Effet attendu : moins de "vieilles entrées" ouvertes en paper, sans bloquer les closes/reduces nécessaires pour gérer les positions déjà ouvertes.

### Seuils de simulation calibrés

- `src/hl_observer/simulation/live_filters.py`
- `src/hl_observer/copying/realtime_magic_score.py`
- `tools/start_hypersmart_simulation.ps1`

Réglages alignés :

- âge signal max : 15000 ms
- edge minimum : 15 bps
- single-wallet edge minimum : 28 bps
- liquidité minimum : 0.22
- dégradation copie max : 40 bps

Effet attendu : moins de starvation totale, mais refus maintenu pour les signaux trop faibles après coûts.

### Gate V12 corrigée

- `src/hl_observer/ui/routes.py`
  - La gate V12 reçoit maintenant l'edge net restant, pas l'edge brut du leader.
  - Correction d'un mauvais attribut de seuil.

Effet attendu : la décision paper se base sur ce qu'il reste réellement après coûts, pas sur une estimation trop optimiste.

### Cooldown par session amélioré

- `src/hl_observer/ui/routes.py`
  - Perte sévère coin/wallet : cooldown strict.
  - Perte modérée coin/wallet : le moteur peut continuer seulement avec un edge plus fort.

Effet attendu : éviter de reprendre trop vite sur un coin ou wallet qui vient de pénaliser la session, tout en permettant un très fort consensus de passer.

### SL/TP et journalisation

- `src/hl_observer/paper_trading/sltp_runtime.py`
  - Les closes SL/TP écrivent maintenant :
    - `sltp_pnl_bps`
    - `sltp_favorable_excursion_bps`
    - `sltp_take_profit_bps`
    - `sltp_stop_loss_bps`
    - `sltp_trailing_stop_bps`

Effet attendu : les prochains logs permettront de savoir si le TP est trop loin, le SL trop large, ou le trailing mal calibré.

### Proxies et limites

- `src/hl_observer/collection/proxy_pool.py`
- `src/hl_observer/collection/weight_budgeter.py`
- `src/hl_observer/scanner/throughput_planner.py`
- `src/hl_observer/cli.py`

Le mode "bypass" ne force plus les budgets. Les demandes de contournement sont refusées explicitement et orientées vers :

- sticky sharding sain;
- WebSocket public read-only;
- cache local;
- rotation bornée;
- backoff et source health.

Effet attendu : meilleure stabilité et moins de données dégradées par des erreurs/rate-limits. Cela respecte la contrainte read-only locale et évite de masquer les vrais problèmes de fraîcheur.

## Tests lancés

Commande :

```powershell
python -m pytest -q tests/test_hypersmart_single_launcher.py tests/test_v9_proxy_pool_safe_sharding.py tests/test_hypersmart_v9_collection_budget.py tests/test_copy_cli_and_safety.py tests/test_scanner_fast_scan.py tests/test_simulation_live_filters.py tests/test_v9_fill_admission.py tests/test_realtime_magic_score.py tests/test_v9_sltp_runtime.py tests/test_ui_simulation_persistence.py
```

Résultat :

- `123 passed`
- `4704 warnings` FastAPI `DeprecationWarning`, non bloquants pour cette passe.

Suite complète relancée après correction des raccords :

```powershell
python -m pytest -q
```

Résultat :

- `1870 passed`
- `16330 warnings` principalement FastAPI `DeprecationWarning`, non bloquants pour cette passe.

Garde-fous relancés :

- `python -m hyper_smart_observer.app.main --safety-check` : OK
- `python -m hyper_smart_observer.app.main --audit-safety` : OK

## Ce que cette passe ne peut pas garantir

- Elle ne garantit pas un PnL positif.
- Elle ne ment pas au graphe.
- Elle ne fabrique pas de fausses positions.
- Elle ne crée aucun ordre réel.
- Elle ne contourne pas les limites réseau.

Le prochain lancement doit produire de nouveaux logs frais. Les anciens logs resteront utiles comme baseline négative, mais il ne faut pas juger les corrections uniquement sur ce fichier historique.

## Prochaine vérification obligatoire

1. Fermer proprement le serveur existant avec `Q` dans `LANCER_HYPERSMART`.
2. Relancer `LANCER_HYPERSMART.cmd`.
3. Laisser tourner au moins 10 à 20 minutes.
4. Relire :
   - `C:\Users\flo\Desktop\Projet invest\logs\logs à envoyer\simulation_decisions_latest.jsonl`
   - `C:\Users\flo\Desktop\Projet invest\logs\logs à envoyer\simulation_snapshot_latest.json`
   - `C:\Users\flo\Desktop\Projet invest\logs\logs à envoyer\simulation_resume_pour_chatgpt.md`
5. Relancer :

```powershell
python -m hl_observer.cli simulation-loss-report --from-logs "C:\Users\flo\Desktop\Projet invest\logs\logs à envoyer"
```

## NEXT CODEX OBJECTIVE

Reprendre après un nouveau run live frais et comparer :

- nombre d'entrées acceptées;
- âge médian des signaux;
- part de `STALE_SIGNAL`;
- PnL net par coin;
- closes déclenchées par SL/TP;
- PnL des closes vs entrées;
- dégradation moyenne de copie;
- edge net moyen des entrées acceptées.

Si le PnL reste négatif, la prochaine correction doit cibler en priorité :

1. TP/SL/trailing par régime de marché;
2. blocage temporaire des coins qui perdent pendant la session;
3. recalibrage du sizing par edge net;
4. coût d'entrée minimum en dollars, pas seulement en bps;
5. branchement complet des features L2/candles dans la gate V9 avant de la rendre autoritaire dans le launcher.
