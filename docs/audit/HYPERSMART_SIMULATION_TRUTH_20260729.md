# HYPERSMART — VÉRITÉ DE SIMULATION (2026-07-29)

Ce document répond à une seule question : **à quelles conditions un chiffre de PnL produit par ce dépôt
mérite d'être cru ?**

---

## 1. La chaîne canonique unique

```
tick durable  →  canonicalisation  →  gate qualité  →  replay exécutable  →  ledger  →  réconciliation
```

| Étape | Module | Refus possible |
|---|---|---|
| tick durable | `collection/tick_dataset.py` (sha256 + shards immuables) | `RAW_HASH_MISMATCH` |
| canonicalisation | `normalization/market_events.py` | `UNSUPPORTED_TICK_SCHEMA`, `MISSING_SOURCE_IDENTITY`, `WRITE_BEFORE_RECEIVE`, `PROVENANCE_NOT_READ_ONLY` |
| gate qualité | `realtime/feed_quality.py` | `DATA_QUALITY_GATE_NOT_READY` |
| replay exécutable | `market_truth/executable_replay.py` | `NO_BOOK`, `STALE_BOOK`, `NO_FILL`, `QUALITY_BLOCKED`, `UNMEASURABLE` |
| ledger + réconciliation | `market_truth/truth_chain.py` | `PNL_RECONCILIATION_MISMATCH` |
| orchestration | `market_truth/pipeline.py` | empêche de sauter une étape |

**Point clé** : `MarketTruthPipeline` existe précisément pour qu'aucun appelant ne puisse passer d'un message
brut à un fill paper sans traverser la canonicalisation et le gate.

---

## 2. Les huit règles qui rendent un PnL crédible

1. **Sortie liquidable, jamais un mid.** Un long ferme au bid, un short à l'ask. Le mid sert au graphique,
   jamais à valoriser.
2. **Non mesurable ≠ 0.** Un épisode sans prix d'entrée ET de sortie exécutables est exclu et compté
   (`bloc 18` : `FERMETURE_SANS_PRIX_EXECUTABLE`, `POSITION_ENCORE_OUVERTE`). Le valoriser à 0 diluerait la
   moyenne vers le beau.
3. **Un dénominateur par chiffre.** Quatre ROI publiés séparément — equity de départ, marge moyenne, marge
   pic, exposition brute. Dénominateur inconnu ⇒ `None`.
4. **PF sans perte ⇒ `None`**, jamais un infini présenté comme excellent.
5. **Coûts comptés une seule fois.** `included_in_price` distingue ce qui est déjà dans le prix (spread
   traversé) de ce qui se débite en cash (frais).
6. **Le futur ne change pas une décision passée** (`bloc 17`) : bande tronquée à `t` et bande complète
   donnent le même fill, sinon la décision lisait le futur.
7. **Le rejeu ne crée ni ne détruit de PnL.** Seules `session_id` et `last_event_hash` diffèrent entre deux
   sessions — prouvé, pas supposé.
8. **L'optimiste ne classe rien.** `OPTIMISTIC_DIAGNOSTIC_ONLY` porte `promouvable=False`.

---

## 3. Ce qui reste ASSUMED, et pourquoi c'est dit

Le projet n'envoie **aucun ordre réel**. Donc :

- la latence d'exécution externe (submit → fill) n'est **pas observable** ;
- la queue de coûts adverses (P95/P99) n'est **pas observable**.

Ces composantes sont donc des **distributions conservatrices versionnées**, marquées `ASSUMED` dans le
rapport (`DEGRADATIONS_ADVERSES_BPS = {P95: 6 bps, P99: 12 bps}`). Les présenter comme « mesurées en réel »
serait un mensonge, et c'est le genre de mensonge qui transforme un backtest en promesse.

Le fill maker reste `MAKER_FILL_UNMEASURABLE` tant que la file devant nous n'est pas modélisée : « le prix a
touché » n'est pas un fill.

---

## 4. Mesure réelle au 2026-07-29 (bloc 18)

| Stratégie | Statut | n | net USD | bps/trade | PF | max DD | ROI equity |
|---|---|---:|---:|---:|---:|---:|---:|
| `raw_probe` | MESURE | 19 | **-0,168** | **-5,88** | 0,66 | -0,24 | -0,017 % |
| `carry_paper` | **AUCUN_EPISODE_MESURABLE** | 0 | — | — | — | — | — |
| `experimental_paper_v2` | LEDGER_ABSENT | — | — | — | — | — | — |

Enveloppes `raw_probe` : `ADVERSE_P95` -0,276 · `ADVERSE_P99` -0,384. **Aucune enveloppe n'est positive.**

`carry_paper` : 190 lignes, 100 ouvertures sans prix ni notionnel, 90 fermetures orphelines. Le producteur
écrit `price: None` — c'est un défaut de **collecte**, pas un résultat. Tant qu'il n'est pas corrigé, aucun
PnL carry n'est calculable, et aucun ne doit être affiché.

**Conclusion sans maquillage** : à ce HEAD, la seule stratégie mesurable est **négative après coûts**, ce qui
est cohérent avec la loi déjà établie du projet (edge de copie négatif). Aucun résultat positif n'est
produit, et aucun n'est promis.

---

## 5. Sécurité

`0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.`
