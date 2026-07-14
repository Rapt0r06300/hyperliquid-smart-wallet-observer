# HyperSmart - mega rapport de reprise PnL pour Claude

Date : 2026-07-12  
Audience : Claude Code / ingenieur Python senior  
Projet : `C:\Users\flo\Desktop\Projet invest`  
Runtime officiel : `src/hl_observer`  
Mode autorise : Hyperliquid read-only + simulation paper locale

## Resume technique

Le PnL negatif ne vient pas d'un seul mauvais seuil. L'audit prouve quatre problemes cumules :

1. la strategie historique de copy-trading ne possede pas encore d'edge net positif hors
   echantillon ;
2. l'ancien runtime pouvait empiler des positions de 500 USDT et concentrer presque tout le risque
   dans le meme sens ;
3. les frais et les timeouts transforment plusieurs petits gains bruts en pertes nettes ;
4. les anciennes surfaces snapshot, ledger et logs ne se reconcilient pas toujours, donc certains
   PnL historiques ne sont pas assez fiables pour calibrer le moteur.

Une cinquieme anomalie est maintenant confirmee : le bus GitHub ecrit des evenements
`PAPER_ORDER_ACCEPTED` qui ne sont que des evaluations sans taille, sans sens et sans position. Cela
pollue l'UI et la notion de trade accepte.

## Decision produit definitive : plus aucun bus GitHub

Le bus GitHub est termine. Il ne doit plus :

- etre execute dans le hot path ;
- creer une decision ou une position paper ;
- ecrire dans le ledger comptable ;
- incrementer les compteurs de trades ;
- apparaitre comme moteur actif dans l'ecran principal ;
- fournir un score, un ordre paper ou un motif de sortie.

Les clones sous `runtime/research/github_repos_v24` peuvent rester intacts comme bibliotheque de
recherche hors runtime. Les idees utiles doivent etre distillees manuellement dans des modules
HyperSmart uniques, mesures et testes. Aucun code upstream ne doit etre lance comme moteur autonome.

Architecture cible unique :

```text
Hyperliquid read-only
  -> normalisation et provenance
  -> position deltas frais
  -> features marche mesurees
  -> edge empirique hors echantillon
  -> RiskEngine canonique
  -> PaperEngine canonique
  -> ledger canonique
  -> PnL/equity/drawdown
  -> dashboard et logs
```

## Ce que la session active prouve

Apres relance, `/api/simulation/overview` et `/api/simulation/status` repondent. Le portefeuille est
plat et coherent :

- equity : `1000.0 USDT` ;
- PnL realise : `0.0` ;
- PnL latent : `0.0` ;
- positions : `0` ;
- trades fermes : `0`.

Le ledger visible contient pourtant `171` evenements, tous `ENGINE_EVALUATION`. Plusieurs lignes ont :

```text
decision=PAPER_ORDER_ACCEPTED
reason=PROFILE_PRODUCED_ACCEPTED_LOCAL_PAPER_ORDER
paper_action_type=ENGINE_EVALUATION
copied_notional_usdt=0
leader_side=NONE
execution=forbidden
```

Conclusion : ces lignes ne sont pas des trades paper. Le runtime et l'UI utilisent un vocabulaire
trompeur. Elles doivent etre retirees de la chaine comptable, pas simplement masquees visuellement.

## Sources auditees

Sources principales :

- `logs/logs a envoyer/_archives/session_20260711_161654` ;
- `logs/logs a envoyer/_archives/session_20260711_204658` ;
- les autres archives du 8 au 12 juillet ;
- `simulation_snapshot_latest.json` ;
- `simulation_pnl_ledger_latest.jsonl` ;
- `simulation_decisions_latest.jsonl` ;
- `/api/simulation/overview` ;
- `/api/simulation/status` ;
- `docs/audit/AUTOPSIE_DU_PNL.md` ;
- `docs/audit/PREUVE_ABSENCE_EDGE_COPYTRADING.md` ;
- les rapports sous `runtime/reports/`.

## Historique des sessions : le probleme est recurrent

