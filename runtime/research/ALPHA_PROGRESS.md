# ALPHA PROGRESS — reprise en <2 min

CURRENT_TASK : (aucune en cours)
LAST_COMMIT  : 5fd9d6e (P58 factory coverage)
TESTS        : suite recherche verte (~76 tests) — factory + 8 modules discipline
RESULT       : 0 candidat net-positif prouve. La COUCHE DISCIPLINE est maintenant complete et testee : les verdicts seront fiables des que la donnee arrivera.
NEXT_TASK    : data-ready restants -> P36 (deconfliction event_cluster_id) -> P37 (meta-gate/ablation) -> P40 (wallet info ratio) -> P35 (exit factory) -> P46 (capacity curve) -> P47 (capital efficiency) -> P61 (daily report). Puis P15 (brancher toutes les familles dans run_factory).
BLOCKERS     : le VRAI deblocage reste la collecte HF SIMULTANEE cote user (fills+Binance BBO+L2 multi-niveaux+node_fills+L4). Pas de reseau ici.

## Couche DISCIPLINE livree ce run (data-ready, testee)
- P13 fix factory (min->max, append-only, hashes) .......... 367e576
- P14 source unique de couts (cost_model) ................... 3a2494a
- P33/P44/P45 gates (cost-aware/early-stop/multiple-testing)  d8aeb3c
- P50 basis vs latency (cross-venue transient-only) ......... 505ac9f
- P12 recette economique (4 scenarios, optimistic!=promote) . 6c91c5b
- P16 search space pre-enregistre & hashe (anti-snooping) ... 42f5590
- P32 alpha decay (half-life/break-even/NO_TRADE) ........... 62070f6
- P62/P63 hard-negatives + backlog scorer .................. b5c7867
- P58 factory coverage test ................................ 5fd9d6e

## Deja prouve (ne pas refaire sans nouvelle donnee/hypothese)
- BTC lead-lag taker : KILL ; OFI/microprice L1 : gross<cout (KILL) ; MLOFI : math prete, data-limited
- cross-venue gap<cout / basis persistant : KILL / DISABLED_BY_SCOPE
- wallet '+58bps' 0x1e9b : PUMP artefact ; population 27 wallets : 0 candidat ; P2 anticipation : MORE_DATA (data non simultanee)

## Regles actives
- 1 task = 1 commit ; jamais push (l'user pousse) ; commit via plomberie git (mount interdit unlink index.lock)
- PROMOTE seulement si net>0 & LCB>0 & OOS>0 & forward>0 & couts complets & survit ADVERSE_P95 & passe multiple-testing
- carry/funding = DISABLED_BY_SCOPE ; PAPER/READ-ONLY (0 ordre reel)
