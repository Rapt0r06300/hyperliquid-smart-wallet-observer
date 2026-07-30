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
- **Rigueur statistique** : `metaorder_id` STABLE + dédup des fills ; **unité = le métaordre** ; par stade →
  **n_slices ET n_métaordres UNIQUES**, PnL net moyen avec **IC bootstrap CLUSTERISÉ par métaordre** (pas d'IC
  par slice), part de métaordres positifs, placebo alpha clusterisé, capacité, % taker/TWAP, coût moyen+source.
  En plus : **walk-forward PURGÉ** (embargo = horizon) et groupements **par vault / coin / jour**.
- **Coûts L2 RÉELS par signal** (`cout_l2_reel_bps` : frais + spread + 2×slippage(taille/profondeur) + latence,
  book courant par la taille) ; **16 bps = screening** seulement (fallback si L2 indisponible, tracé en `cout_source`).
- **Budget REST EXACT** (doc HL) : `poids_info` = 20 par appel `info` (2 pour l2Book) **+ floor(items/20)** pour
  les endpoints paginés ; on journalise le **poids/passe (rafale)** et le **vrai total IP** de toutes les sources
  (`rest_budget.json`, `budget_total`) vs 1200/min. (Correctif : 18 appels info = ≥ 360, pas 36 amorti.)

**Décision** (règle Flo) : on n'ouvrira une nouvelle cohorte QUE si un stade précis devient **fortement positif
après coûts**, **contre placebo ET en OOS** (walk-forward purgé), sur assez de **métaordres uniques**. Par défaut : rien.

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

## Contrat causal V2 (2026-07-29)

Cette section remplace les descriptions historiques d'identite et de stade
ci-dessus lorsqu'elles divergent.

- `userTwapSliceFills` est relie au fill par `tid`, puis par `(oid, time)`.
  Le hash TWAP nul (`0x00...00`) n'est jamais utilise comme identite globale:
  plusieurs slices officielles partagent ce hash.
- Un `twapId` officiel groupe les slices meme si leur cadence depasse la
  fenetre heuristique locale. Sans `twapId`, le groupe reste explicitement
  `INFERRED_METAORDER`.
- Le stade est calcule avec le prefixe observable seulement. Un futur slice ne
  peut plus transformer retrospectivement `FIRST_SLICE` ou `CONTINUATION` en
  `LATE_STAGE`.
- `LATE_STAGE`, la fraction executee, le residuel, le mode `NORMAL/CATCH_UP` et
  l'ETA utilisent uniquement le dernier `twapStates` recu avant la decision.
  Sans etat horodate, le residuel reste `RESIDUAL_UNMEASURABLE`.
- Le replay SHADOW mesure les delais pre-enregistres
  `50/100/250/500/1000/2000/5000 ms`. Ces mesures ne materialisent ni ordre
  paper ni PnL canonique.

Le schema read-only suivi est celui documente par Hyperliquid:
`twapStates` expose des paires `[twapId, TwapState]`; les slices TWAP sont
normalement emises toutes les 30 secondes et le rattrapage peut atteindre
trois fois la tranche normale. Ces constantes servent a decrire les preuves,
jamais a fabriquer un etat absent.

## Gouvernance RAW (cfg-6d8a2937)
Baseline **jamais promue**. Cap **20 cycles clôturés** (config courante) → `RAW_BASELINE_FIGEE_20` (gel pour
décision KILL/OBSERVE). RAW est exemptée de l'auto-KILL d'expectancy pour atteindre l'échantillon de 20 ; la
perte reste bornée par son budget minuscule ($20, notional $10 × max 2). `config_hash` **inchangé** (overlay).
