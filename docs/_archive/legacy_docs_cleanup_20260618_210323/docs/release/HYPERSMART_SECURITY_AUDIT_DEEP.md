# HyperSmart Security Audit Deep

Generated: 2026-06-18T16:12:33.210206+00:00

## Findings
- OK `no_exchange_path`: matches=0
- OK `no_signature_calls`: matches=0
- OK `no_operational_order`: unexpected_matches=0, locked_refusal_stubs=1
- OK `no_private_key_config`: No private key material is loaded in HyperSmart config.
- OK `database_hygiene`: Legacy DB(s) in logs detected and excluded from clean archives: 1
- OK `archive_hygiene`: Runtime files excluded by clean archive: 1
- OK `secret_scan`: suspicious secret markers: 0
- OK `dashboard_readonly`: Dashboard contains no dangerous action buttons.
- OK `explorer_disabled_by_default`: Explorer observer disabled by default.
- OK `ws_disabled_by_default`: WebSocket monitor disabled by default.
- OK `mainnet_forbidden`: Mainnet flag is disabled.
- OK `execution_disabled_by_default`: Runtime execution flag is disabled.
- OK `testnet_disabled_by_default`: Testnet executor flag is disabled.
- OK `copy_mode_no_llm_hot_path`: Copy detector uses deterministic local rules, no LLM call.

## Extended Surfaces
- src/hl_observer scanned keys: exchange_path, place_order, private_key_literal, sign_call
- root cmd files: ['CREER_ARCHIVE_PROPRE.cmd', 'LANCER_HYPERSMART.cmd']
- tools ps1 files: ['tools\\create_clean_archive.ps1', 'tools\\find_locked_runtime_files.ps1', 'tools\\hypersmart_simulation_poll_loop.ps1', 'tools\\start_hypersmart_simulation.ps1']
- root archives forbidden count: 0

## Policy
- Documentation may mention forbidden terms only to prohibit them.
- Disabled stubs may contain refusal method names only when they fail closed.
- No operational mainnet, signature, private key, order or testnet executor is allowed.
