# Registre des flags de configuration (auto-genere)

> Genere par `python tools/gen_config_flags.py`, sur la meme source de verite que
> `T3-CABLAGE.cmd` (`hl_observer.audit.cablage`). **Ne pas editer a la main.**

Trois choses DIFFERENTES, qu'une ancienne version de ce generateur confondait :

- **lu** : le code appelle `os.environ.get(...)` dessus (AST, hors tests) ;
- **pose** : un lanceur lui donne une valeur (`.cmd`, `.ps1` **dans ses deux syntaxes**,
  `.sh`, `.yaml`) ;
- **MORT** : lu avec un defaut ETEINT (`0`/`false`/`no`/`off`) et pose par **personne**
  -> la capacite existe, elle est cablee, et elle ne s'allumera **jamais**, sans un log.

| statut | nb |
|---|---:|
| flags a nous | 48 |
| **MORTS** (capacite eteinte en silence) | **0** |
| ambigus (defaut vide : « aucune limite » ou « eteint » ? on ne tranche pas) | 2 |
| poses par un lanceur mais lus par personne (flag orphelin) | 0 |

## À lire à la main (defaut vide)

- `HYPERSMART_PNL_AUDIT_PREFER_APPEND_ONLY` -- lu par src/hl_observer/analysis/negative_pnl_auditor.py
- `HYPERSMART_TOP_WALLET_SAMPLE_LIMIT` -- lu par src/hl_observer/cli.py

## Tous les flags

