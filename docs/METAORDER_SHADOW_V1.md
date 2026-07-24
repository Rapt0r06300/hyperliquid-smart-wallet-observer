# METAORDER_SHADOW_V1 — mesure d'edge par stade de métaordre (SHADOW)

Module : `src/hl_observer/experimental/metaorder_shadow.py` · runner câblé dans
`tools/collecter_userfills_vaults.py` (`_metaorder_shadow_periodique`, ~10 min).
Tests : `tests/test_metaorder_shadow.py`. **N'ouvre AUCUNE position.** Ledger séparé
`runtime/data/metaorder_shadow_ledger.jsonl` + stats `runtime/data/metaorder_shadow_stats.json`.
Jamais mélangé au PnL live. `real_execution=false`, `shadow=true` sur chaque ligne. Lecture seule.

## Ce qui est mesuré, par stade
- **TWAP** étiqueté DIRECTEMENT via `userTwapSliceFills` (index `tid|hash → twapId`) — pas d'heuristique.
- **Métaordre caché** : agrégation des fills par `(vault, coin, sens)` contigus (écart ≤ intervalle, défaut 60 s).
- **Stades** : `FIRST_SLICE`, `CONTINUATION`, `LATE_STAGE`, `REVERSAL` (1er slice qui inverse le métaordre précédent).
- Par slice : **PnL forward net après coûts** (horizon 5 min), **taille relative**, **crossed maker/taker**,
  **placebo** même coin/même instant (vs dérive BTC → `alpha_vs_marche_bps`), et en shadow l'**OFI top-5** du carnet.
- Par stade (`stats_par_stade`) : n, PnL net moy/méd, part positive, **IC** (taille→forward), placebo alpha moyen,
  **capacité** (somme des tailles), % taker, % TWAP.

**Décision** (règle Flo) : on n'ouvrira une nouvelle cohorte QUE si un stade précis devient **fortement positif
après coûts** (net, placebo, IC, capacité) sur assez de signaux. Par défaut : rien.

## Les TROIS âges — à ne jamais confondre (réconciliation « 60 s » vs « 382 ms »)
1. **Âge du fill HL** (`age_fill_hl_ms`) = skew/staleness de l'**événement** HL (fill.time vs horloge).
   C'est l'ancienneté du signal *côté source*. En live : `age_event_ms` du ledger RAW (~0–1 s, parfois négatif = skew).
2. **Latence locale** (`latence_locale_ms`) = NOTRE pipeline **WS→décision→L2→open**. Mesurée en live :
   **~382 ms médian** (max ~2,2 s). N/A en shadow (la passe shadow relit des fills historiques par REST).
3. **Âge du stade** (`age_stade_ms`) = temps écoulé depuis le **FIRST_SLICE** du métaordre parent (s→min).
   C'est une propriété du *déroulé* du métaordre, indépendante du transport.

Le « **price-in ~60 s** » évoqué dans des rapports antérieurs était une propriété **du signal de copie mesurée
offline** (décroissance de l'edge / âge médian du signal dans l'étude OOS ≈ 62 s), **PAS** la latence locale
(382 ms). Autrement dit : notre exécution est rapide (382 ms), mais l'*edge du signal copié* se dégrade sur
un horizon de l'ordre de la minute. METAORDER_SHADOW sépare ces axes et mesure l'edge net réel par stade.

## Budget REST
Le runner appelle `userFillsByTime` + `userTwapSliceFills` (2 appels/vault) toutes les ~10 min, REST hors
event-loop, poids estimé journalisé (`poids~…/1200 IP·min`). Le budget REST GLOBAL de tous les collecteurs
sera journalisé au prochain redémarrage naturel (note différée, avec `aggregateByTime:false` explicite et la
clé enrichie `px/sz/side`).

## Gouvernance RAW (cfg-6d8a2937)
Baseline **jamais promue**. Cap **20 cycles clôturés** (config courante) → `RAW_BASELINE_FIGEE_20` (gel pour
décision KILL/OBSERVE). RAW est exemptée de l'auto-KILL d'expectancy pour atteindre l'échantillon de 20 ; la
perte reste bornée par son budget minuscule ($20, notional $10 × max 2). `config_hash` **inchangé** (overlay).
