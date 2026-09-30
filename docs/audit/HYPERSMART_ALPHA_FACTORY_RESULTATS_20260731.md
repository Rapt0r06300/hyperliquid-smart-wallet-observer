# HYPERSMART — ALPHA FACTORY : TABLE DES CANDIDATS (données RÉELLES) — 2026-07-31

> Chaque piste passée dans le même moule : `DATA × EVENT × STATE × FILTER × HORIZON × EXECUTION → RESULT`,
> discipline DISCOVERY→FREEZE→OOS, votes indépendants (grappes maison), coûts exécutables déduits,
> `UNMEASURABLE` jamais remplacé par 0. **Aucun vert fabriqué.** Registre global : `runtime/research/alpha_trial_registry.jsonl`.

## TABLE (triée : candidats d'abord)

| IDEA | CONFIG FROZEN | N IND | GROSS | COST | NET | LCB | OOS | FORWARD | CAPACITY | VERDICT |
|---|---|---|---|---|---|---|---|---|---|---|
| Lead-lag ETH strong-shock + MAKER | régime choc-fort GELÉ ; h≈5 ; maker 3bps | 4 | 8.87 | 3.0 | **+5.87** | n/a | N trop faible | requis | UNMEASURABLE | **MORE_DATA** |
| Wallet 0x1e9b03ec06 copyable | grappes wallet:coin:jour ; 9bps | 3 | 87.0 | 9.0 | +44.6 | n/a | confondu coin-switch | — | UNMEASURABLE | **MORE_DATA** |
| TWAP/metaorder residual flow | FIRST_SLICE vs CONTINUATION ; fwd 1–30s | — | — | 9.0 | — | — | — | — | UNMEASURABLE | **MORE_DATA** |
| Book-imbalance L1 MAKER-fee-only (opt.) | l2_book ; maker 3bps ; fill supposé | 460 | 1.90 | 3.0 | −1.10 | −1.36 | net<0 | — | UNMEASURABLE | **KILL** |
| Book-imbalance L1 (ETH, best) | l2_book ; \|imb\|≥q gelé ; h≈36s | 460 | 1.90 | 9.3 | −7.65 | −7.91 | net<0 | — | UNMEASURABLE | **KILL** |
| Lead-lag HL←Binance (BTC) | bbo_synchro ; choc≥seuil gelé ; h=1 | 54 | 0.62 | 9.0 | −8.38 | −8.62 | net<0 | — | UNMEASURABLE | **KILL** |
| Wallet population (27, ≥8 fills) | classé par net copyable edge | — | — | 9.0 | — | — | — | — | UNMEASURABLE | **KILL** |
| Cross-venue latency arb (BTC, fresh) | bbo_synchro ; desync<50ms | — | 4.18 | 9.0 | −4.82 | — | P99<coût | — | 245826 | **KILL** |
| Cross-venue gaps illiquides (SAGA…) | carnet_venues ; ecart_exec_max | — | 52.0 | 9.0 | — | — | — | — | UNMEASURABLE | **BLOCKED (basis/scope)** |
| OFI multi-niveau L3/L5/L10/L20 + MLOFI | tailles PAR NIVEAU dans le temps | — | — | — | — | — | — | — | UNMEASURABLE | **BLOCKED (data)** |
| L4 / order-intent lifecycle | ORDER→MODIFY→CHASE→FILL/CANCEL | — | — | — | — | — | — | — | UNMEASURABLE | **BLOCKED (data)** |
| Wallet population AT SCALE (milliers) | node_fills_by_block streaming | — | — | — | — | — | — | — | UNMEASURABLE | **BLOCKED (data)** |

## Verdict honnête du run
**0 candidat net-positif PROUVÉ.** Les 2 seules lignes au net>0 ne sont PAS des candidats :
- **ETH strong-shock + maker** : net **+5,87 bps** mais **N=4** → statistiquement nul ; et le maker est encore
  une *hypothèse de fill*, pas un modèle queue-aware réel. → MORE_DATA (même régime gelé, plus de N + fill-model).
- **Wallet 0x1e9b03ec06** : le fameux « +58 bps OOS » = **1 seule journée PUMP** (memecoin). 43 fills → **3 votes
  indépendants**, **concentration 0,79**, LCB non calculable. C'est un artefact de petit N, pas un edge.
  Sur **toute la population (27 wallets)** : **0 candidat**, les mieux peuplés (n_ind 94–141) font ~0–3 bps
  gross → net franchement négatif.

**Le mur est structurel : le coût par trade (≈9 bps taker HL).** Tous les signaux à haute fréquence
(OFI/microprice, imbalance, lead-lag, cross-venue) sont **réels mais sous le coût**. Le cross-venue « énorme »
est du **basis perp/spot persistant** (autocorr 0,63–0,94) = `DISABLED_BY_SCOPE`, pas un arb de latence.

## Ce qui débloquerait de vrais candidats (collecte ciblée, par priorité)
1. **P3/P4 — un tape L2 multi-niveaux HAUTE CADENCE** (tailles bid/ask par niveau, sub-seconde). Aujourd'hui
   `l2_book` n'a que la profondeur **agrégée** (pas L3/L5/L10/L20) et le `metaorder_l2_tape` ne fait que **24 min**.
   → indispensable pour MLOFI et pour le flux résiduel TWAP (les 2 pistes les plus prometteuses de la littérature).
2. **P1A/P6 — fills wallet AVEC TAILLE** + BBO/L2 exécutable des coins tradés (dont memecoins), et les
   archives **node_fills_by_block**. Sans taille : action OPEN/ADD/REDUCE/CLOSE/FLIP, capacity et fill-ratio
   restent **UNMEASURABLE**. Avec : on passe de 27 à des milliers de wallets, classés par *notre* net copyable edge.
3. **P5 — flux node/L4 (order intent)** : totalement absent ici → toute la piste « ordres en vol avant le
   spread » est `BLOCKED_EXTERNAL`. C'est la piste à plus fort potentiel théorique mais elle exige l'infra.
4. **P1B — plus de tape synchronisé** pour donner du N au régime choc-fort ETH (la seule lueur au net>0).

## Ledger des SHA (repo de travail ; jamais poussé)
- `11a29a9` OFI + microprice + déséquilibre (48/48 KILL)
- `14809c9` wallet copyable-edge + population (0/27 candidat)
- `00a481c` Alpha Factory (registre + table)
- *(ce doc : commit docs séparé)*

Carry/funding = `DISABLED_BY_SCOPE`. PAPER/READ-ONLY (0 ordre réel). Holdout jamais retuné.
