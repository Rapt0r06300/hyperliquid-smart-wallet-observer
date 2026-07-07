# HyperSmart scan bottleneck audit - 2026-06-28

## Constat

Le probleme observe "3 wallets en 4h" ne venait pas d'une absence de donnees en base.

Diagnostic sur `runtime/data/hypersmart_simulation_session.sqlite3` :

- `wallet_candidates` : 2 853 785 lignes.
- `top_wallets` : 133 016 lignes.
- wallets distincts dans `top_wallets` : 26 686.
- wallets distincts `public_trades_ws` : 26 540.
- echantillon `top_wallets limit 250` avant dedupe : 16 wallets uniques seulement.
- echantillon `top_wallets limit 2500` avant dedupe : 21 wallets uniques seulement.
- echantillon `top_wallets limit 8000` avant dedupe : 52 wallets uniques.

Conclusion : le scanner voyait beaucoup de wallets, mais l'UI et le scanner `live-user-fills-scan`
prelevaient trop peu de lignes avant deduplication. Les lignes de tete etaient dominees par des
rafraichissements du meme petit groupe de wallets. Le pool de leaders reellement suivis tombait donc
artificiellement sous la cible.

## Correctifs appliques

1. `src/hl_observer/ui/routes.py`
   - Ajout `top_wallet_sample_limit()` borne a 50 000, defaut 8 000.
   - `/api/copy/status` lit 8 000 lignes avant dedupe.
   - `/api/copy/leader-activity` lit 8 000 lignes avant dedupe.
   - `/api/simulation/overview` lit 8 000 lignes avant dedupe.
   - Ajout diagnostics visibles :
     - `leader_rows_sampled_before_dedupe`
     - `leader_sample_limit`
   - Bornage de l'overview au nombre de leaders cible.

2. `src/hl_observer/cli.py`
   - Ajout `_top_wallet_sample_limit()`.
   - `_selected_top_wallet_rows()` utilise maintenant un echantillon profond avant dedupe.
   - Impact : `live-user-fills-scan` ne tourne plus sur un pool artificiellement reduit.

3. `src/hl_observer/simulation/session_memory.py`
   - Nouvelle memoire de session locale paper par `coin + side`.
   - Si un couple `coin + side` vient de perdre, une nouvelle entree identique exige :
     - edge plus eleve ;
     - consensus minimal ;
     - liquidite minimale.
   - Le cote oppose n'est pas bloque.

4. `src/hl_observer/ui/simulation_log_export.py`
   - Les logs exportes incluent maintenant :
     - `session_memory_reason`
     - `session_memory_coin_side_pnl_usdc`
     - `session_memory_recent_loss_streak`
     - `session_memory_required_edge_bps`

5. `tools/start_hypersmart_simulation.ps1`
   - `HYPERSMART_TOP_WALLET_SAMPLE_LIMIT=8000`.
   - Ajout seuils de memoire coin+side :
     - `HYPERSMART_COIN_SIDE_LOSS_COOLDOWN_USDC=0.20`
     - `HYPERSMART_COIN_SIDE_LOSS_RECOVERY_EXTRA_EDGE_BPS=35`
     - `HYPERSMART_COIN_SIDE_LOSS_MIN_CONSENSUS=3`
     - `HYPERSMART_COIN_SIDE_LOSS_MIN_LIQUIDITY=0.55`

## Verification locale

Avec le nouveau code charge directement sur la DB runtime :

- `/api/copy/status` : `leaders_count=50`, `sampled=8000`, `limit=8000`.
- `/api/simulation/overview?limit=1` : `leaders=50`, `target=50`, `sampled=8000`, `limit=8000`.

Le poller n'etait plus actif au moment du diagnostic :

- dernier `position_deltas.detected_at_ms` age approximatif : 24 minutes.
- `launcher_exit` detecte dans `logs/hypersmart_launcher.log`.

Donc l'ecran fige venait aussi d'un arret du lanceur/poller. Il faut relancer `LANCER_HYPERSMART.cmd`
pour que les nouveaux reglages prennent effet.

## Tests

Commandes lancees :

```powershell
python -m pytest -q tests/test_copy_cli_and_safety.py tests/test_fresh_opportunity.py tests/test_hypersmart_session_memory.py tests/test_ui_copy_dashboard.py tests/test_pnl_loss_fixes.py tests/test_ui_simulation_persistence.py tests/test_ui_simulation_status_fast.py tests/test_ui_simulation_v9_filters.py
```

Resultat : `99 passed`.

Checks :

```powershell
python -m hl_observer audit-safety
python -m hyper_smart_observer.app.main --safety-check
python -m hyper_smart_observer.app.main --audit-safety
```

Resultats :

- `audit-safety` : OK.
- `Safety check: OK`.
- audit HyperSmart : OK, aucun `/exchange`, aucune signature, aucune cle privee, aucun ordre reel.

## Prochaine priorite

1. Relancer `LANCER_HYPERSMART.cmd` pour charger le nouveau code.
2. Verifier dans l'UI que :
   - `leaders_loaded_unique=50`;
   - `leader_rows_sampled_before_dedupe=8000`;
   - `fresh_entry_deltas` remonte apres quelques cycles.
3. Si les deltas frais restent faibles :
   - investiguer `live-user-fills-scan` par batch de 10 utilisateurs ;
   - ajouter un flux long-running pour les 10 leaders les plus chauds ;
   - garder la rotation large pour les autres leaders.

Toujours paper-only, read-only, Hyperliquid par defaut. Aucun PnL positif ne doit etre fabrique.
