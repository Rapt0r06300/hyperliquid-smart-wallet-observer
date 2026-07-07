# HyperSmart — Feuille de route complète V1 (2026-07-07)

Cap produit: un bot d'observation Hyperliquid qui prouve, en paper honnête,
qu'un style "grinder" (beaucoup de mini-positions copy wallet + arbitrage)
produit un PnL net positif reproductible — puis le porter vers le testnet.

Deux modes cohabitent, un seul ledger arbitre:
- **SNIPER**: peu de trades directionnels copy, edge net élevé après coûts.
- **GRINDER**: volume de petites positions à coût unitaire quasi nul
  (funding delta-neutre, fills maker, copy multi-leaders proportionnel).

Règles transverses non négociables (toutes les phases):
- paper-only / read-only, 0 ordre réel, 0 clé, 0 signature;
- aucune donnée fabriquée: donnée manquante → NO_TRADE;
- chaque flag est réversible par env; activation par défaut UNIQUEMENT
  après replay A/B net de frais positif (jamais "au feeling");
- chaque perte doit être explicable par le ledger (trade, coûts, cause).

---

## Phase 0 — Socle livré (FAIT, commits ff7aeec + b15b488)

- Bus GitHub coupé: scope 9 repos prioritaires par défaut, double verrou
  de matérialisation directe, matrice de distillation.
- Replay A/B sur logs frais: plancher notional 40 activé (le sous-ensemble
  "preuve mesurable + taille suffisante" = seul rentable: +0.11 vs -1.77).
- Sizing whale consensus (multiplicateur ≤1.0, flag OFF).
- Brique maker: style exécution maker + adverse selection configurable.
- Brique funding-arb paper: paires delta-neutres multi-symboles, accrual
  horaire au ledger (OPEN/ACCRUAL/CLOSE sans double compte).
- Preset GRINDER commenté dans le launcher. 48 tests verts.

## Phase 1 — Validation runtime du socle (J+0 → J+3)

Objectif: prouver que le nouveau code vit correctement en session réelle.

1. Redémarrer `LANCER_HYPERSMART.cmd` (charge caps 12/400, plancher 40,
   export `simulation_pnl_ledger_latest.jsonl`).
2. Vérifier en session: refus `PAPER_NOTIONAL_BELOW_MINIMUM` et
   `PORTFOLIO_*` visibles au ledger; exposition ≤ caps; plus de
   "34 moteurs actifs" affichés.
3. Décommenter le bloc `MODE GRINDER` et lancer une session de test 48-72h.
4. Surveiller: événements `FUNDING_ARB_OPEN/ACCRUAL/CLOSE`, raisons de
   refus funding (`FUNDING_SPIKE_UNSTABLE`, `FUNDING_EDGE_TOO_SMALL`…),
   fraîcheur des données funding.

**Gate de sortie**: 48h sans anomalie ledger (pas de doublon, pas de PnL
inexpliqué, pas de position fantôme), données funding fraîches en continu.

## Phase 2 — Calibration A/B du grinder (S1 → S2)

Objectif: activer par défaut UNIQUEMENT ce qui gagne, aux bons seuils.

1. A/B coût d'exécution: mêmes signaux, `EXECUTION_STYLE=taker` vs `maker`
   (+ adverse selection 2-4 bps) → comparer PF net.
2. Funding-arb: edge réalisé vs théorique par paire; ajuster
   `MIN_EDGE_BPS_H` (2.5 par défaut), `MAX_PAIRS` (5), notional/jambe (25).
3. Multi-entrées copy: 1 vs 3 entrées distillées simultanées, whale sizing
   ON vs OFF → PF net et drawdown.
4. Passer en défaut launcher les gagnants; documenter les perdants
   (docs/release/REPLAY_AB_*.md).

**Gate**: PF net > 1 sur le périmètre grinder sur ≥ 48h de données, ou
révision des seuils avec justification chiffrée. Pas de PF > 1 → on
n'active rien et on documente pourquoi.

## Phase 3 — Copy multi-leaders renforcé (S2 → S3)

Objectif: le copy qui marche = leaders swing, fraîcheur mesurée, sélection
par performance nette.

