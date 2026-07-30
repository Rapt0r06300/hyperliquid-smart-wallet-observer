# HYPERSMART — RÉSULTAT DU ONE-RUN (ALPHA-5 → bloc 20)

## 1. HEAD avant / après

- **Avant** : `15071edc10169dc4ea32816632ec5c78eee5ad85`
- **Après** : `3950b95`
- Branche : `main`, sans branche annexe, sans réécriture d'historique, sans force.

## 2. Bugs trouvés, avec cause racine

| Bug | Cause racine | Correction |
|---|---|---|
| `manifeste_campagne` annonçait un arbre **propre** quand `git` ne répondait pas | un `subprocess` en échec rendait `""`, **indistinguable** de la sortie vide d'un arbre propre ⇒ `reproductible=True` à tort | tri-état `True/False/None`, `reproductible=False` si inconnu, kill non bloquant |
| `market_truth` (1 145 lignes) sans aucun appelant de production | module écrit **et testé**, jamais branché — maladie « testé-seulement » du projet | étape `market_truth_replay` enregistrée dans le lanceur d'analyse officiel |
| Mon propre diagnostic : `pnl_improvement_lab` classé orphelin | j'ai cherché les appelants par `import` seulement, alors qu'il est lancé en **sous-processus** | méthode corrigée ; documenté pour ne pas le refaire |
| `test_idea78` figeait la suite complète | `git status` sans garde sur un dépôt de 50 Go, et mes runs en arrière-plan tués par le sandbox | timeout + kill non bloquant ; runs au premier plan |

## 3. Fichiers créés dans ce run

`src/hl_observer/experimental/cross_venue_conditions.py` · `src/hl_observer/arbitrage/nbbo_synthetique.py` ·
`src/hl_observer/experimental/metaorder_toxicite.py` · `src/hl_observer/copying/leader_proportional_sizing.py` ·
`src/hl_observer/ops/economic_revalidation.py` · 6 fichiers de tests ·
4 documents d'audit (`DEEP_AUDIT`, `MASTER_WIRING_EVIDENCE`, `SIMULATION_TRUTH`, `EXTERNAL_IDEAS`) ·
`runtime/reports/economic_revalidation.json`.

## 4. Avant → correction → preuve

| Avant | Correction | Preuve |
|---|---|---|
| Lead-lag cherché globalement | 12 conditions causales pré-enregistrées + embargo + tous les essais comptés | embargo 5 s : 40 chocs → 8 ; KILL conservé dans la population DSR |
| Écart de mid pris pour un arbitrage | NBBO **directionnel** : routes achat/vente séparées | 2 venues à ~500 bps d'écart de mid ⇒ `AUCUN_CROISEMENT` |
| Rien ne mesurait l'arrivée tardive | profondeur reconstruite **alors que le prix est déjà parti** | +30 bps de déplacement ⇒ `en_retard=true` |
| Sizing sans dénominateur | `min(capacité, budget, equity × clip(delta/NAV))` | NAV absent ⇒ `SIZING_NON_MESURABLE`, 0 position |
| Parité replay/forward non prouvée | prefix stability sur `market_truth` | bande tronquée = bande complète ; seules `session_id`/`last_event_hash` diffèrent |
| PnL sans dénominateur explicite | 4 ROI + enveloppes BASE/P95/P99/OPTIMISTIC | 20 tests analytiques (0 frais + prix plat = 0 ; frais seuls = perte exacte) |

## 5. Moteurs réellement actifs et leur chaîne

- **Runtime** (`LANCER_HYPERSMART.cmd`) : profil **CORE = `allMids` + `BBO`** →
  `collecter_bbo` (tick_dataset + feed_quality + market_events) → moteur/dashboard 8794.
- **Analyse** (`ANALYSER_BACKTESTS_REPLAYS.cmd`) : `historical_analysis_suite`, **12 étapes**, dont
  `market_truth_replay` (4ᵉ) et `pnl_improvement_lab`.
- **Moteur de fill unique** : `market_truth` (canonicalisation → gate → replay exécutable → ledger).

## 6. État des 91 idées + HS-070→100 + dette

Détail : `docs/audit/HYPERSMART_MASTER_WIRING_EVIDENCE_20260729.md`.

- Dette mesurée au HEAD : **101 orphelins · 372 testés-non-branchés · 143 outillés · 1 interrupteur mort ·
  62 vivants · 0 illisible** ; cliquet `PLAFOND_DETTE = 61`.
- **Non résorbé par ce run** : les 372 testés-non-branchés. Le dire est le seul choix honnête.
- IDEA 9/10/11/36/71/78-80 protègent encore depuis le **legacy** ⇒ `TODO_ACTIVE`, pas `DONE`.
- HS-070→100 : **`A_REVALIDER` en bloc** — je n'ai pas rejoué les 31 preuves ici.

