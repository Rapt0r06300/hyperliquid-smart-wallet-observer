# HYPERSMART — RÉSULTATS DU SPRINT ALPHA (données RÉELLES) — 2026-07-30

> Expériences mesurées sur les tapes RÉELLES du bot (`runtime/data/`), pas de synthétique présenté comme
> réel. Discipline stricte : DISCOVERY→FREEZE→OOS INTACT, coûts déduits, aucun retune du holdout.
> Coût round-trip taker HL supposé **9 bps** (source unique `config/frais_venues`), maker ~3 bps en sensibilité.

## Tableau des idées

| IDEA | DATA | N indép. | GROSS bps | COST bps | NET bps | LCB net | OOS | FORWARD | CAPACITY | VERDICT |
|---|---|---|---|---|---|---|---|---|---|---|
| Lead-lag HL←Binance (BTC, H=1) | bbo_synchro 333k pts | 54 | 0.62 | 9 | **−8.38** | −8.62 | oui (net<0) | — | non mesurée | **KILL** |
| Lead-lag HL←Binance (ETH, choc fort H=5) | bbo_synchro 302k | 4 | 9.21 | 9 | +0.21 | n/a | trop peu | — | — | MORE_DATA |
| Lead-lag ETH choc fort + **maker 3 bps** | bbo_synchro 302k | 4 | 8.87 | 3 | **+5.87** | n/a | trop peu | — | — | MORE_DATA (prometteur) |
| Wallet forward markout (global) | leader_fills_forward 28.8k | 34 wallets | −0.72 (med) | 9 | −9.7 | — | — | — | — | **KILL** (suiveurs dominent) |
| Wallet préc. — 5 gelés → OOS | leader_fills_forward split | 5 gelés | — | 9 | — | — | 1/5 survit | requis | — | MORE_DATA |
| Wallet survivant `0x1e9b03ec06` | leader_fills_forward | disc 20 / oos 23 | +67 (oos med) | 9 | **+58** | non calc (n=23) | positif disc+OOS | **REQUIS** | non mesurée | **FORWARD_REQUIS** |

## Ce que ça dit, honnêtement

1. **Binance mène HL — confirmé sur données réelles.** Cross-corr des rendements : pic à **lag +2** pour
   BTC/ETH/SOL (HL suit Binance de ~2 updates BBO). La prémisse « un wallet simplement suiveur = KILL » est
   fondée : le marché HL est majoritairement mené par Binance.
2. **Le lead-lag brut ne survit pas au coût taker.** Sur BTC (N=54, robuste), le markout HL après un choc
   Binance est net **−8,4 bps**, LCB **−8,6** → KILL franc. Le régime « choc fort + horizon 3-5 » monte le
   gross à ~9 bps mais devient trop rare (N=4) → MORE_DATA. **Sous exécution maker (3 bps), ETH nette +5,9 bps**
   sur ce régime : c'est la SEULE piste lead-lag à creuser (plus de data + maker queue-aware).
3. **La plupart des wallets sont des suiveurs** (markout global −0,7 bps médian). Mais la discipline OOS
   révèle du vrai : sur 5 wallets gelés en découverte, **4 s'effondrent en OOS** (biais de sélection prouvé :
   `0x7c93` +25→−49), **1 survit** (`0x1e9b03ec06` : +13 disc → **+58 OOS**). Candidat réel à confirmer en
   FORWARD post-freeze, avec LCB et plus de N (n=23 encore fragile). **Aucune promotion** sans forward.

## Conclusion du sprint
Aucun edge net-positif PROUVÉ (forward requis pour l'unique survivant). Mais deux pistes réelles et
mesurées, non fabriquées : **(a)** lead-lag choc-fort + exécution maker ; **(b)** le wallet préc. survivant
`0x1e9b03ec06`. Prochaine étape à plus fort impact : collecter plus de tape synchronisée (ton bot) pour
donner du N à ces deux pistes, et tester le maker queue-aware sur le régime choc-fort.

Outils réutilisables commités : `research/hl_binance_leadlag.py` (expérience lead-lag testée),
`following/binance_anticipation.py` (anticipation wallet corrigée), `scoreboard_*` (jugement honnête).
