# Fusion #06 : Composio-HQ/polymarket-kalshi-arbitrage-bot (TS) — arb 15min Polymarket↔Kalshi
Source: https://github.com/Composio-HQ/... — détecte un écart de prix entre 2 venues, signale "buy".

## À GARDER / ADAPTER (status API + timing gate read-only)
- **A1. API de statut read-only** : `GET /health`, `GET /status` (derniers prix, **signal d'arbitrage courant**, trading activé ?, fenêtre de départ passée ?), `POST /poll/start` + `/poll/stop`. → ADAPT: notre API/dashboard read-only expose déjà status ; garder le **contrôle start/stop du scanner** + `current_signal` (qui peut être un `NoTradeDecision`).
- **A2. Timing gate "after N minutes from market start"** (évalue les signaux seulement après 8 min) → ADAPT: gate temporel d'éligibilité (analogue à notre fraîcheur ; utile pour des marchés à round/horaire).
- **A3. Forme de signal explicite** : `action`, `spreadCents`, `edge`, statut → KEEP (notre SignalCandidate/NoTradeDecision structuré).
- **A4. Poll interval configurable** (`POLL_INTERVAL_MS`) + cooldown entre achats → KEEP (intervalle borné + cooldown).

## BAN
`@polymarket/clob-client`, **ethers**, `POLYMARKET_PRIVATE_KEY`, proxy wallet, `buy_polymarket`/`buy_polymarket_late` (actions réelles), tradingEnabled=true, arbitrage cross-venue réel (DEFER multi-venue).

## Verdict
Petit repo (vendu "90% profitable" = marketing, ignorer). Valeur = confirmer **status API read-only + timing gate + start/stop scanner**. Peu de nouveauté.