| Session | PnL snapshot | Equity | Trades fermes snapshot | Lignes ledger |
|---|---:|---:|---:|---:|
| `session_20260712_102708` | 0.000000 | 1000.000000 | 0 | 0 |
| `session_20260711_205714` | 0.000000 | 1000.000000 | 0 | 0 |
| `session_20260711_204658` | -12.258191 | 987.741809 | 15 | 35 |
| `session_20260711_185603` | -31.224617 | 968.775383 | 16 | 37 |
| `session_20260711_161654` | -63.682548 | 936.317452 | 22 | 19 |
| `session_20260709_130528` | -72.799976 | 927.200024 | 53 | 16 |
| `session_20260708_201955` | -8.837048 | 991.162952 | 5 | 20 |
| `session_20260708_183641` | +5.088017 | 1005.088017 | 0 | 2 |

Le nombre de lignes ledger n'est pas cense egaler le nombre de closes, car il contient aussi des
OPEN/REDUCE. Cependant les differences de PnL et l'absence de reconstruction complete par
`position_key` prouvent que les anciennes sessions ne sont pas entierement reconciliables.

## Cause 1 - aucun edge copy robuste n'est prouve

L'etude existante couvre `24 133` signaux. Son esperance reste autour de `-7.97 bps` meme avant une
modelisation complete de tous les couts. Le consensus de quatre wallets ou plus reste negatif avec un
profit factor proche de `0.39`.

Le replay de la session de reference donne :

- train : `-64.438970` ;
- validation : `+4.061648` ;
- holdout : `-34.247028` ;
- meilleur choix robuste : `no_trade_baseline`.

Implication : desactiver `HYPERSMART_REQUIRE_EMPIRICAL_EDGE=1` pour obtenir plus de trades serait une
regression. Cela fabriquerait des entrees sans preuve et ne reparerait pas le PnL.

## Cause 2 - quelques pertes dominent tous les gains

Sur l'extrait canonique de 19 fermetures de `session_20260711_161654` :

- PnL net : `-44.655244 USDC` ;
- frais : `10.260212 USDC` ;
- 9 evenements positifs, 10 negatifs.

| Coin | PnL net USDC |
|---|---:|
| ZEC | -16.647055 |
| BTC | -15.052658 |
| AVNT | -6.794351 |
| SOL | -5.245401 |
| ETH | -3.463734 |
| HYPE | -2.636107 |
| VINE | -0.015000 |
| NEAR | +2.723996 |
| SUI | +1.390410 |
| @188 | +0.605706 |
| BNB | +0.478950 |

ZEC et BTC expliquent environ `31.70 USDC` de pertes. Le probleme n'est donc pas seulement le taux de
reussite : la distribution des pertes est beaucoup plus lourde que celle des gains.

## Cause 3 - exposition et sizing excessifs

Dans `session_20260711_204658`, plusieurs OPEN ont exactement
`copied_notional_usdt=500` pour un capital de depart de `1000`. Le champ `adaptive_sizing` est nul.

Deux positions utilisent deja 100 % du capital notionnel. Plusieurs positions simultanees creent un
levier implicite important. Une ancienne observation runtime montrait environ `4500 USDT` de notionnel
sur `1000 USDT`, avec presque toutes les positions SHORT et des doublons par coin.

La taille ne doit plus etre choisie dans `fusion_runtime` ni dans une adaptation de profil externe.
Le PaperEngine doit etre la seule autorite de sizing et refuser avant l'ecriture de l'OPEN si un cap
portefeuille, direction, coin ou correlation est depasse.

## Cause 4 - frais et timeout rendent les petits mouvements non rentables

Exemples du ledger `session_20260711_204658` :

| Coin | Methode | Brut | Cout | Net | Diagnostic |
|---|---|---:|---:|---:|---|
| HYPE | `SLTP_TIMEOUT` | +0.404536 | 0.600485 | -0.195949 | gain brut inferieur aux couts |
| @107 | `SLTP_TIMEOUT` | -0.112280 | 0.599865 | -0.712145 | derive faible, cout dominant |
| AAVE | `SLTP_TIMEOUT` | -1.772609 | 0.597873 | -2.370482 | mouvement adverse + cout |

