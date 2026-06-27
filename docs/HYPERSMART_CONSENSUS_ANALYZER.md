# HyperSmart Consensus Analyzer

Consensus means multiple qualified wallets align on the same coin and direction
inside a short fresh window.

Rules:

- consensus alone never creates a trade;
- `edge_remaining_bps` remains mandatory;
- crowding can penalize the signal;
- low-quality wallets must not dominate high-quality wallets.

Current active simulation groups consensus positions locally and keeps them
read-only.

