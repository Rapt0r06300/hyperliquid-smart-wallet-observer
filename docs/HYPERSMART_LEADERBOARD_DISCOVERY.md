# HyperSmart Leaderboard Discovery

La discovery leaderboard selectionne uniquement des adresses completes:
`0x` + 40 caracteres hexadecimaux. Les adresses tronquees avec `...` sont
rejetees avant toute candidature.

Filtres Batch 1:

- `min_history_days = 7`;
- `min_closed_pnl_points = 10`;
- concentration PnL;
- one-big-win risk;
- drawdown max;
- consistency score;
- per-coin stability;
- execution quality;
- sample confidence;
- copyability.

Sorties:

- `data/leaderboard_shortlist.json`;
- table SQLite `leaderboard_shortlist`;
- statuts `SHORTLISTED`, `REJECTED`, `INSUFFICIENT_DATA`, `WATCH_ONLY`.

Import local de candidats:

```powershell
python -m hyper_smart_observer.app.main --write-shortlist-template data\reports\leaderboard_candidates_template.csv
python -m hyper_smart_observer.app.main --build-shortlist-file config/leaderboard_candidates.example.csv
python -m hyper_smart_observer.app.main copy-preflight --network-read
```

Formats supportes:

- CSV avec colonnes de metriques;
- JSON liste de candidats ou objet `{ "candidates": [...] }`;
- TXT avec une adresse par ligne.

Si un TXT ne contient que des adresses, HyperSmart ne complete pas les
metriques: les wallets sans historique/closed PnL restent refuses ou
insuffisants. Cette regle evite de transformer une adresse vue dans un explorer
en leader exploitable sans preuve.

Le preflight copie ne lance aucun reseau. Il verifie la shortlist, signale les
adresses invalides, affiche les endpoints `/info` qui seraient appeles et borne
le run a `HYPERSMART_COPY_MAX_LEADERS_PER_RUN=3` leaders par defaut.

Raisons de refus:

- `TRUNCATED_ADDRESS_REJECTED`;
- `INVALID_ADDRESS_REJECTED`;
- `INSUFFICIENT_HISTORY`;
- `INSUFFICIENT_CLOSED_PNL`;
- `PNL_CONCENTRATION_TOO_HIGH`;
- `ONE_BIG_WIN_RISK`;
- `LOW_CONSISTENCY`;
- `MAX_DRAWDOWN_TOO_HIGH`.