Le timeout ferme donc parfois une position gross-positive avec une perte nette. Il faut calculer le
break-even complet avant toute sortie discretionnaire : frais entree/sortie, spread, slippage,
funding et degradation de copie. Les stops de securite restent prioritaires ; ne jamais prolonger une
perte uniquement pour eviter les couts.

## Cause 5 - concentration directionnelle

Une session observee avait environ 73 % de positions SHORT et environ 97 % de sa perte provenait des
shorts. Le risque doit etre calcule sur le notionnel net LONG/SHORT, pas seulement sur le nombre de
positions.

Modules a verifier de bout en bout :

- `src/hl_observer/risk/directional_exposure.py` ;
- `HYPERSMART_MAX_NET_DIRECTIONAL_PCT` ;
- `HYPERSMART_MAX_COIN_NOTIONAL_PCT`.

Chaque refus doit etre ecrit dans le DecisionLedger avec exposition avant/apres et limite appliquee.

## Cause 6 - donnees fraiches vieillies par le hot path

Le cycle mesure dure encore environ `31.65 s`. Temps observes :

- user fills : `15.0 s` ;
- scan public : `10.5 s` ;
- opportunity report : `13.0 s` ;
- explorer : `9.8 s` ;
- warehouse report : `8.8 s` ;
- scan marche : `5.0 s`.

Certaines etapes se chevauchent, mais OpportunityReport a traite un groupe age de `29.2 s`. La
decision doit etre event-driven et declenchee juste apres le batch WS/userFills. Explorer, warehouse
et rapports doivent tourner hors du chemin critique, a cadence lente et bornee.

Fichier principal : `src/hl_observer/runtime/persistent_poll_runner.py`.

## Cause 7 - les deltas n'ont pas les features necessaires

Le heartbeat corrige voit des fills Hyperliquid frais et des prix. Il ne produit pourtant aucun
`distilled_signal_candidate` lorsque manquent :

- `edge_remaining_bps` empirique ;
- `liquidity_score` mesure ;
- `copy_degradation_bps` mesure.

Il ne faut pas convertir un vote ou un score arbitraire en bps. Le candidat doit etre enrichi avec
L2 reel, spread, profondeur, slippage estime, frais et provenance. Si une mesure manque, le bon etat
est NO_TRADE.

## Cause 8 - divergence des sources comptables

Pour `session_20260711_161654` :

- snapshot : `-63.682548` ;
- extrait canonique disponible : `-44.655244` ;
- audit de 39 closes issus de plusieurs logs : `-94.624350` ;
- divergence snapshot/logs apres latent : environ `30.941802`.

Tant que ces nombres ne sont pas expliques par une liste de positions fermee sans doublon, les
anciennes archives ne doivent pas servir a calibrer sizing, SL/TP ou modele IA.

## Correctifs Codex deja realises - ne pas annuler

### Fraicheur et consensus

`src/hl_observer/runtime/fusion_heartbeat_input.py` :

- utilise `exchange_ts` avant le temps d'ingestion ;
- dedupe `(wallet, coin, side)` ;
- lit une queue bornee par cle primaire sur la grosse DB ;
- heartbeat mesure autour de 358 ms dans le runtime relance.

### Logs forensic

`src/hl_observer/ui/simulation_log_export.py` conserve maintenant :

- taille avant/fermee/apres ;
- notionnel ferme ;
- age, min hold et stop catastrophique ;
- TP, SL, trailing et MFE ;
- funding et couts ;
- spread, slippage, liquidite et profondeur ;
- edge, source de l'edge et statut empirique ;
- strategie et preuves source.

### Audit exposition

`src/hl_observer/analysis/negative_pnl_auditor.py` expose maintenant :

- notionnel brut, long, short et net ;
- levier brut/net ;
- direction dominante ;
- concentration par coin ;
- doublons ;
- positions sans evidence d'entree complete.

### Attribution des pertes

