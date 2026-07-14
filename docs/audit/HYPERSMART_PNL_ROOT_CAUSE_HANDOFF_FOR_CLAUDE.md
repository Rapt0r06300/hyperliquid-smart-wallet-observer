# HyperSmart - handoff causes racines du PnL pour Claude

Date de l'audit : 2026-07-12  
Perimetre : runtime actif `src/hl_observer`, Hyperliquid read-only, simulation paper locale.  
Regle : ce document n'affirme aucun profit futur et ne recommande aucun ordre reel.

## Reponse courte

Le PnL negatif ne vient pas d'une cause unique. Quatre familles de causes se cumulent :

1. **Le signal de copy-trading historique n'a pas d'edge net mesure.** Sur l'etude existante de
   24 133 signaux, l'esperance reste negative meme avant une modelisation complete des couts. Le
   meilleur replay robuste des trades fermes reste actuellement `no_trade_baseline`.
2. **Les anciennes sessions ont paye beaucoup de frais et ont concentre les pertes sur quelques
   stops.** La session archivee `session_20260711_161654` a un PF net proche de `0.17`; ZEC et BTC
   expliquent a eux seuls environ `31.70 USDC` des `44.66 USDC` visibles dans l'extrait canonique.
3. **Le portefeuille a pu empiler le meme pari directionnel.** Une session observee contenait neuf
   positions, presque toutes SHORT, pour environ 4 500 USDT de notionnel sur 1 000 USDT de capital.
   Les doublons ETH/PUMP et la concentration SHORT amplifiaient un seul mouvement de marche.
4. **Le hot path vieillissait les donnees avant la decision.** Le cycle actuel dure encore environ
   `31.65 s`; un cluster arrive frais mais l'OpportunityReport l'a juge a `29.2 s`. Un ancien bug
   utilisait aussi le temps d'ingestion comme temps de marche et comptait plusieurs fills du meme
   wallet comme plusieurs votes.

Il faut donc corriger/calibrer la chaine dans cet ordre : provenance et fraicheur, edge empirique,
concentration, couts/exits, puis seulement seuils d'admission.

## Preuves quantitatives

### Session perdante de reference

Source : `logs/logs a envoyer/_archives/session_20260711_161654`.

- Snapshot session : `-63.682548 USDC`.
- Extrait PnL canonique disponible : 19 fermetures, `-44.655244 USDC`.
- Logs enrichis/supplementaires analyses par l'audit : 39 fermetures, `-94.624350 USDC`.
- Divergence snapshot/logs : `30.941802 USDC` apres latent, donc l'ancienne exportation n'est pas
  une preuve comptable complete.
- Profit factor net des 39 fermetures : environ `0.1705`.
- Frais des 39 fermetures : `21.126074 USDC`.
- Replay observe : train `-64.438970`, validation `+4.061648`, holdout `-34.247028`.
- Aucune variante testee ne bat le non-trade sur selection robuste + holdout.

Attribution de l'extrait canonique de 19 fermetures :

| Coin | PnL net USDC |
|---|---:|
| ZEC | -16.647055 |
| BTC | -15.052658 |
| AVNT | -6.794351 |
| SOL | -5.245401 |
| ETH | -3.463734 |
| HYPE | -2.636107 |
| NEAR | +2.723996 |
| SUI | +1.390410 |
| @188 | +0.605706 |
| BNB | +0.478950 |

Conclusion : ce n'est pas un simple probleme de winrate. Quelques pertes beaucoup plus grandes
que les gains et les couts detruisent le PF.

### Session active apres relance

Observation endpoint local `/api/simulation/status`, poll 14 :

- serveur et moteur actifs ; endpoint overview repond en environ 163 ms ;
- equity `1000`, aucune position et aucune fermeture pour cette nouvelle session ;
- 1 849 trades publics et 311 wallets vus sur le scan public du cycle ;
- 166 signaux copy-run ; aucune entree acceptee ;
- 19 votes fusion frais, 14 coins avec prix, dernier delta age de 0 ms ;
- heartbeat fusion : environ `358 ms` apres correction ;
- cycle total : environ `31 650 ms` ;
- OpportunityReport : 4 groupes, meilleur groupe age de `29 214 ms`, edge `-11.99 bps`, refus
  `EDGE_NOT_EMPIRICAL_NO_TRADE` ;