1. **Filtre leaders swing** (nouvelle brique): estimer le holding médian
   par leader depuis ses fills; refuser la copie des scalpeurs
   (holding < 15 min) — la latence HL 200-500 ms rend leur copie perdante.
2. **Budget latence par leader** (idée n°2 matrice, repo 15): âge du fill
   leader mesuré à l'entrée; rejet stale déjà présent → ajouter la mesure
   par wallet au dashboard (audit de dégradation de copie).
3. **Sélection par PF net du leader** (leader_pnl_tracker existant):
   shortlist = leaders à PF net > 1 sur fenêtre glissante, pas au volume.
4. Monter progressivement `DISTILLED_MAX_PAPER_ENTRIES` 3 → 5 si le PF
   tient; floor $10/ordre (contrainte HL réelle).

**Gate**: PF net copy > 1 et winrate évènementiel stable sur ≥ 1 semaine,
avec ≥ 30 trades clos (échantillon minimal décent).

## Phase 4 — Arbitrage élargi (S3 → S4)

Objectif: ajouter des sources de PnL non-directionnelles, une par une.

1. **Cross-venue discrepancy** (repo 28): aujourd'hui evidence read-only;
   matérialisation paper seulement si les 2 sources sont live et le spread
   net > coûts conservateurs (gate existant `DIRECT_ARBITRAGE_MIN_SPREAD_BPS=30`).
2. **Triangulaire** (repo 34): primitives présentes; même règle.
3. **Grid/MM paper cappé** (repos 35/33 + `market_making_paper`): profil
   passivbot SANS martingale illimitée (cap re-entrées, cap exposition);
   uniquement si les fills maker sont validés en Phase 2.

**Gate par famille**: replay A/B positif net de frais avant matérialisation
par défaut. Une famille perdante reste en shadow/evidence.

## Phase 5 — Robustesse & vérité (continu, prioritaire dès S2)

1. Persistance des paires funding au restart (SQLite/UiState au lieu du
   store process-local) — actuellement remises à plat.
2. Modéliser le résidu de PnL prix sur les paires (divergence des jambes)
   au lieu de supposer la couverture parfaite.
3. Dashboard: panneaux SNIPER vs GRINDER séparés (même ledger), compteur
   de refus par raison (voir quel gate serre — anti-blocage).
4. Audit hebdo: `logs-analyze` + `ledger-pnl-calibration` +
   `closed-ledger-replay`; toute perte inexpliquée = bug à corriger.

## Phase 6 — Cap testnet (après PF net > 1 stable 2-4 semaines)

Conforme à l'addendum CLAUDE.md 2026-07-04:
1. `mainnet_readonly_observer` → `decision_engine` (evidence chain) →
   `testnet_executor` verrouillé (`TESTNET_ONLY=true`,
   `CONFIRM_TESTNET_EXECUTION=true`, caps notional/positions).
2. `TestnetExchangeAdapter` + fake adapter pour les tests; aucun secret,
   aucune signature réelle (sprint futur explicite et audité si besoin).
3. Comparer PnL testnet vs paper (liquidité testnet ≠ mainnet, l'écart
   est une donnée, pas un échec).

**Gate d'entrée**: PF net paper > 1 stable sur 2-4 semaines, drawdown
contenu, audit sécurité vert.

---

## Tableau de bord de pilotage (à chaque phase)

| Métrique | Cible | Source |
|---|---|---|
| Profit factor net | > 1.0 (le juge de paix) | closed-ledger-replay |
| Fee drag ratio | < 0.35 (vs 0.59 mesuré) | ledger-pnl-calibration |
| PnL net médian / trade | > 0 | ledger |
| Trades/jour (grinder) | en hausse SI PF tient | ledger |
| Drawdown max session | < garde-fou env | equity history |
| % refus par raison | aucun gate ne refuse >90% en silence | input_diagnostics |

## Ce qu'on ne fera PAS (et pourquoi)

