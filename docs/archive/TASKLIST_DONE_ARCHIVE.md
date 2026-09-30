# ARCHIVE DES TÂCHES TERMINÉES — avec leurs preuves

> Retirées de `docs/TASKLIST_ACTIVE.md` le 2026-07-21 parce que `DONE_VERIFIED` :
> codées, **branchées**, testées, prouvées par une mesure.

## Vérité du PnL

| tâche | preuve | date |
|---|---|---|
| Ledger append-only comme source unique du réalisé | `resume_depuis_ledger()` | 07/2026 |
| PnL par session (repart à zéro, historique conservé) | `session_id` sur chaque ligne | 20/07 |
| Latent de base séparé du net (fin du yoyo) | marquage MID, `carry_bases_courantes.json` | 20/07 |
| Funding **réglé** séparé de l'**estimé** | `funding_settlement.py`, 28 tests | 21/07 |

## Carry

| tâche | preuve | mesure |
|---|---|---|
| Anti-churn A1-A6 | 32 ouv. / 31 ferm. en 22,3 h → arrêté | −5 $ évités/jour |
| Marge dynamique (92 % du capital dormait) | `marge_par_position` | 75 $ → 1 175 $ de notionnel |
| Univers Unit (UBTC→BTC…) | `_apparier_spots` | 8 → 20 coins |
| Levier plancher 1,0/1,5x | `LEVIERS_A_ESSAYER` | HYPE débloqué |
| Sortie prise-de-profit | `SORTIE_PRISE_PROFIT_BASE` | +0,05 $ net |
| Allocation ∝ rendement net³ | 34 tests | corrélation −0,596 → positive, **+23,9 %** |
| Renfort sans churn (R1-R6) | 27 tests | grossir sans payer de sortie |
| Garde du plancher z-score | `facteur_zscore(z, funding)` | bruit au plancher neutralisé |
| Journal de scans + backtest paramétrique | 49 tests | 96 → ~2 900 lignes/jour |

## Arbitrage

| tâche | preuve | mesure |
|---|---|---|
| Correction du coût 4 jambes → 2 jambes | `COUT_AR_BPS 22 → 8` | seuil 35 → 15 bps |
| Étude de convergence **avant** les seuils | `arb_backtest.convergence` | −2,26 bps à 30 min |
| Cadence ×5 | launchers | 300 s → 60 s |

## Infrastructure et honnêteté

| tâche | preuve |
|---|---|
| Superviseur de collecteurs (relance les morts) | compteurs au rapport |
| Anti-orphelins (collecteurs meurent avec le moteur) | `collecteur_doit_vivre.py` |
| `TOUT-TESTER.cmd` — un seul lancement | 8 étapes + inventaire chiffré |
| Rapport du jour toutes les 6 h, écriture atomique | 12 sections |
| Registre des **lois mesurées** (13) | branché dans le chercheur de pépites |
| `AGENTS.md` remis à jour (13 jours de retard) | test qui exige sa date |
| Grinder/Sniper : statut réel prouvé | ledger : 0 ligne |

## Idées ENTERRÉES par la mesure (ne pas rouvrir sans donnée neuve)

Copy global (−7,97 bps / 24 133 signaux) · leader contrarien (−7,75 bps avant fill) ·
latence (courbe edge/horizon plate, −3,74 bps à 500 ms) · market-making dans le spread
(0/29) · spread = prix du risque (BTC 0,16 bps vs 3,0 bps de coût) · funding perp↔perp
(0/120) · couverture par actif corrélé · lead-lag BTC→alts (0/66) · sizing d'un rendement
négatif · z-score au plancher (−0,596).

Détail et conditions de réouverture : `docs/LOIS_MESUREES.md`.

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