- `distilled_signal_candidates=[]` car les deltas bruts n'apportent pas encore simultanement un
  edge mesure, une liquidite mesuree et une degradation de copie mesuree.

Conclusion : le moteur collecte actuellement. Le PnL plat n'est pas une panne comptable. Le gate
empirique refuse parce que la calibration disponible ne prouve pas un edge positif apres couts.

## Bugs confirmes et deja corriges dans cette passe Codex

### 1. Heure d'ingestion prise pour heure de marche

Fichier : `src/hl_observer/runtime/fusion_heartbeat_input.py`.

Avant : `detected_at_ms` pouvait rendre frais un fill Hyperliquid ancien charge tardivement.  
Apres : priorite a `exchange_ts` / event time ; ingestion seulement en dernier recours.

Test : `test_fusion_heartbeat_rejects_old_exchange_event_even_if_ingested_now`.

### 2. Consensus gonfle par doublons

Avant : plusieurs deltas du meme wallet, coin et sens pouvaient compter comme plusieurs votes.  
Apres : dedupe `(wallet, coin, side)` et conservation de l'evenement source le plus recent.

Test : `test_fusion_heartbeat_dedupes_same_wallet_coin_side_and_uses_exchange_clock`.

### 3. Requete heartbeat trop lente sur base multi-gigaoctets

Avant : filtre et tri de millions de lignes sur `detected_at_ms`, absent des index legacy.  
Apres : lecture bornee de la queue par cle primaire, filtrage event-time en memoire, et ordre des
market snapshots par id. Mesure sur la DB active : environ `0.73 s` en appel isole ; le statut
runtime apres relance rapporte `358 ms`.

### 4. Export des sorties incomplet

Fichier : `src/hl_observer/ui/simulation_log_export.py`.

Les exports conservent maintenant : age de position, minimum hold, stop catastrophique, TP, SL,
trailing, funding, tailles avant/fermee/apres, notionnel ferme, edge, source de l'edge, consensus,
liquidite, spread, slippage, profondeur, strategie et profils source.

Test : `tests/test_simulation_log_export_forensics.py`.

### 5. Audit PnL aveugle au portefeuille ouvert

Fichier : `src/hl_observer/analysis/negative_pnl_auditor.py`.

L'audit expose maintenant : notionnel brut, notionnel LONG/SHORT, exposition nette, sens dominant,
levier brut/net, concentration par coin, doublons et nombre de positions sans evidence complete.

### 6. `loss-attribution` lisait les mauvaises lignes

Fichier : `src/hl_observer/simulation/decision_replay_analyzer.py`.

Avant : le fichier de 1 000 evaluations GitHub shadow masquait les vrais closes.  
Apres : `simulation_pnl_ledger_latest.jsonl` est prioritaire. La meme archive passe de "aucune
cause" a 19 fermetures, `-44.655244`, fees `10.260212`, causes `NEGATIVE_EVENTS_DOMINATE` et
`FEES_DRAG`.

## Points critiques encore ouverts

### A. Le cycle de decision reste trop long

Le poll courant depense environ :

- `live_user_fills_scan`: 15.0 s ;
- `live_public_scan`: 10.5 s ;
- `opportunity_report`: 13.0 s ;
- `scrape_explorer`: 9.8 s ;
- `warehouse_report`: 8.8 s ;
- `scan_markets`: 5.0 s.

Certaines etapes se chevauchent, mais le poll total reste 31.65 s. La decision doit etre declenchee
immediatement apres un batch WS frais. Les rapports explorer/warehouse ne doivent jamais bloquer le
hot path. Chercher dans `src/hl_observer/runtime/persistent_poll_runner.py`.

### B. Les deltas frais n'ont pas les features necessaires au chemin distille

Le heartbeat voit des fills reels, mais `_distilled_candidate_from_delta()` refuse si l'un de ces
champs manque :

- `edge_remaining_bps` mesure ;
- `liquidity_score` mesure ;
- `copy_degradation_bps` mesure.

Ne pas remettre une formule vote-score -> bps. Brancher le carnet L2/microstructure et la table
d'edge empirique en amont du delta, ou rester NO_TRADE.

### C. La calibration empirique disponible est negative