- Copier des leaders scalpeurs (latence 200-500 ms = perte structurelle).
- Rebrancher le bus GitHub direct comme mode normal (mesuré: PF 0.61).
- Marteler des micro-trades taker (frais > brut, mesuré).
- Activer un flag sans replay (règle produit).
- Marketing de PnL: aucun chiffre promis, jamais.


---

## Annexe A — Couverture des idées GitHub (audit 2026-07-07, rien d'oublié)

| Source | Meilleure idée | Où / tâche | Statut |
|---|---|---|---|
| 17 whale-mirror | consensus + sizing proportionnel | `whale_consensus_sizing` (livré) + T16 | PORTÉ (flag) |
| 17 whale-mirror | scoring wallet récence/winrate | T20 + T33 | PLANIFIÉ |
| 15/16 solana copy | budget latence, session logs | T19 | PLANIFIÉ |
| terauss copy | hot path multi-traders, dedupe, conflits | conflict_resolver (existant) | FAIT |
| 21 tony v4 | exits SL/TP/trailing/max-hold + risk flags | T32 | PLANIFIÉ (replay-gated) |
| 22 freqtrade | dry-run, walk-forward, hyperopt, anti-lookahead | T29 | PLANIFIÉ |
| 22 freqtrade | trailing_stop_positive 0.5% | T32 | PLANIFIÉ |
| 23 octobot / 35 passivbot | optimiseur évolutionnaire de configs | T29 | PLANIFIÉ |
| 35 passivbot | grid contrarian cappé (sans martingale) | T23 | PLANIFIÉ |
| 28/29 jackhuang | scanner spread cross-venue + alertes | T21 | PLANIFIÉ |
| 30 rustjesty | basis/funding dual-leg, atomicité, min_profit_usd | T35 (+ moteur livré) | PARTIEL |
| 32 gajesh funding | seuils entrée/sortie, anti-spike 2σ | `funding_arb_paper` (livré) + T15 | PORTÉ (flag) |
| 32 gajesh funding | payment tracking réel + drift detection | T30 | PLANIFIÉ |
| 32 gajesh funding | crash recovery (persistance état) | T24 | PLANIFIÉ |
| 33 hummingbot | abstraction connecteurs, caps inventaire | connectors/risk (existant) | FAIT |
| 33 hummingbot | PMM/XEMM market making | T23 | PLANIFIÉ |
| 34 drakkar | cycles triangulaires + coût de chemin | T22 | PLANIFIÉ |
| 31 arbibot | event queue faible latence, arrêt propre | realtime V16 (existant) + T35 | PARTIEL |
| 36/37 interexchange | discrepancy cross-source | T21 | PLANIFIÉ |
| 38 chainstacklabs | grid presets, --validate, testnet-first | doctor/T23/T28 | PARTIEL |
| 09 mlmodelpoly | order-book imbalance 0.10 + cooldown 2s | T34 | PLANIFIÉ |
| 11 prediction backtesting | replay sans lookahead, rapports reproductibles | closed-ledger-replay (existant) | FAIT |
| 13 polymarket agents | IA analyste shadow-only | ml/ V13 (existant, non-autoritaire) | FAIT |
| 14 lightweight-charts | charts ledger-first | UI (existant) | FAIT |
| 01-10, 12, 18-19, 24-27 | runtimes Polymarket/Kalshi/Solana | hors venue | SKIP_WITH_REASON |
| CODEX_GOAL item 2-3 | régime marché + volume z-score dans edge | T31 | PLANIFIÉ |
| CODEX_GOAL item 4 | winrate leader par coin | T33 | PLANIFIÉ |
| CODEX_GOAL item 5 | sizing par paliers de confiance | whale sizing (livré) | PORTÉ (flag) |
| CODEX_GOAL item 6 | gros trades WS >$50k comme boost | T34 | PLANIFIÉ |
| Web/X 2026 | HIP-4 binaires (hedge même marge) | T37 | EXPLORATION |
| Souci Flo anti-blocage | coût des refus chiffré | T36 | PLANIFIÉ |

Toute idée non listée ici = SKIP volontaire (venue incompatible ou doublon),
consigné dans `docs/research/GITHUB_IDEAS_TO_MODULES.md` et
`GITHUB_PORTAGE_DECISIONS.md`.