`src/hl_observer/simulation/decision_replay_analyzer.py` lit d'abord
`simulation_pnl_ledger_latest.jsonl`. Avant, les evaluations GitHub masquaient les vraies fermetures.

## Suppression propre du bus GitHub du runtime

Ne pas supprimer brutalement les clones. Retirer uniquement leur cablage runtime.

### Fichiers a modifier

1. `src/hl_observer/strategies/external_simulation_bus.py`
   - conserver comme module legacy/research si necessaire ;
   - `external_profile_scope()` doit retourner `off` par defaut ;
   - aucune execution dans le runtime normal.
2. `src/hl_observer/strategies/fusion_runtime.py`
   - retirer l'appel `run_external_profile_simulation_bus()` ;
   - retirer les profils externes comme source de `strategy_id` ;
   - ne conserver que des strategies HyperSmart canoniques.
3. `src/hl_observer/ui/fusion_persistent_adapter.py`
   - ne plus enregistrer `_record_external_profile_executions()` ;
   - interdire toute materialisation directe externe ;
   - ne plus ecrire `ENGINE_EVALUATION` dans `simulation_ledger_events`.
4. `src/hl_observer/ui/status_routes.py`
   - retirer `external_github_bridge` du payload principal ;
   - filtrer defensivement tous les `ENGINE_EVALUATION` des stats comptables.
5. `src/hl_observer/ui/static/simulation_v2.html`
   - retirer les cartes `Moteurs GitHub`, `Bus GitHub simulation` et `Profil paper utilise` ;
   - afficher uniquement la chaine HyperSmart canonique.
6. `tools/start_hypersmart_simulation.ps1`
   - fixer `HYPERSMART_EXTERNAL_PROFILES_SCOPE=off` ;
   - supprimer tout flag de materialisation directe du lancement normal.

### Invariants a ajouter

- `ENGINE_EVALUATION` ne peut jamais etre comptabilise comme trade.
- `PAPER_ORDER_ACCEPTED` exige coin tradable, LONG/SHORT, prix positif, taille positive, couts,
  `position_key` et evidence source.
- un evenement sans impact comptable va dans un diagnostic separe, jamais dans `paper_ledger`.
- seul PaperEngine peut ajouter ou modifier une position.

## Ordre de reparation recommande

1. Mettre le bus GitHub hors runtime et ajouter les tests anti-regression.
2. Faire du ledger canonique l'unique source du dashboard, des logs et des audits.
3. Reconstruire toutes les positions historiques par `position_key`.
4. Resoudre chaque divergence snapshot/ledger ou marquer l'archive non calibrable.
5. Faire du PaperEngine l'unique autorite de sizing.
6. Appliquer caps brut, net, direction, coin, correlation et capital disponible.
7. Sortir explorer/warehouse/reporting du hot path.
8. Declencher decision et scoring directement sur evenements WS frais dedupes.
9. Enrichir chaque delta avec L2, spread, profondeur, slippage et couts.
10. Construire une table d'edge empirique par wallet, coin, regime et horizon.
11. Garder un holdout strictement inutilise pendant la selection.
12. Rejouer TP/SL/trailing/timeout avec couts complets et sans lookahead.
13. Classer les timeouts net-negatifs dus aux couts comme `TIMEOUT_COST_DRAG`.
14. Promouvoir uniquement une configuration PF > 1 sur train et validation, puis verifier holdout.
15. Si aucune configuration ne bat le non-trade, conserver NO_TRADE.

## Tests minimum a ajouter

- le scope externe est `off` par defaut ;
- fusion runtime n'appelle pas le bus externe ;
- aucun `ENGINE_EVALUATION` dans le ledger canonique ;
- aucun diagnostic externe dans total_trades, closed_trades, winrate ou PF ;
- ordre paper refuse si taille, prix, sens ou `position_key` manque ;
- deux OPEN de 500 sur equity 1000 ne contournent pas les caps ;
- exposition SHORT nette excessive refusee ;
- doublon coin/side refuse ou fusionne explicitement ;
- OPEN/REDUCE/CLOSE se reconcilient exactement par `position_key` ;
- frais ne sont pas comptes deux fois ;
- timeout gross-positive/net-negative est correctement classe ;
- dashboard PnL = ledger PnL a la tolerance pres ;
- spike graphe sans evenement ledger est refuse et journalise ;
- event time ancien ingere maintenant reste stale ;
- un wallet ne compte qu'une fois dans un consensus coin/side ;
- aucun ordre reel, aucune signature, aucune cle, aucun `/exchange`.

