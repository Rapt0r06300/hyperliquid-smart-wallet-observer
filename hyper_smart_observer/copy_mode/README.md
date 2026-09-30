# HyperSmart Copy Mode

Copy mode is a local research observer. It implements the three-job architecture
from the product research README:

1. leaderboard shortlist;
2. dry-run copy loop observing deltas;
3. reports/dashboard/no-trade output.

It never creates orders, never signs anything, never connects a wallet and never
enables mainnet. Accepted candidates are only eligible for local paper/mock-USDC
simulation after `edge_remaining_bps` is measurable and above threshold.
