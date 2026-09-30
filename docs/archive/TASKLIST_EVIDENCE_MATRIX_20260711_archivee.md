# Matrice de preuves — ce qui est vraiment fait, et ce qui ne l'est pas

**2026-07-11.** Phase 0 du brief. Une tâche n'est `DONE_VERIFIED` que si l'on trouve **simultanément** :
code + câblage dans le runtime actif + test utile + aucune contradiction dans les logs.

---

## 🔴 Les 3 découvertes qui dominent tout le reste

### 1. L'edge qui autorisait chaque entrée était FABRIQUÉ

```python
# fusion_paper_engine_adapter.py:288
dominance    = |long_score − short_score| / total     # un score de VOTE
gross_signal = dominance * 45.0 + bonus               # ← 45. D'où vient 45 ?
```

Le code l'avouait : `edge_source = "CONSENSUS_VOTE_PROXY_NOT_EMPIRICAL"`.
**Ce nombre n'a jamais touché un prix.** Le seuil `min_edge` comparait donc une valeur inventée à
un plancher — c'est pourquoi aucun réglage de ce seuil n'a jamais rien changé.

Deuxième source (`fresh_opportunity._expected_edge_bps`) : `score×0,55 + wallets×9 +
notional/25000 + tightness×10`. Même maladie.

→ **CORRIGÉ** : `edge/empirical_edge.py`, deny-by-default. Un edge est mesuré, ou il n'existe pas.

### 2. Le « funding-arb delta-neutre » n'a qu'une jambe

Position **nue** sur un perp, dont le PnL **ignorait totalement le prix**. Il aurait imprimé des
profits fictifs. **Le verrou d'entrée mort nous en a accidentellement protégés.**

→ **CORRIGÉ** : le PnL de prix est compté, de la position jusqu'au ledger.

### 3. La décision attend la fin d'un cycle de 30-50 s

Le firehose WS persistant **est allumé** et stocke les fills en sub-seconde. Mais **personne ne
décide** avant la fin de la boucle de poll (médiane 30,6 s, p95 50,4 s, max 106 s).
**Le hot path est prisonnier du cold path.** → **NON CORRIGÉ** (P4).

---

## Ce que l'analyse externe a mal lu (vérifié)

| affirmation | verdict |
|---|---|
| `strategy_mode = null` → régression | **FAUX**. Ledger 19:28:50, code 20:04-20:45. Le serveur analysé tournait l'**ancien code**. |
| userFills relancé toutes les 10 s (pas de firehose) | **FAUX**. Le firehose multiplexé est allumé (`.ps1` l.239). La fenêtre de 10 s est un scan borné **en plus**. |
| `FUSION_PAPER_ENTRY` contourne les gates | **PIRE** : il les *satisfait* avec un edge fabriqué et des coûts constants. |
| Le modèle IA menace le hot path | **FAUX**. `apply_model_promotion` n'est appelé **nulle part**. Influence : zéro. |

---

## Statut par tâche

### ✅ DONE_VERIFIED (code + câblage + test + preuve)

| tâche | preuve |
|---|---|
| Edge empirique obligatoire | `edge/empirical_edge.py` + câblé en 2 points + **16 tests** |
| Frais Hyperliquid réels (maker COÛTE 1,5 bps) | `exec_model.py` — aller-retour taker = **9 bps** |
| PnL de prix du funding-arb | `funding_arb_paper.py` + ledger + **8 tests** |
| `strategy_mode` posé à la source | entrées + **toutes** les sorties + **20 tests** |
| PnL séparé par moteur | `engine_pnl.py` + câblé au statut + **15 tests** |
| Budget de risque par moteur | `engine_risk_budget.py` + câblé au gate + **13 tests** |
| Exposition directionnelle NETTE | `directional_exposure.py` — 9 shorts = 250 % du capital |
| Économie : config perdante détectée | `engine_economics.py` — l'ancienne config : breakeven **90 %** |
| Symétrie LONG/SHORT | **8 tests** — aucun bug ; le biais vient des leaders |
| Promotion IA bloquée | `ml/promotion_gate.py` + **9 tests** |
| Carnet L2 + funding enregistrés | `microstructure_recorder.py` — actif au lancement |

### 🔴 REGRESSION_DETECTED / TODO_ACTIVE (le vrai reste-à-faire)

| # | tâche | pourquoi ça compte |
|---|---|---|
| P4 | **La décision attend 30-50 s** | Le Sniper meurt de la fraîcheur. Tout le reste est secondaire. |
| P2-2 | Spread/slippage/profondeur **constants** dans le gate fusion | Un carnet imaginaire de 50 000 $, le même pour BTC et un meme coin |
| P2-3 | 2 chemins de décision non alignés | Celui qui **mesure** refuse ; celui qui **invente** ouvre |
| P3 | Latence bout-en-bout non instrumentée | On ne peut pas corriger ce qu'on ne mesure pas |
| P7-1 | **Courbe edge/horizon 100 ms → 5 min** | **Jamais mesuré sous 1 s.** La seule raison honnête d'espérer un edge de copie |

### 🔵 BLOCKED_DATA (le code peut être écrit ; la donnée n'existe pas encore)

Microstructure (OFI, VPIN, micro-prix, queue), exécution maker, funding historique, scoring de
leaders. **Les modules d'analyse existent déjà et sont testés.** Il leur manque *uniquement* la
donnée — que le bot enregistre depuis ton redémarrage.

---

## La phrase qui résume

> Le bot a **cessé de perdre bêtement**. Il n'a **pas commencé à gagner**.
> Ces deux choses sont différentes, et je ne les confondrai pas pour te faire plaisir.

---

*Simulation paper uniquement. **0 ordre réel, 0 argent réel, 0 clé privée, 0 signature,
0 dépôt/retrait.***
