# HyperSmart Security Audit Deep

Generated: 2026-07-22T19:05:10.496454+00:00

## Findings
- OK `no_exchange_path`: matches=0
- OK `no_signature_calls`: matches=0
- OK `no_operational_order`: unexpected_matches=0, locked_refusal_stubs=0
- OK `no_private_key_config`: No private key material is loaded in HyperSmart config.
- OK `database_hygiene`: No HyperSmart DB configured under logs; runtime DB files excluded from archives.
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
- src/hl_observer scanned keys: not present or no scanner output
- root cmd files: []
- tools ps1 files: []
- root archives forbidden count: 0

## Policy
- Documentation may mention forbidden terms only to prohibit them.
- Disabled stubs may contain refusal method names only when they fail closed.
- No operational mainnet, signature, private key, order or testnet executor is allowed.