Fichier : `runtime/calibration/empirical_edge.json`.  
Code : `src/hl_observer/edge/empirical_edge.py`.

Le gate `HYPERSMART_REQUIRE_EMPIRICAL_EDGE=1` bloque par conception. Le desactiver ferait revenir
un proxy invente et ne corrigerait pas le PnL. Il faut produire une calibration causale par
wallet/coin/regime/horizon, avec train/validation/holdout, et promouvoir uniquement une bande dont
l'edge net reste positif hors echantillon.

### D. L'ancienne comptabilite n'est pas reconciliee

Le snapshot, le PnL extract et les evenements supplementaires ne donnent pas le meme total pour
l'archive de reference. Ne pas utiliser cette archive pour calibrer le sizing sans reconstruire
chaque OPEN -> CLOSE par `position_key` et sans prouver l'absence de doublons.

### E. SL/TP et timeout doivent etre juges apres couts

Configuration active observee : TP 110 bps, SL 60 bps, trailing 45 bps, activation 65 bps,
min-hold 45 s, stop catastrophique 110 bps. Le code applique aussi des barrieres vol-ajustees.

Ne pas recopier un calibrage d'un autre repo. Pour chaque sortie, comparer :

1. PnL brut avant couts ;
2. frais/spread/slippage/funding ;
3. PnL net ;
4. MFE/MAE ;
5. age ;
6. raison TP/SL/trailing/timeout/leader close.

Un timeout gross-positive mais net-negatif doit etre classe `COSTS_EXCEED_GROSS_MOVE`, pas comme
bonne sortie. Tester plusieurs horizons uniquement en replay sans lookahead.

### F. Risque directionnel

Le module `src/hl_observer/risk/directional_exposure.py` et les flags suivants sont maintenant
presents :

- `HYPERSMART_MAX_NET_DIRECTIONAL_PCT` ;
- `HYPERSMART_MAX_COIN_NOTIONAL_PCT`.

Verifier leur cablage E2E sur le runtime relance, puis ajouter le resultat du refus au ledger et au
dashboard. Ne pas se contenter du nombre total de positions.

### G. Le bus GitHub pollue la notion de trade accepte

Preuve sur l'endpoint actif `/api/simulation/overview` apres la relance du 12 juillet :

- le ledger visible contient `171` evenements et ils sont tous de type `ENGINE_EVALUATION` ;
- certains portent `decision=PAPER_ORDER_ACCEPTED` et
  `reason=PROFILE_PRODUCED_ACCEPTED_LOCAL_PAPER_ORDER` ;
- ces memes evenements ont pourtant `copied_notional_usdt=0`, `leader_side=NONE`,
  `execution=forbidden` et ne creent aucune position ;
- le portefeuille canonique reste a `1000`, avec zero position et zero trade ferme.

Ce ne sont donc pas des trades paper. Ce sont des diagnostics de profils. Ils ne doivent jamais :

1. incrementer le compteur de trades joues ;
2. apparaitre comme une entree acceptee ;
3. entrer dans le winrate, le PF ou le PnL ;
4. etre ecrits dans le ledger comptable canonique.

Correction attendue : separer strictement `strategy_diagnostics` du `paper_ledger`. Un evenement ne
devient `PAPER_ORDER_ACCEPTED` qu'apres creation d'un ordre paper avec coin tradable, sens LONG/SHORT,
prix, taille strictement positive, couts, identifiant de position et preuve source. Sinon le statut
doit rester `ENGINE_EVALUATED_NO_ORDER`.

### H. Le sizing historique empilait des positions de 500 USDT

Dans `session_20260711_204658`, plusieurs OPEN ont `copied_notional_usdt=500` alors que le capital de
depart vaut `1000`. Deux positions suffisent donc a consommer 100 % du capital notionnel, et plusieurs
positions simultanees produisent un levier implicite important. Le champ `adaptive_sizing` est nul sur
ces evenements : le sizing n'etait pas adapte a l'equity, au nombre de positions, a la correlation ou
a l'exposition directionnelle deja ouverte.

Correction attendue : le PaperEngine doit etre l'unique autorite de taille et appliquer avant OPEN :

- plafond de notionnel brut du portefeuille ;
- plafond net LONG/SHORT ;
- plafond par coin et par cluster correle ;
- budget restant apres positions ouvertes ;
- taille reduite apres pertes consecutives ;
- refus si l'evidence de prix/edge/couts est incomplete.

