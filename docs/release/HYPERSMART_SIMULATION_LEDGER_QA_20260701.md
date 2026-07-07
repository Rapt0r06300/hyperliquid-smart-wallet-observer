# HyperSmart Simulation Ledger QA - 2026-07-01

## Contexte

Audit cible apres symptomes utilisateur:

- une position paper disparaissait de l'ecran;
- le compteur "Trades gagnants" restait a `0 / 0`;
- le PnL etait negatif malgre des positions parfois legerement favorables;
- le metagraphe affichait des pics ou des mouvements difficiles a expliquer;
- le moteur ouvrait moins de positions qu'avant.

Le serveur local observe etait `http://127.0.0.1:8794/static/simulation_v2.html`.

## Causes verifiees

### 1. Fermetures paper non comptees dans l'UI rapide

Le ledger local contenait bien des evenements `CLOSE`, notamment des fermetures
par `QUALITY_GUARD_LEGACY_UNEVIDENCED`, mais `/api/simulation/status` n'exposait
pas `closed_trades`, `winning_trades`, `losing_trades` et `winrate_pct`.

Effet visible:

- la position disparaissait;
- le PnL realise changeait;
- l'UI continuait d'afficher `0 / 0`, donnant l'impression que la fermeture
  n'avait jamais ete comptabilisee.

Correctif:

- ajout d'un compteur canonique base sur `simulation_ledger_events`;
- seules les actions paper `CLOSE` / `REDUCE` / exits explicites avec PnL
  numerique sont comptees;
- les lignes `NO_TRADE` et refus ne peuvent pas gonfler les stats.

### 2. Verrous anti-duplication non relaches apres fermeture

Certaines positions paper gardent `source_delta_key`. Apres une fermeture,
la cle pouvait rester dans `simulation_processed_delta_keys`, ce qui pouvait
bloquer une opportunite future portant la meme reference moteur.

Correctif:

- liberation de `source_delta_key` apres fermeture SL/TP;
- liberation de `source_delta_key` apres fermeture directe d'un profil externe;
- liberation pour les fermetures quality guard.

### 3. Exposition amplifiee par levier paper x5

Le moteur paper pouvait convertir `40 USDT` de marge en environ `200 USDT` de
notional via `HYPERSMART_SIMULATION_LEVERAGE=5`. Sur un compte de simulation
de `1000 USDT`, cela amplifiait:

- les frais;
- le cout de sortie estime;
- les pics du metagraphe;
- les petites pertes meme quand le mouvement brut etait legerement favorable.

Correctif:

- profil officiel du lanceur passe a `HYPERSMART_SIMULATION_LEVERAGE=1`;
- `HYPERSMART_MAX_TOTAL_EXPOSURE_USDT` borne a `400`;
- le pont `fusion_persistent_adapter` applique aussi le cap
  `HYPERSMART_MAX_POSITION_USDT` avant d'inscrire une position dans l'UI state.

### 4. SL/TP trop tardif pour le mode diagnostic court

Le profil de lancement avait:

- take profit: `180 bps`;
- stop loss: `120 bps`;
- trailing: `90 bps`;
- stop min hold: `180000 ms`;
- catastrophic stop: `220 bps`.

Sur une simulation courte a `1000 USDT`, cela laissait les positions paper
respirer longtemps et pouvait retarder la comptabilisation d'une sortie.

Correctif:

- take profit: `80 bps`;
- stop loss: `55 bps`;
- trailing: `35 bps`;
- trailing activation: `70 bps`;
- breakeven buffer: `6 bps`;
- stop min hold: `30000 ms`;
- catastrophic stop: `120 bps`.

Ces reglages restent locaux/paper et ne creent aucun ordre.

## Fichiers modifies

- `src/hl_observer/ui/status_routes.py`
- `src/hl_observer/ui/fusion_persistent_adapter.py`
- `src/hl_observer/paper_trading/sltp_runtime.py`
- `src/hl_observer/paper_trading/fusion_paper_engine_adapter.py`
- `tools/start_hypersmart_simulation.ps1`
- `LANCER_HYPERSMART.cmd`
- `tests/test_ui_simulation_status_fast.py`
- `tests/test_v9_sltp_runtime.py`
- `tests/test_fusion_persistent_adapter_external_profiles.py`
- `tests/test_hypersmart_single_launcher.py`
- `tests/test_launcher_guards_match_runtime.py`

## Tests lances

- `python -m pytest -q tests/test_ui_simulation_status_fast.py tests/test_v9_sltp_runtime.py tests/test_fusion_persistent_adapter_external_profiles.py tests/test_hypersmart_single_launcher.py tests/test_launcher_guards_match_runtime.py`
  - resultat: `58 passed`
- tests HyperSmart + ciblés:
  - resultat: `345 passed`
- `python -m pytest -q`
  - resultat: `2076 passed`
- `python -m hyper_smart_observer.app.main --safety-check`
  - resultat: `Safety check: OK`
- `python -m hyper_smart_observer.app.main --audit-safety`
  - resultat: OK, aucun `/exchange`, aucune signature, aucun ordre reel.

## Lecture du PnL

Le PnL reste une mesure de simulation paper locale, calculee sur vrais prix
Hyperliquid disponibles. Ce rapport ne promet pas de PnL positif. Il corrige
les incoherences de comptabilite et reduit les sources de pertes artificiellement
amplifiees par levier/frais.

Formule officielle:

`equity = starting_balance + realized_pnl + unrealized_pnl`

## Prochaine verification manuelle

Redemarrer avec `LANCER_HYPERSMART.cmd` pour charger le nouveau code et les
nouveaux reglages. Observer ensuite:

- `closed_trades` doit augmenter quand une position ferme;
- `winning_trades / closed_trades` ne doit plus rester a `0 / 0` apres fermeture;
- les positions ne doivent plus rester bloquees par `DUPLICATE_DIRECT_PAPER_ORDER`
  apres une fermeture reelle du paper ledger;
- l'exposition par position doit rester proche du cap paper au lieu de `5x`.

## Garde-fous confirmes

- Simulation locale uniquement.
- Donnees reelles ou etat vide honnete.
- Aucun faux PnL.
- Aucun ordre reel.
- Aucun `/exchange`.
- Aucune signature.
- Aucune cle privee.
- Aucun wallet connect.
