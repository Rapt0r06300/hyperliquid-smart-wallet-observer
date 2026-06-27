# Fusion #08 : NYTEMODEONLY/polyterm — outillage agent-safe read-only (README volumineux)
Source: https://github.com/NYTEMODEONLY/polyterm (README ~80KB ; essence connue + résumé master plan §6.8).

## À GARDER / ADAPTER (agent-safe read-only) — DÉJÀ LARGEMENT IMPLÉMENTÉ chez nous cette session
- **A1. Manifest d'outils agent-safe** (read-only only) → FAIT: `agent_tools/readonly_manifest.py` + `schemas.py`.
- **A2. JSON Schemas par outil** → FAIT: `docs/schemas/*.schema.json` (status.read, wallet.leaderboard, decision_ledger.search, dashboard.export, source_health.read).
- **A3. `llms.txt` / `llms-full.txt`** (découvrabilité agent) → FAIT cette session (`docs/llms.txt`, `docs/llms-full.txt`).
- **A4. Doctor diagnostics** → on a `doctor`/`safety-audit`.
- **A5. SQLite local + exports JSON/CSV + historical replay** → on a (storage + backtest replay).
- **A6. Zero custody, input sanitization, no bare subprocess, graceful failure** → KEEP/vérifier (sanitation des entrées agent + échec gracieux ; pas de subprocess non borné).
- **A7. Serveur read-only type FastMCP** → ADAPT (DEFER léger): exposer le manifest en MCP read-only.

## BAN
Write/trade tools, Kelly real sizing, trade links, custody.

## Verdict
polyterm = la "checklist agent-safe". On a déjà couvert l'essentiel cette session (manifest, schémas JSON, llms.txt, doctor, graceful failure). Reste optionnel : serveur MCP read-only + tests d'input-sanitization explicites.