### I. Les timeouts ferment souvent avant le seuil de rentabilite apres couts

Exemples reels du ledger de `session_20260711_204658` :

| Coin | Sortie | PnL brut | Cout | PnL net | Observation |
|---|---|---:|---:|---:|---|
| HYPE | `SLTP_TIMEOUT` | +0.404536 | 0.600485 | -0.195949 | mouvement favorable, mais inferieur aux couts |
| @107 | `SLTP_TIMEOUT` | -0.112280 | 0.599865 | -0.712145 | petite derive + cout dominant |
| AAVE | `SLTP_TIMEOUT` | -1.772609 | 0.597873 | -2.370482 | mouvement adverse avant timeout |

Le timeout n'est donc pas neutre : sur 500 USDT, environ 0.60 USDT de cout de sortie suffit a
transformer un petit gain brut en perte nette. Le moteur doit calculer le seuil de rentabilite complet
avant toute sortie discretionnaire et distinguer `TIMEOUT_NET_POSITIVE`, `TIMEOUT_COST_DRAG` et
`TIMEOUT_ADVERSE_MOVE`. Les stops de risque restent prioritaires ; il ne faut pas prolonger une perte
uniquement pour eviter de la constater.

### J. La preuve comptable des anciennes sessions reste incomplete

`session_20260711_204658` annonce 15 trades fermes dans son snapshot, mais son fichier ledger contient
35 lignes OPEN/CLOSE. `session_20260711_161654` presente aussi trois totaux differents selon la surface.
Tant que chaque position n'est pas reconstruite par `position_key` avec exactement un OPEN et des
reductions/fermetures dont la somme ne depasse pas la taille ouverte, aucun calibrage PnL historique ne
doit etre promu.

## Ordre exact recommande a Claude

1. Sortir tous les `ENGINE_EVALUATION` du ledger comptable et des compteurs de trades.
2. Ajouter un invariant : aucun `PAPER_ORDER_ACCEPTED` sans coin, sens, prix, taille et position_key.
3. Reconstruire OPEN/REDUCE/CLOSE par `position_key` et resoudre les divergences snapshot/ledger.
4. Ne pas desserrer `HYPERSMART_REQUIRE_EMPIRICAL_EDGE`.
5. Rejouer les tests cibles listes ci-dessous.
6. Separer le hot path WS/decision des rapports lents dans `persistent_poll_runner.py`.
7. Declencher heartbeat + candidate scoring juste apres le join userFills, avant explorer et
   warehouse.
8. Faire tourner explorer/warehouse a cadence basse ou dans un worker read-only borne.
9. Enrichir les deltas frais avec L2 reel, spread, slippage, profondeur et provenance.
10. Faire du PaperEngine l'unique autorite de sizing et bloquer l'empilement de notionnels de 500.
11. Construire une calibration empirique causale avec holdout non utilise pour selection.
12. Lancer un replay A/B des exits TP/SL/trailing/timeout avec couts complets.
13. Promouvoir uniquement un changement qui ameliore PF train ET validation, puis verifier holdout.
14. Verifier les caps directionnels et par coin sur un test E2E PaperEngine -> ledger.
15. Laisser le PnL plat si aucune strategie ne bat le non-trade. Ne jamais fabriquer d'action.

## Tests verifies dans cette passe

```text
25 passed
tests/test_fusion_heartbeat_input.py
tests/test_hypersmart_v19_negative_pnl_audit.py
tests/test_hypersmart_simulation_diagnostic_logs.py
tests/test_simulation_log_export_forensics.py

5 passed
tests/test_simulation_loss_report.py
```

## Commandes de reprise

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
```

## Phrase de reprise pour Claude

> Reprends depuis `docs/audit/HYPERSMART_PNL_ROOT_CAUSE_HANDOFF_FOR_CLAUDE.md`. Ne desserre aucun
> gate pour fabriquer des trades. Commence par sortir OpportunityReport du chemin critique,
> enrichis les deltas frais avec des features L2 mesurees, puis reconstruis les trades fermes par
> position_key afin de resoudre la divergence ledger/snapshot. Ne promeus un calibrage que s'il
> bat le non-trade sur validation causale, avec holdout reserve a la verification.