## Tests deja passes

```text
25 passed
tests/test_fusion_heartbeat_input.py
tests/test_hypersmart_v19_negative_pnl_audit.py
tests/test_hypersmart_simulation_diagnostic_logs.py
tests/test_simulation_log_export_forensics.py

5 passed
tests/test_simulation_loss_report.py
```

## Commandes de validation

```powershell
$env:PYTHONPATH='src'
python -m pytest -q tests/test_fusion_heartbeat_input.py `
  tests/test_hypersmart_v19_negative_pnl_audit.py `
  tests/test_hypersmart_simulation_diagnostic_logs.py `
  tests/test_simulation_log_export_forensics.py `
  tests/test_simulation_loss_report.py

python -m hl_observer.cli pnl-audit `
  --from-logs 'logs\logs a envoyer\_archives\session_20260711_161654' `
  --output-dir 'runtime\reports\pnl_audit_session_20260711_161654'

python -m hl_observer.cli loss-attribution `
  --from-logs 'logs\logs a envoyer\_archives\session_20260711_161654'

python -m hl_observer.cli closed-ledger-replay `
  --from-logs 'logs\logs a envoyer\_archives\session_20260711_161654' `
  --output-dir 'runtime\reports\closed_replay_20260711_161654'

python -m pytest -q
python -m hl_observer.cli --safety-check
python -m hl_observer.cli --audit-safety
```

Adapter les deux dernieres commandes au CLI reel si leurs options sont exposees via
`python -m hyper_smart_observer.app.main`.

## Criteres d'acceptation Claude

Le chantier n'est pas valide tant que :

- le bus GitHub n'apparait plus dans le hot path ni l'UI principale ;
- zero `ENGINE_EVALUATION` n'entre dans le ledger comptable ;
- snapshot, ledger, dashboard et logs donnent le meme PnL ;
- chaque fermeture possede une entree et une taille reconciliables ;
- le sizing tient compte de l'equity et de l'exposition existante ;
- les couts sont decomposes sans double comptage ;
- le decision path utilise des timestamps de marche ;
- l'edge accepte est empirique et positif apres couts ;
- replay train/validation/holdout est sans lookahead ;
- la suite cible et les audits de securite passent.

## Limites et verite a conserver

- Un PnL positif ne peut pas etre garanti.
- Le PnL plat est correct quand aucune opportunite ne passe les gates.
- Un score de wallet n'est pas un edge en bps.
- Un consensus n'est pas une preuve de rentabilite.
- Une configuration qui gagne sur le meme echantillon utilise pour la choisir est suspecte.
- Les archives non reconciliables ne doivent pas entrainer l'IA.
- L'IA doit rester shadow tant qu'elle n'a pas de donnees mixtes, propres et hors echantillon.

## Prochain objectif exact pour Claude

> Reprends depuis ce rapport. Commence par supprimer proprement le bus GitHub du runtime sans effacer
> les clones de recherche. Ajoute les invariants qui interdisent qu'un `ENGINE_EVALUATION` devienne un
> trade. Ensuite reconstruis `session_20260711_161654` et `session_20260711_204658` par `position_key`
> pour obtenir une reconciliation exacte OPEN/REDUCE/CLOSE, frais et PnL. Ne change aucun seuil de
> strategie avant que cette preuve comptable soit obtenue. Puis sors les rapports lents du hot path,
> enrichis les deltas avec les vraies features L2 et lance le replay A/B sans lookahead. Ne promeus
> que ce qui bat le non-trade sur validation et reste positif sur holdout.