## 6bis. SHA créés dans ce run

`33df446` ALPHA-5 · `e50382c` ledger · `318887c` ALPHA-6 · `2aaa525` ledger · `ebf291e` ALPHA-7 ·
`b53101b` ledger · `9209ab6` ALPHA-8 · `f496448` ledger · `65b9255` bloc 17 · `3dc7d9c` ledger ·
`0420753` bloc 18 · `b1cb828` ledger · `5d4be75` bloc 19a · `6c9cc84` bloc 19b · `a230469` preuves
runtime · `3950b95` rapport final.

## 7. Tests

- **114 tests** des blocs de ce run, tous verts (ALPHA-5 17 · ALPHA-6 15 · ALPHA-7 17 · ALPHA-8 22 ·
  bloc 17 11 · bloc 18 20 · étape market_truth 12).
- Non-régression rejouée : cross-venue (111), metaorder (29), market_truth (34), cohortes/consensus (30),
  lanceurs + sécurité (61), blocs 1→16 (149).
- **Sécurité : `safety-audit` et `audit-safety` = 8/8 `ok`.** `doctor` 9/10 — l'unique `FAIL`
  (`python_3_11_plus`) est le Python 3.10 du sandbox, pas le dépôt.
- ⚠️ **La suite complète (6 383 tests / 969 fichiers) n'a PAS été exécutée ici.** Chaque appel du sandbox est
  plafonné à ~44 s et 25 fichiers dépassent déjà ce budget. Conformément à la loi du projet
  (« la vérité est Windows »), la suite complète doit être lancée sous Windows :
  `set PYTHONPATH=src && python -m pytest -q`.

## 8. Mesures économiques réelles

| Stratégie | Statut | n | net USD | bps/trade | PF | max DD | ROI equity |
|---|---|---:|---:|---:|---:|---:|---:|
| `raw_probe` | MESURE | 19 | **-0,168** | **-5,88** | 0,66 | -0,24 | -0,017 % |
| `carry_paper` | AUCUN_EPISODE_MESURABLE | 0 | — | — | — | — | — |
| `experimental_paper_v2` | LEDGER_ABSENT | — | — | — | — | — | — |

Enveloppes `raw_probe` : `ADVERSE_P95` **-0,276** · `ADVERSE_P99` **-0,384**.

**Aucune stratégie n'est positive.** Le seul chiffre mesurable est négatif après coûts, cohérent avec la loi
déjà établie du projet (edge de copie négatif). Aucun résultat positif n'a été fabriqué, et aucun n'est promis.

## 9. Ce qui reste BLOCKED_DATA — et le producteur en place

| Bloqué | Manque | Producteur |
|---|---|---|
| PnL carry | prix exécutables (`price: None` × 100) | `carry-feeder` — **à réparer**, il écrit sans prix |
| Capacité par épisode | profondeur L2 jointe aux ledgers | `collecter_carnet` ✔ |
| ALPHA-5 sur données réelles | tape L2 longue par condition | `collecter_lab_microstructure` ✔ |
| ALPHA-8 sizing | NAV point-in-time des wallets | `collecter_vaults` (vaults seulement) |
| `mid equity` vs `liquidatable equity` chiffré | carnets joints aux épisodes historiques | `collecter_carnet` ✔ |

## 10. Les 3 prochaines expériences, classées par espérance nette / capacité / preuve

1. **Réparer le producteur carry** (écrire prix + notionnel au ledger). Coût quasi nul, débloque 190 lignes
   déjà collectées et rend une stratégie entière mesurable. Rien ne se classe tant qu'on ne peut pas mesurer.
2. **Joindre la profondeur L2 aux épisodes** pour renseigner `capacite_usd` et `fill_ratio`. Sans capacité,
   tout classement de stratégies est une extrapolation.
3. **Campagne ALPHA-5 conditionnée sur tape réelle** — l'instrument, l'embargo et le registre d'essais sont
   prêts ; il manque la donnée, pas le code. À juger sur l'IC bas OOS, jamais sur le PnL brut.

Classement fondé sur ce qui **débloque une mesure**, pas sur une intuition d'edge.

## 11. Limite majeure

**Rien n'a été exécuté sous Windows.** Ni `LANCER_HYPERSMART.cmd self-test`, ni
`ANALYSER_BACKTESTS_REPLAYS.cmd full`, ni la suite pytest complète. Le sandbox est Linux/Python 3.10.
Aucun « PRÊT À LANCER » n'est prononcé ici.

---

`Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.`
