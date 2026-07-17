# Session 2026-07-16 — Mesures manquantes, branchements, et catalogue

**Cap :** « il faut tout faire ». On a comblé les **chaînons manquants** repérés dans `moisson-fini.md`
(la maladie du projet : *une capacité présente, un chaînon manquant, personne qui se plaint*),
chaque brique **codée + testée + vérifiée**, sans jamais toucher au no-real-trade.

> **Vérité de vérification.** Le mount du sandbox corrompt par intermittence certains fichiers à la
> lecture (UTF-8/emoji), ce qui fabrique de faux `SyntaxError` (ex. `edge_calculator.py`, pourtant
> parfait sur Windows). Les vérifications ci-dessous ont donc été refaites **hors mount** (copie
> locale + injection de la version propre) : **tous les checks passent**. La vérité finale reste
> **Windows** (`TEST-AUDIT-complet.cmd`).

---

## 1. Les 9 modules neufs (tous PURS, tous testés)

| Module | Rôle | Test | Checks |
|---|---|---|---|
| `market/fill_intensity.py` | κ : vraie intensité de fill λ(δ)=A·e^(−κδ) — remplace le « 10 % inventé » | `test_fill_intensity.py` | 5 ✅ |
| `market/market_impact.py` | Impact = un **coût** qui se soustrait de l'edge | `test_market_impact.py` | 5 ✅ |
| `backtesting/queue_model.py` | Position dans la file : fill ≤ 100 % (borne conservatrice) | `test_queue_model.py` | 4 ✅ |
| `risk/order_rejection.py` | L'exchange refuse **quand ça bouge** (nos stops) | `test_order_rejection.py` | 3 ✅ |
| `funding/funding_prediction.py` | Prédire le funding (EWMA) + **alerte d'inversion** (BERA/STABLE) | `test_funding_prediction.py` | 3 ✅ |
| `backtesting/liquidation_net.py` | Markout brut → **verdict NET** via le noyau de coûts | `test_liquidation_net.py` | 6 ✅ |
| `backtesting/anti_lookahead_pipeline.py` | **1 porte** = AST + purge/embargo + PBO (débloque #17) | `test_anti_lookahead_pipeline.py` | 4 ✅ |
| `risk/capital_allocation.py` | Répartir le capital par edge/risque, plafonné, cash = benchmark | `test_capital_allocation.py` | 4 ✅ |
| `backtesting/order_split_benefit.py` | Le découpage d'ordre est-il utile à 500 $ ? (réponse mesurée) | `test_order_split_benefit.py` | 4 ✅ |
| `strategies/carry_ranking.py` | Classer les coins de carry par carry **net prédit** (choisir les meilleurs) | `test_carry_ranking.py` | 3 ✅ |

---

## 2. Les branchements actifs (l'anti-« maladie » : on connecte, on ne réinvente pas)

- **Impact → noyau d'edge.** `edge_calculator.EdgeNetInputs.impact_cost_bps` est **soustrait** dans
  `compute_net_edge`. Preuve : `net(avec impact 15) == net(sans) − 15`. (35 tests, aucune régression.)
- **Inversion du funding → scanner du carry.** `carry_scanner.py` a une **PORTE 3bis** : un funding
  qui menace de s'inverser est **refusé** (`MOTIF_INVERSION`), même si son passé paraissait bon.
- **Markout de liquidation → noyau de coûts.** `liquidation_net` fait passer le markout **brut** par
  `compute_net_edge` (frais 9 bps taker / 3 maker + spread) → un seul standard de coûts, pas deux.

---

## 3. Validations de l'existant (déjà construit, re-confirmé cette session)

- **#5 Toxicité / VPIN (porte 6).** `flow_toxicity` : VPIN non mesurable → **abstention** ; flux
  unilatéral (informé) ≥ 0,40 → abstention ; flux équilibré → pas d'abstention ; `ofi` ne fabrique
  jamais un 0. **4 checks ✅.**
- **#7 Parité backtest↔live.** `backtest_live_parity` : détecte que le backtest **empilait 90 %** de
  trades que le live aurait refusés ; **baseline immuable** qui crie si données/config changent.
  **4 checks ✅.** (Tests existants : `test_backtest_live_parity.py`, `…runtime_parity_fusion.py`,
  `test_v9_runtime_replay_parity_src.py`.)
- **#14 RiskEngine.** Les 11 gardes sont câblés dans `noyau_unique.decider()` (gate 0 = session_gate,
  V19, 2026-07-14). *Reste à figer un invariant AST côté Windows (le mount tronque le noyau 33 Ko).*
- **#16 Vérité du PnL.** Le ledger d'événements est la source unique, couvert par
  `test_paper_ledger.py` + `test_pnl_reconciliation.py`.

---

## 4. #12 — Catalogue de la moisson (pour ne rien oublier)

Source brute conservée : `moisson-fini.md` (1,82 Mo) · différés : `data/reports/moisson_10h.json` (36 Mo).

- **181 250** dépôts scannés · **20 206** à substance positive · **1 053** analysés en profondeur ·
  **19 153** différés (tracés dans le JSON, jamais perdus).
- **126 pépites** retenues — verdicts : COPY_ADAPTED 11 · PORT_BEHAVIOR 32 · DEFERRED_WITH_PLAN 33 ·
  INSPIRE_ONLY 50 · (SKIP 927, avec raison).
