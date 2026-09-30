# Portage — `cobusgreyling/loop-engineering` → HyperSmart Observer (2026-07-22)

Source analysée sur demande de Flo (tweet @zaynmcps → `github.com/cobusgreyling/loop-engineering`,
projet réel de Cobus Greyling, ~5,5k ⭐). **Ce n'est pas un système de trading** : c'est un cadre
pour *orchestrer des agents de codage IA* (« stop prompting — design the loop — get a score »),
avec des CLI npm (`loop-init`, `loop-audit`, `loop-cost`, `loop-context`, `loop-worktree`,
`loop-gate`…) et 7 patterns (Daily Triage, PR Babysitter, CI Sweeper…).

## Décision de portage (règles CLAUDE.md « Portage GitHub »)

| Idée source | Verdict | Raison |
|---|---|---|
| **`loop-audit` : score de maturité unique + échelle d'autonomie L0→L3** | **COPY_ADAPTED** | Comble un vrai trou : on a tous les signaux épars (tests, câblage, sécurité, fraîcheur, PnL) mais **aucun score unique** ni échelle d'autonomie formelle. Porté en `ops/loop_readiness.py`, lentille trading. |
| Framework npm (`loop-init` scaffolding : `STATE.md`, `LOOP.md`, `gate.yaml`, `skills/`) | **SKIP_WITH_REASON** | 3ᵉ architecture qui entre en conflit avec CLAUDE.md / `memory/` / `TOUT-TESTER` ; exécute du code npm non audité. Violerait « ne pas introduire de 3ᵉ architecture ». |
| Patterns PR Babysitter / CI Sweeper / Dependency Sweeper / Fleet | **SKIP_WITH_REASON** | Conçus pour des équipes livrant du code applicatif avec CI/CD et N contributeurs. HyperSmart = bot de recherche solo. Hors-sujet. |
| `memory-engineering` (tiers + budget de rappel) | **DEFERRED_WITH_PLAN** | Notre `MEMORY.md` grossit ; une structure en tiers pourrait aider. Pas ce sprint. |
| `loop-context` / `loop-worktree` | **INSPIRE_ONLY** | Coupe-circuit de session & worktree-par-tentative : pratiques d'atelier, pas du code bot. |

Cousin déjà porté : [`ops/lecons_du_ledger.py`](../../src/hl_observer/ops/lecons_du_ledger.py)
(autre source « loop engineering », 20/07 — la boucle perte → leçon → règle).

## Ce qu'on a livré : `ops/loop_readiness.py` (score BOT-READY)

Adaptation TRADING de `loop-audit`, deny-by-default. **Le no-real-trade est un GATE DUR**, pas
une dimension pondérée : la moindre brèche force le grade **F** et le niveau **N0**.

**L'échelle d'autonomie = notre ladder de sécurité** (addendum 2026-07-04), pas la leur :

| Niveau | Sens | Conditions |
|---|---|---|
| `N0_OBSERVE` | mainnet lecture seule (plancher) | toujours atteint |
| `N1_PAPER_DECIDE` | décision locale + simulation paper | sécurité ∧ tests verts ∧ PnL réconcilié ∧ données fraîches |
| `N2_TESTNET_VERROUILLE` | testnet fausse monnaie, tous verrous | N1 ∧ portes de coût ∧ kill-switch ∧ journal ∧ `REAL_MAINNET_TRADING=false`+`TESTNET_ONLY=true` |

**Il n'existe AUCUN niveau « réel ».** La fonction ne peut pas l'émettre — plafond codé en dur.
Ce module **renforce** le no-real-trade : il ne débloque jamais rien, il refuse de déclarer prêt.

Dimensions pondérées (somme 100), poids pensés trading : sécurité 18 · vérité du PnL 16 ·
fraîcheur 16 · tests 14 · portes de coût-net 12 · kill-switch 10 · câblage 8 · journal 6.

Les invariants gardés par des tests nommés (vérité du PnL → `test_pnl_reconciliation` ; portes de
coût → `test_carry_benchmark_gate`+`test_arb_cout_all_in` ; kill-switch → `test_circuit_breaker`+
`test_risk_guards_no_limbo`) sont **dérivés d'une suite verte** — c'est leur preuve, pas une
supposition. Suite rouge → deny-by-default (score conservateur).

### Câblage (jamais un orphelin)
- `tools/lanceur_tout_tester.py` imprime le bloc BOT-READY à la fin de chaque `TOUT-TESTER`
  (try/except : un bonus d'affichage ne fait jamais échouer l'audit).
- `tools/bot_ready.py` : commande autonome `python tools/bot_ready.py` (`--ecrire` → `BOT_READY.md`).
- Source unique du barème : `hl_observer.ops.loop_readiness` (le tool et le lanceur y délèguent).

### Bonus : angle mort d'audit corrigé
En câblant, on a découvert que `audit/cablage.py` ratait les tools lancés via l'idiome Windows
`python "%~dp0tools\x.py"` (préfixe `%~dp0`) — donc `lanceur_tout_tester.py` lui-même passait
pour « non démarré ». Regex corrigée + test (`test_un_lanceur_avec_prefixe_pdp0_est_reconnu`).

## Tests
`test_loop_readiness.py` (13) · `test_bot_ready.py` (5) · `test_audit_cablage.py::test_un_lanceur_avec_prefixe_pdp0_est_reconnu`.
Cliquet anti-orphelin (`test_risk_guards_no_limbo`) : vert (≤ 285).

## Ce que ça N'apporte PAS
Aucun edge de trading, aucun code dans les moteurs (edge/carry/arbitrage/copy). Ça ne bouge pas
le PnL paper. Valeur = **visibilité** (un score pour Flo) + **discipline d'autonomie** arrimée au
no-real-trade.

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
