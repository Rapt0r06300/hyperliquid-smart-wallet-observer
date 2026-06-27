# HyperSmart WebSocket Monitor

Le monitor WebSocket est read-only et desactive par defaut.

Il prepare des subscriptions limitees:

- `allMids`;
- trades publics;
- user streams uniquement pour shortlist limitee.

Limites par defaut:

- 10 user subscriptions maximum;
- duree bornee obligatoire pour non dry-run;
- aucune execution;
- aucun endpoint trading.
# Realtime Freshness Guard

For selected wallets, real-time observation must stay fresh. HyperSmart now
contains `LivePositionFreshnessGuard`, a read-only guard that evaluates the age
of the latest position, fill or open-order update.

Policy:

- fresh wallet state can be used for research/paper observation;
- stale wallet state creates a `STALE_SIGNAL` no-trade decision;
- missing wallet state creates a `SOURCE_UNAVAILABLE` no-trade decision;
- the guard never executes an order and never signs anything;
- WebSocket user-specific observation remains limited to the configured
  shortlist and max 10 unique users.

This exists because following old leader positions is a major source of false
copy-trading results. HyperSmart refuses stale data instead of pretending it is
live.
