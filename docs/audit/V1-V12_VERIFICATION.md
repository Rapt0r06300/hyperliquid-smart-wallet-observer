# CLUSTER V (V1–V12) — VÉRIFICATION du chemin LIVE

**Date : 2026-07-18.** Demande de Flo : *« fais V1 jusqu'à V12 ».* Ce cluster ne code pas de
feature : il **vérifie que le chemin de décision LIVE est honnête**. Discipline dure (héritée de
V11) : *un contrôle qui ne pourrait pas échouer est un contrôle vide.* Chaque test ci-dessous est
construit pour **échouer si la propriété est violée** — et on l'a **prouvé par mutation** (V11).

Harnais neuf : `tests/test_v_cluster_verification.py` (14 contrôles, tous verts). Preuve de
mutation en mémoire : neutraliser le garde de fraîcheur fait bien disparaître le refus
`SIGNAL_TROP_VIEUX` → le contrôle correspondant basculerait en ÉCHEC. Vérités déléguées aux tests
existants (25 verts) là où elles les couvrent déjà. 100 % lecture, aucun ordre.

| # | Propriété vérifiée | Comment | Statut |
|---|---|---|---|
| **V1** | Chaque garde/porte est ATTEINT sur le chemin LIVE | AST : `estimate_edge_net_v12`, `appliquer_filtres`, `_appliquer_gardes`, `_etat_moteur`, `_facteur_sizing` tous **appelés** dans la porte | ✅ VÉRIFIÉ (sandbox) |
| **V2** | Aucun plancher/seuil à 0.0 ou désactivé en LIVE | Fait en session antérieure (invariant `test_v2_v3_edge_no_fail_open`) : plancher 30, coûts requis→NO_TRADE, jamais mainnet | ✅ DÉJÀ FAIT |
| **V3** | Coûts RÉELS et non nuls dans l'edge LIVE | Défauts config `spread/slippage/fee > 0` ; un coût **absent → NO_TRADE** (on ne devine pas) | ✅ VÉRIFIÉ (sandbox) |
| **V4** | Unités : frais non doublés, funding 1h vs 8h | `total_cost = somme UNIQUE` des composantes ; `fee` compté **une** fois. Unité funding (bps/h) : garde-fou déjà en place côté carry (règle « on ne CONVERTIT jamais un taux »), cité | ✅ VÉRIFIÉ (frais) · 🟡 funding = revue+tests carry |
| **V5** | L'edge est SOUSTRAIT et UTILISÉ (pas jeté) | `net = gross − total_cost` (exact) ; `net<0 → jamais accepté` ; la porte passe **`edge.net_edge_bps`** à `apply_delta` (anti-régression du bug historique « mesuré puis jeté ») | ✅ VÉRIFIÉ (sandbox) |
| **V6** | Aucun garde AFFAMÉ (refuse tout faute d'entrée) | ctx minimal → **abstention, jamais refus** ; sortie jamais bloquée. C'est le principe même de `filter_pipeline` | ✅ VÉRIFIÉ (sandbox) |
| **V7** | Fraîcheur/calibration : périmé/absent → DENY | `frais_pour_envoi(None) → False` (deny-by-default) ; carry : inputs trop vieux → `INPUTS_PERIMES`. Pas de « défaut mort » qui laisse passer | ✅ VÉRIFIÉ (sandbox) |
| **V8** | Module mesuré FEED la décision (mention ≠ porte) | Manifeste `audit_cablage_manifest.json` : les 8 gardes branchés (X1/X2/X3) ne sont **plus** dans TESTÉ-SEULEMENT | ✅ VÉRIFIÉ (sandbox) |
| **V9** | Réconciliation dashboard = ledger = audit | `test_pnl_reconciliation` + `test_paper_engine_ledger_wiring` verts (ledger unique). Réconciliation **dashboard live** complète = à re-confirmer au runtime | ✅ VÉRIFIÉ (ledger) · 🟡 dashboard live = runtime |
| **V10** | Pas de lookahead résiduel (purge+embargo) | `zscore_roulant` **causal** (changer le futur ne change pas le passé) ; tests existants `test_anti_lookahead_pipeline`, `test_purged_split`, `test_v12_no_lookahead_guard` verts | ✅ VÉRIFIÉ (sandbox) |
| **V11** | Les tests VÉRIFIENT (mutation), pas exécutent | `_appliquer_gardes` **discrimine** bon vs mauvais input ; **preuve de mutation** : neutraliser un garde fait basculer le contrôle en échec. Mutation testing EXHAUSTIF = lourd/Windows | ✅ VÉRIFIÉ (borné) · 🟡 exhaustif = Windows |
| **V12** | La vérité complète = Windows, pas le sandbox | Sandbox sans réseau ni UTF-8 fiable → NE PEUT PAS être la vérité complète. Source de vérité = `TEST-AUDIT-complet.cmd` sous Windows | 📌 MÉTA (documenté) |

## Ce qui est PROUVÉ ici (sandbox) vs ce qui reste

**Prouvé, reproductible en sandbox** : V1, V3, V4 (frais), V5, V6, V7, V8, V10, V11 (borné) —
14 contrôles neufs verts + 25 tests existants cités.

**Ne PEUT être clos qu'ailleurs (honnêteté)** :
- **V4 funding 1h/8h** : le garde-fou d'unité existe (règle carry « ne jamais convertir un taux »),
  mais l'audit ligne-à-ligne de CHAQUE consommateur de funding dépasse ce harnais → revue + tests
  carry existants. Pas de sur-affirmation.
- **V9 dashboard live** : le ledger unique est prouvé ; la convergence dashboard↔ledger↔audit **en
  conditions runtime** se confirme moteur allumé (pas en sandbox).
- **V11 mutation exhaustif** : preuve bornée faite ; un run `mutmut` complet est lourd et se fait
  sous Windows.
- **V12** : par construction, la vérité complète est Windows (`TEST-AUDIT-complet.cmd`).

## Verdict

Le chemin de décision LIVE tient les propriétés d'honnêteté vérifiables : les portes sont
atteintes (V1), les coûts sont réels et soustraits (V3/V5), les gardes ne s'affament pas (V6), le
périmé est refusé (V7), les modules branchés nourrissent vraiment la décision (V8), pas de fuite du
futur (V10), et les tests **discriminent** (V11, prouvé par mutation). Aucune sur-affirmation :
les portions runtime/Windows sont nommées, pas maquillées.

*Rappel : un contrôle qui ne peut pas échouer ne vérifie rien. On préfère un « 🟡 à confirmer au
runtime » honnête à un ✅ qui ment.*