| Flag | defaut | lu par | pose par | statut |
|---|---|---:|---|---|
| `HL_DATABASE_URL` | `-` | 1 | start_hypersmart_simulation.ps1 | pose au lanceur |
| `HL_ENABLE_MAINNET_EXECUTION` | `-` | 1 | LANCER_HYPERSMART.cmd, start_hypersmart_simulation.ps1 | pose au lanceur |
| `HL_ENABLE_TESTNET_EXECUTION` | `-` | 1 | LANCER_HYPERSMART.cmd, start_hypersmart_simulation.ps1 | pose au lanceur |
| `HL_ENV` | `-` | 1 | LANCER_HYPERSMART.cmd, start_hypersmart_simulation.ps1 | pose au lanceur |
| `HL_LOGS_DIR` | `-` | 1 | - | defaut du code |
| `HL_LOG_LEVEL` | `INFO` | 1 | - | defaut du code |
| `HL_REQUIRE_TESTNET_SCHEDULE_CANCEL` | `-` | 1 | - | defaut du code |
| `HYPERSMART_APPEND_ONLY_ROTATE_MB` | `-` | 1 | - | defaut du code |
| `HYPERSMART_DISABLE_RAW_STORAGE` | `0` | 2 | LANCER_HYPERSMART.cmd | pose au lanceur |
| `HYPERSMART_EXECUTION_STYLE` | `taker` | 1 | LANCER_HYPERSMART.cmd | pose au lanceur |
| `HYPERSMART_FRESH_OPPORTUNITY_MAX_PER_COIN` | `-` | 1 | - | defaut du code |
| `HYPERSMART_FRESH_OPPORTUNITY_MIN_WALLETS` | `-` | 1 | LANCER_HYPERSMART.cmd, start_hypersmart_simulation.ps1 | pose au lanceur |
| `HYPERSMART_LEADER_MID_FALLBACK_MAX_AGE_MS` | `0` | 1 | start_hypersmart_simulation.ps1 | pose au lanceur |
| `HYPERSMART_LEADER_QUALITY_GATE` | `1` | 1 | - | defaut du code |
| `HYPERSMART_MAKER_ADVERSE_SELECTION_BPS` | `0` | 1 | LANCER_HYPERSMART.cmd | pose au lanceur |
| `HYPERSMART_MAX_OPEN_POSITIONS` | `-` | 1 | LANCER_HYPERSMART.cmd, start_hypersmart_simulation.ps1 | pose au lanceur |
| `HYPERSMART_MAX_POSITION_USDT` | `-` | 1 | LANCER_HYPERSMART.cmd, start_hypersmart_simulation.ps1 | pose au lanceur |
| `HYPERSMART_MAX_TOTAL_EXPOSURE_USDT` | `-` | 1 | LANCER_HYPERSMART.cmd, start_hypersmart_simulation.ps1 | pose au lanceur |
| `HYPERSMART_PNL_AUDIT_HISTORY_BYTES_AUX_THRESHOLD` | `-` | 1 | - | defaut du code |
| `HYPERSMART_PNL_AUDIT_HISTORY_DECISIONS_AUX_THRESHOLD` | `50000` | 1 | - | defaut du code |
| `HYPERSMART_PNL_AUDIT_PREFER_APPEND_ONLY` | `` | 1 | - | à verifier |
| `HYPERSMART_RECORD_MICROSTRUCTURE` | `0` | 1 | start_hypersmart_simulation.ps1 | pose au lanceur |
| `HYPERSMART_SIMULATION_LEVERAGE` | `1` | 2 | LANCER_HYPERSMART.cmd, start_hypersmart_simulation.ps1 | pose au lanceur |
| `HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS` | `-` | 1 | LANCER_HYPERSMART.cmd, start_hypersmart_simulation.ps1 | pose au lanceur |
| `HYPERSMART_SIMULATION_MAX_PRICE_DEVIATION_BPS` | `-` | 1 | LANCER_HYPERSMART.cmd | pose au lanceur |
| `HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS` | `-` | 1 | LANCER_HYPERSMART.cmd, start_hypersmart_simulation.ps1 | pose au lanceur |
| `HYPERSMART_SIMULATION_MIN_EDGE_BPS` | `-` | 1 | LANCER_HYPERSMART.cmd, start_hypersmart_simulation.ps1 | pose au lanceur |
| `HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS` | `-` | 1 | LANCER_HYPERSMART.cmd | pose au lanceur |
| `HYPERSMART_SLTP_ENABLED` | `0` | 1 | LANCER_HYPERSMART.cmd, hypersmart_simulation_poll_loop.ps1, start_hypersmart_simulation.ps1 | pose au lanceur |
| `HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS` | `-` | 1 | LANCER_HYPERSMART.cmd, hypersmart_simulation_poll_loop.ps1, start_hypersmart_simulation.ps1 | pose au lanceur |
| `HYPERSMART_SLTP_TRAILING_BPS` | `-` | 1 | LANCER_HYPERSMART.cmd, hypersmart_simulation_poll_loop.ps1, start_hypersmart_simulation.ps1 | pose au lanceur |
| `HYPERSMART_STATUS_EXPORT_MIN_MS` | `2500` | 1 | - | defaut du code |
| `HYPERSMART_STATUS_LIVE_MARKS_MIN_INTERVAL_MS` | `1500` | 1 | - | defaut du code |
| `HYPERSMART_STATUS_LIVE_MARKS_TIMEOUT_SECONDS` | `0.35` | 1 | - | defaut du code |
| `HYPERSMART_TOP_WALLET_SAMPLE_LIMIT` | `` | 1 | - | à verifier |
| `HYPERSMART_UI_STATE_DIR` | `-` | 1 | LANCER_HYPERSMART.cmd, start_hypersmart_simulation.ps1 | pose au lanceur |
| `HYPERSMART_V13_EXPL_PATH` | `-` | 1 | LANCER_HYPERSMART.cmd | pose au lanceur |
| `HYPERSMART_V13_MODEL_AUTHORITATIVE` | `` | 1 | LANCER_HYPERSMART.cmd | pose au lanceur |
| `HYPERSMART_V13_MODEL_MIN_P` | `0.5` | 2 | LANCER_HYPERSMART.cmd | pose au lanceur |
| `HYPERSMART_V13_MODEL_PATH` | `-` | 3 | LANCER_HYPERSMART.cmd | pose au lanceur |
| `HYPERSMART_V13_MODEL_REPORT` | `-` | 2 | LANCER_HYPERSMART.cmd | pose au lanceur |
| `HYPERSMART_V13_OLLAMA_API_STYLE` | `-` | 1 | LANCER_HYPERSMART.cmd | pose au lanceur |
| `HYPERSMART_V13_OLLAMA_HOST` | `-` | 1 | LANCER_HYPERSMART.cmd | pose au lanceur |
| `HYPERSMART_V13_OLLAMA_MODEL` | `-` | 1 | LANCER_HYPERSMART.cmd | pose au lanceur |
| `HYPERSMART_V13_SAMPLES_PATH` | `-` | 2 | LANCER_HYPERSMART.cmd | pose au lanceur |
| `HYPERSMART_V26_RECORD_CANDIDATES` | `0` | 2 | LANCER_HYPERSMART.cmd | pose au lanceur |
| `HYPERSMART_V26_RECORD_PATH` | `` | 2 | LANCER_HYPERSMART.cmd | pose au lanceur |
| `HYPERSMART_V9_PIPELINE_AUTHORITATIVE` | `0` | 1 | LANCER_HYPERSMART.cmd | pose au lanceur |