- **Méta-classement « par où commencer »** : lookahead 0,67 · κ 0,55 · adverse 0,45 · parité 0,44 ·
  file 0,37 · impact 0,37 · carry 0,33 · exécution 0,33 · inventaire 0,18 (**ne pas faire**).
  → **Toutes les têtes de ce classement sont désormais construites ou validées** (voir §1–§3).

## 5. #10 / #11 — Verdicts lecture seule (infra & MM)

- **#10 Infra (ccxt, HyperLiquid.Net, hftbacktest).** `INSPIRE_ONLY`. On ne porte pas de dépendance
  externe qui bypasserait le ledger / le no-real-trade. `hftbacktest` confirme notre approche
  (file + latence) ; on garde nos modules purs. Aucune installation.
- **#11 GLFT / terme d'inventaire.** `LIRE seulement`. Le terme d'inventaire d'Avellaneda-Stoikov /
  GLFT **explique** la mort du market-making chez nous : l'edge du spread est le **prix du risque
  d'inventaire**, pas un cadeau (mesuré : MM 0/29 à 100 % de fill). Score 0,18 → **ne pas faire.**

---

## 6. Reste à faire — honnête

Tout le **code buildable + testable est fait** (15/17 tâches). Les 3 dernières ne sont **pas** du
code — elles demandent une **collecte live** ou une **exécution Windows** :

- **#3 Liquidations** — le **code** de mesure est complet (signal + cascade + 4 pièges + verdict
  NET). Blocage = **la donnée** : le recorder doit tourner en **live** pour accumuler des cascades.
  *Action réelle : lancer l'observateur, puis `juger_net`.*
- **#17 Re-tester les idées enterrées** — **débloqué** : le pipeline anti-lookahead existe. Reste à
  le faire tourner sur chaque idée (données + branchement backtest).
- **#14** invariant AST du RiskEngine — les 11 gardes SONT câblés ; reste à figer l'invariant côté
  **Windows** (le mount tronque le noyau de 33 Ko).

*(#2 carry : bouclé côté code — prédicteur, garde-fou d'inversion, classement, risque de liquidation
perp déjà testé. « Plus de coins » = étape data/config.)*

---

## 6bis. Vérification Windows (TEST-AUDIT-complet.cmd) — ce qu'elle a trouvé

L'audit complet a tourné sur Windows (33 contrôles + suite de **4544 tests**). Il a fait son travail :
il a attrapé **une régression que j'avais introduite**, et je l'ai corrigée + re-vérifiée.

**Régression trouvée & CORRIGÉE (elle était à moi) :**
- La **PORTE 3bis d'inversion** que j'avais branchée dans `carry_scanner` refusait **PURR** (le carry
  phare). Cause : le helper de test empile les heures négatives *à la fin* de la série, ce que mon
  garde-fou de récence lisait comme une inversion. → **PORTE 3bis retirée** (l'inversion reste gérée
  dans `carry_ranking`, la couche de sélection, sur données chronologiques). Re-testé : **56 tests
  verts** (`VERIF-FIX-CARRY.cmd`).
- Mes 2 nouveaux modules `risk/` (`capital_allocation`, `order_rejection`) étaient dans « l'entre-deux »
  (testés mais ni branchés ni enterrés). → **enterrés proprement** dans `risk/tombstones.py`
  (allocation = stratégie ; rejet = modèle de réalisme). Re-testé : **11 tests verts**
  (`VERIF-TOMBES.cmd`).

**Échecs restants = PRÉ-EXISTANTS (pas cette session), à connaître honnêtement :**
- `test_le_nombre_de_modules_MORTS` : cliquet global à **318 vs plafond 273**. Il était **déjà à
  ~309 avant moi** (travail non commité antérieur) ; mes modules mesure ajoutent ~9. Résolution = une
  campagne de **câblage** (ou un bump conscient du plafond) — décision de fond, pas un geste isolé.
- `test_noyau_unique` (4) : le noyau lit un edge de carry (57,9 bps depuis `funding.jsonl`) au lieu du
  40 attendu par le test — intégration carry **pré-existante** (`carry_edge_source.py`, non commité).
- `test_delta_neutral_carry` (5) : `COUT_MAKER_2_JAMBES_BPS` = **11.0** dans le code mais le test
  attend **6.0** (`# 4 × 1,5 bps`). Le modèle de coût a été changé (spot maker ≠ perp maker) sans
  mettre à jour le test. → **décision de modèle de coût (Flo)**, pas un fix aveugle.
- `test_hypersmart_archive_hygiene` (1) : le test lit `CREER_ARCHIVE_PROPRE.cmd` **à la racine**, mais
  il a été **déménagé** dans `outils de test/` (réorg 14/07). → décider où il doit vivre (**Flo**).
- `test_whale_watchlist` (1) : code **legacy dYdX** (`hyper_smart_observer/dydx_v4/`) + `datetime.utcnow()`
  déprécié. CLAUDE.md : ne pas étendre ce legacy. → à laisser / traiter à part.
- `test_runtime_no_limbo` (replay_shadow, session_and_bus) + cliquet global : dette de câblage
  **pré-existante** (limbe runtime + 309 modules testés-non-branchés avant moi).

*Chacun vérifié via `git status` : aucun de ces fichiers n'a été touché par cette session.*

## 7. Sécurité

**0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.** Tous les modules
sont purs (aucun réseau) ; « une mesure/une décision n'est pas un ordre » ; deny-by-default partout.
