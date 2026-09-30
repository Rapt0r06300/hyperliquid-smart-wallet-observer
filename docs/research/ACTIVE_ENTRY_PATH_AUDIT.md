# Autopsie du chemin actif d'entrée — LA CAUSE RACINE

**2026-07-11.** Phase 2 du brief. Preuves de code, pas d'hypothèses.

---

## 🔴 LA DÉCOUVERTE : l'« edge » qui autorise chaque entrée est FABRIQUÉ

`src/hl_observer/paper_trading/fusion_paper_engine_adapter.py`, ligne 288 :

```python
def _consensus_edge_remaining_bps(conflict, *, distinct_wallets) -> float:
    dominance = abs(long_score - short_score) / total      # un score de VOTE, ∈ [0,1]
    consensus_bonus = min(distinct_wallets, 5.0) * 4.0     # 0 à 20
    gross_signal = dominance * 45.0 + consensus_bonus      # ← 45. Pourquoi 45 ?
    conservative_cost = 18.0
    return gross_signal - conservative_cost
```

**Ce nombre n'a JAMAIS touché un prix.**

C'est `dominance × 45 + bonus`. Le 45 est arbitraire. Ce n'est pas un mouvement de prix attendu,
ce n'est pas une mesure, ce n'est pas un edge. C'est un **score de vote entre wallets, converti en
bps par une formule inventée**.

Et le code l'avoue lui-même, ligne 144 :

```python
"edge_source": "CONSENSUS_VOTE_PROXY_NOT_EMPIRICAL",
"edge_is_empirical": False,
```

> **Le seuil `min_edge` compare une valeur inventée à un plancher.**
> Tout le réglage de ce seuil — le mien, celui de Codex, tous — portait sur **un nombre qui ne
> décrit pas le marché.** C'est pourquoi aucun réglage n'a jamais rien changé.

---

## 🔴 Et le modèle de coûts du gate est fabriqué aussi

Lignes 135-137 :

```python
spread_bps            = _env_float("HYPERSMART_FUSION_COPY_SPREAD_BPS", 6.0)      # CONSTANTE
estimated_slippage_bps= _env_float("HYPERSMART_FUSION_COPY_SLIPPAGE_BPS", 6.0)    # CONSTANTE
top_depth_usdt        = _env_float("HYPERSMART_FUSION_COPY_TOP_DEPTH_USDT", 50000) # CONSTANTE
```

Le spread réel du marché n'est **jamais lu**. La profondeur réelle n'est **jamais lue**.
Le gate de liquidité « valide » l'entrée contre **un carnet imaginaire de 50 000 $, toujours le
même, pour BTC comme pour un meme coin illiquide**.

---

## Les 2 chemins de décision concurrents — enfin identifiés

| chemin | edge utilisé | verdict |
|---|---|---|
| **`opportunity_report`** | edge **RÉEL**, mesuré sur les prix | **REFUSE** (−11,8 à −15,3 bps, `STALE_SIGNAL` × milliers) |
| **`fusion_paper_engine_adapter`** | edge **FABRIQUÉ** (`dominance × 45`) | **ACCEPTE** et ouvre |

**Le rapport qui dit la vérité n'a aucun pouvoir. Celui qui invente un chiffre ouvre les positions.**

C'est exactement le paradoxe des logs : des milliers de `STALE_SIGNAL`, et pourtant 21 ouvertures.

---

## Réponses aux 20 questions du brief

| # | question | réponse (preuve de code) |
|---|---|---|
| 1 | pourquoi `signal_age_ms=null` ? | `decision_context` (l.141) ne contient **que** consensus_wallets, leader_wallets, edge_source, vote scores. `signal_age_ms` n'y est **jamais mis**. `_paper_engine_evidence_fields` lit `context.get("signal_age_ms")` → `None`. |
| 2 | pourquoi `edge_remaining_bps=null` ? | idem : passé en **kwarg** à `apply_delta`, jamais copié dans le contexte → le ledger n'en garde aucune trace. |
| 3 | pourquoi les diagnostics V9 absents ? | ce chemin n'appelle **pas** le pipeline V9. |
| 4 | pourquoi le texte affirme que les contrôles ont réussi ? | les gates **tournent** — mais sur un **edge fabriqué** et des **coûts constants**. Le texte n'est pas un mensonge sur l'exécution des gates ; c'est un mensonge sur **ce qu'ils valident**. |
| 5 | `FUSION_PAPER_ENTRY` contourne-t-il les gates ? | **NON** — pire : il les **satisfait avec des données inventées**. |
| 6 | 2 moteurs de décision concurrents ? | **OUI, confirmé** (tableau ci-dessus). |
| 7 | qui est autoritaire ? | `fusion_paper_engine_adapter` — celui qui utilise le faux edge. |
| 8 | l'`opportunity_report` est-il décoratif ? | **OUI, en pratique.** Il refuse, personne ne l'écoute. |
| 9 | les signaux refusés sont-ils matérialisés ailleurs ? | **OUI** — par le chemin fusion. |
| 12-14 | 19/21 SHORT ? | `_consensus_edge_remaining_bps` utilise `abs(long − short)` : **le sens vient du vote, l'edge ne dépend pas du sens.** Un biais du vote se transmet intégralement. → à mesurer (tâche P6c). |
| 15 | prix leader utilisé comme notre prix ? | **NON, corrigé** : `market_price` = mid courant (`_latest_mid_for_coin`), + coût de latence facturé. |
| 20 | qu'est-ce qui bloque le chemin critique ? | la **décision** n'a lieu qu'en **fin de cycle de poll** (médiane 30,6 s / p95 50,4 s / max 106 s). Le firehose WS persistant **est allumé** (`.ps1` l.239) et stocke les fills en sub-seconde — mais **personne ne décide avant la fin du cycle**. Le hot path est **prisonnier du cold path**. |

---

## Ce qui N'EST PAS une régression (contrairement à l'analyse)

L'analyse externe conclut à des régressions sur `strategy_mode = null`. **Vérification :**

| | |
|---|---|
| ledger analysé, dernière écriture | **19:28:50** |
| mon code (`strategy_mode` à la source) | **20:04 – 20:45** |

**Le serveur analysé tournait l'ANCIEN code.** Le stamp existe (11 occurrences dans le code
actif). Statut honnête : `DONE_CODE_NOT_YET_OBSERVED_IN_RUNTIME` — **pas** `REGRESSION_DETECTED`.
Le redémarrage tranchera empiriquement.

De même, le firehose userFills persistant multiplexé **est allumé**. La fenêtre de 10 s des logs
vient d'un **scan borné supplémentaire** dans la boucle de poll, pas du firehose.

---

## Ordre de bataille — ce qui compte vraiment

1. **L'edge fabriqué.** Tant que la décision repose sur `dominance × 45`, **rien d'autre ne compte** :
   ni la latence, ni les seuils, ni les moteurs. On optimise la vitesse d'un chiffre qui ne veut
   rien dire.
2. **Les coûts constants.** Un gate de liquidité sur un carnet imaginaire ne protège de rien.
3. **La décision hors du cycle de 30-50 s.**

> Corriger la latence avant l'edge fabriqué reviendrait à **prendre de mauvaises décisions plus
> vite.**

---

*Simulation paper uniquement. **0 ordre réel, 0 argent réel, 0 clé privée, 0 signature,
0 dépôt/retrait.***
