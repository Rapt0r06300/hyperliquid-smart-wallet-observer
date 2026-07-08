# OBJECTIF — HyperSmart Observer

> Remplace les anciens prompts `CODEX_*` (agent précédent). **Sources de vérité :**
> règles = `CLAUDE.md` · état/roadmap/méthode = `docs/ETAT_ET_FEUILLE_DE_ROUTE.md`.

**But.** Observer Hyperliquid mainnet en **lecture seule**, scorer les wallets smart-money
(baleines = meilleur PnL/ROI en priorité, sans délaisser les autres), et **simuler en paper
local** un bot **copy-trading + arbitrage** style « grinder » (beaucoup de petites positions
propres, marge $50 × levier 10 = notional $500 → PnL en dollars réalistes). Cible ultérieure :
décision locale → exécution **testnet uniquement**, jamais mainnet.

**Ligne rouge.** TOUT est autorisé SAUF l'exécution réelle : aucun ordre réel, aucun argent réel,
aucune clé privée/seed/signature, aucun dépôt/retrait. Un signal n'est jamais un ordre.

**Méthode.** Inspecter git → comprendre l'archi → protéger le local → documenter → coder proprement
(petits modules sous `src/hl_observer`) → tester → vérifier no-real-trade. **Moins de trades, plus
propres** ; juger au profit factor ; **jamais** promettre un PnL ; vérité des données (ledger).

**En cours.** Run 48h qui enregistre des données replay valides → ensuite recherche massive de
scénarios (`docs/REPLAY_SCENARIO_SEARCH.md`) pour trouver le réglage le plus robuste (train/test,
anti-overfit), puis l'appliquer.
