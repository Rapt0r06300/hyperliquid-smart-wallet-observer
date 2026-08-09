# HyperSmart Security Audit Deep

Generated: 2026-08-09T17:25:09.985874+00:00

## Findings
- OK `no_exchange_path`: matches=0
- OK `no_signature_calls`: matches=0
- OK `no_operational_order`: unexpected_matches=0, locked_refusal_stubs=1
- OK `no_private_key_config`: No private key material is loaded in HyperSmart config.
- OK `database_hygiene`: Legacy DB(s) in logs detected and excluded from clean archives: 1
- OK `archive_hygiene`: Runtime files excluded by clean archive: 11
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
- root cmd files: ['ANALYSER_BACKTESTS_REPLAYS.cmd', 'ANALYSE_HISTORIQUE_COMPLETE.cmd', 'COMMITTER_B1_B2.cmd', 'CREER_ARCHIVE_PORTABLE.cmd', 'DIAGNOSTIC_LANCEUR.cmd', 'LANCER-RECHERCHE-14H.cmd', 'LANCER-RECHERCHE-18H.cmd', 'LANCER-RECHERCHE-CONTINUE-ADMIN.cmd', 'LANCER-RECHERCHE-CONTINUE.cmd', 'LANCER_HYPERLAB.cmd', 'LANCER_HYPERSMART.cmd', 'LANCER_LABO.cmd', 'LANCER_MICRO.cmd', 'POUSSER-GITHUB-FORCE.cmd', 'POUSSER_TOUT_LE_TRAVAIL.cmd', 'PREPARER_GIT_PORTABLE.cmd', 'RECETTE-LANCEUR.cmd', 'RECETTE-WINDOWS.cmd', 'REPARER_ET_POUSSER.cmd']
- tools ps1 files: ['tools\\create_clean_archive.ps1', 'tools\\create_portable_bundle.ps1', 'tools\\diagnose_ollama.ps1', 'tools\\find_locked_runtime_files.ps1', 'tools\\hypersmart_simulation_poll_loop.ps1', 'tools\\ia_train_loop.ps1', 'tools\\install_external_github_repos.ps1', 'tools\\install_ollama_optional.ps1', 'tools\\install_portable_git.ps1', 'tools\\install_portable_runtime.ps1', 'tools\\push_github_safe.ps1', 'tools\\start_hypersmart_simulation.ps1', 'tools\\stream_loop.ps1', 'tools\\voir_dashboard.ps1']
- root archives forbidden count: 0

## Policy
- Documentation may mention forbidden terms only to prohibit them.
- Disabled stubs may contain refusal method names only when they fail closed.
- No operational mainnet, signature, private key, order or testnet executor is allowed.
