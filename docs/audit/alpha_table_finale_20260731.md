| IDEA | CONFIG FROZEN | N IND | GROSS | COST | NET | LCB | OOS | FORWARD | CAPACITY | VERDICT |
|---|---|---|---|---|---|---|---|---|---|---|
| Lead-lag ETH strong-shock + MAKER | bbo_synchro; regime choc-fort GELE; h=5; maker 3bps | 4 | 8.87 | 3.00 | 5.87 | UNMEASURABLE | N trop faible | requis | UNMEASURABLE | MORE_DATA |
| Wallet 0x1e9b03ec06 copyable | leader_fills_forward; grappes wallet:coin:jour; cout 9bps | 3 | 87.00 | 9.00 | 44.60 | UNMEASURABLE | confondu coin-switch | — | UNMEASURABLE | MORE_DATA |
| TWAP/metaorder residual flow | metaorder_l2_tape; stade FIRST_SLICE vs CONTINUATION; fwd mid 1-30s | UNMEASURABLE | UNMEASURABLE | 9.00 | UNMEASURABLE | UNMEASURABLE | — | — | UNMEASURABLE | MORE_DATA |
| Lead-lag ETH strong-shock MAKER (reel queue-aware) | regime gele; fill=proba(volume traversant) | 4 | 8.87 | 3.00 | UNMEASURABLE | UNMEASURABLE | — | — | UNMEASURABLE | MORE_DATA |
| Book-imbalance L1 (ETH) MAKER-fee-only (optimiste) | idem, cout=3bps frais maker, fill suppose | 460 | 1.90 | 3.00 | -1.10 | -1.36 | net<0 | — | UNMEASURABLE | KILL |
| Book-imbalance L1 (ETH, best cell) | l2_book HL; |imb_l1|>=q; DISC->FREEZE->OOS; h=2(~36s) | 460 | 1.90 | 9.30 | -7.65 | -7.91 | net<0 | — | UNMEASURABLE | KILL |
| Lead-lag HL<-Binance (BTC) | bbo_synchro; choc Binance>=seuil gele; h=1; DISC/OOS | 54 | 0.62 | 9.00 | -8.38 | -8.62 | net<0 | — | UNMEASURABLE | KILL |
| Wallet population (27 wallets, >=8 fills) | leader_fills_forward; classe par net copyable edge | UNMEASURABLE | UNMEASURABLE | 9.00 | UNMEASURABLE | UNMEASURABLE | — | — | UNMEASURABLE | KILL |
| Cross-venue latency arb (BTC, fresh) | bbo_synchro; desync<50ms; edge exec 2-jambes vs cout | UNMEASURABLE | 4.18 | 9.00 | -4.82 | UNMEASURABLE | P99<cout | — | 245826 | KILL |
| Feature-increment STATE+FLOW (BTC) | l2_book; seuils q0.75 geles; h=2; conjonction | 1615 | UNMEASURABLE | 9.30 | -8.09 | UNMEASURABLE | net<0 | — | UNMEASURABLE | KILL |
| Cross-venue gaps illiquides (SAGA/ZRO...) | carnet_venues; ecart_executable_max_bps | UNMEASURABLE | 52.00 | 9.00 | UNMEASURABLE | UNMEASURABLE | — | — | UNMEASURABLE | BLOCKED_EXTERNAL |
| OFI multi-niveau L3/L5/L10/L20 + MLOFI | requiert tailles PAR NIVEAU dans le temps | UNMEASURABLE | UNMEASURABLE | UNMEASURABLE | UNMEASURABLE | UNMEASURABLE | — | — | UNMEASURABLE | BLOCKED_EXTERNAL |
| L4 / order-intent lifecycle | ORDER->MODIFY->CHASE->PARTIAL->FILL/CANCEL | UNMEASURABLE | UNMEASURABLE | UNMEASURABLE | UNMEASURABLE | UNMEASURABLE | — | — | UNMEASURABLE | BLOCKED_EXTERNAL |
| Wallet population AT SCALE (milliers) | node_fills_by_block streaming | UNMEASURABLE | UNMEASURABLE | UNMEASURABLE | UNMEASURABLE | UNMEASURABLE | — | — | UNMEASURABLE | BLOCKED_EXTERNAL |
