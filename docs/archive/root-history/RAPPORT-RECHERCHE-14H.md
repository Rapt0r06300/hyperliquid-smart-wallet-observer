# RAPPORT — RECHERCHE 14 h (mécanismes natifs Hyperliquid)

- **run_id** : `r14h-6a1374643d22`
- **PID** : 37240 · **read_only** : True · **real_execution** : False
- **T0 (wall ms)** : 1785025138800 · **durée mesurée** : 13.94 h
- **fichiers scellés** : 3 (manifeste SHA256)

## Protocole (anti-sur-ajustement)
Fenêtres : **A_DÉCOUVERTE** 0–5 h → embargo 5–6 h → **B_VALIDATION** 6–10 h → embargo 10–11 h → **C_HOLDOUT** 11–14 h. Finalistes **figés après A** (aucun tuning ensuite). Critères d'ARM : n ≥ 30 épisodes, **PF ≥ 1.2**, DSR ≥ 0.95, PBO ≤ 0.20, stress coûts 50 %.

## Couverture
Mesures par phase : A=30 · B=23 · C=18 (total 71 essais append-only). Mécanismes testés : 10. Finalistes figés : OFI_TOP5, OFI_TOP20, OFI_TOP1, HL_ABSORPTION_NATIVE, TRADE_SWEEP_BURST, LIQUIDITY_VACUUM, QUEUE_MICROPRICE.

## C_HOLDOUT — le juge final (out-of-sample propre)
| mécanisme | n | net médian (bps) | PF | Sharpe | verdict |
|---|---:|---:|---:|---:|---|
| OFI_TOP1 | 10512 | -10.91 | 0.006 | -2.38 | KILL |
| OFI_TOP5 | 11326 | -11.04 | 0.006 | -2.39 | KILL |
| OFI_TOP20 | 11054 | -11.07 | 0.006 | -2.41 | KILL |
| QUEUE_MICROPRICE | 398 | -12.88 | 0.004 | -2.48 | KILL |
| LIQUIDITY_VACUUM | 1238 | -10.42 | 0.009 | -2.05 | KILL |
| HL_ABSORPTION_NATIVE | 8673 | -10.46 | 0.006 | -2.21 | KILL |
| TRADE_SWEEP_BURST | 5354 | -10.15 | 0.030 | -1.76 | KILL |
| OI_VEL_ACCEL_PRICE_FUNDING | 0 | — | — | — | DATA_MISSING |
| FUNDING_CLOCK_DIVERGENCE | 0 | — | — | — | DATA_MISSING |
| LIQUIDATION_CASCADE_DEPTH | 0 | — | — | — | DATA_MISSING |

## B_VALIDATION
| mécanisme | n | net médian (bps) | PF | Sharpe | verdict |
|---|---:|---:|---:|---:|---|
| OFI_TOP1 | 1692 | -10.69 | 0.015 | -2.13 | KILL |
| OFI_TOP5 | 1841 | -10.68 | 0.010 | -2.32 | KILL |
| OFI_TOP20 | 1871 | -10.88 | 0.011 | -2.33 | KILL |
| QUEUE_MICROPRICE | 51 | -12.87 | 0.019 | -2.08 | KILL |
| LIQUIDITY_VACUUM | 128 | -10.29 | 0.072 | -1.25 | KILL |
| HL_ABSORPTION_NATIVE | 639 | -10.21 | 0.000 | -3.65 | KILL |
| TRADE_SWEEP_BURST | 250 | -19.94 | 0.025 | -2.06 | KILL |
| OI_VEL_ACCEL_PRICE_FUNDING | 0 | — | — | — | DATA_MISSING |
| FUNDING_CLOCK_DIVERGENCE | 0 | — | — | — | DATA_MISSING |
| LIQUIDATION_CASCADE_DEPTH | 0 | — | — | — | DATA_MISSING |

## A_DÉCOUVERTE
| mécanisme | n | net médian (bps) | PF | Sharpe | verdict |
|---|---:|---:|---:|---:|---|
| OFI_TOP1 | 18208 | -10.74 | 0.006 | -2.33 | KILL |
| OFI_TOP5 | 19951 | -10.78 | 0.006 | -2.40 | KILL |
| OFI_TOP20 | 19834 | -10.91 | 0.005 | -2.44 | KILL |
| QUEUE_MICROPRICE | 612 | -12.89 | 0.003 | -2.37 | KILL |
| LIQUIDITY_VACUUM | 1669 | -10.18 | 0.010 | -2.10 | KILL |
| HL_ABSORPTION_NATIVE | 8470 | -10.15 | 0.023 | -1.85 | KILL |
| TRADE_SWEEP_BURST | 3601 | -10.53 | 0.093 | -0.60 | KILL |
| OI_VEL_ACCEL_PRICE_FUNDING | 0 | — | — | — | DATA_MISSING |
| FUNDING_CLOCK_DIVERGENCE | 0 | — | — | — | DATA_MISSING |
| LIQUIDATION_CASCADE_DEPTH | 0 | — | — | — | DATA_MISSING |

## PnL / edge net (synthèse holdout)
Mesure = **markout net médian par épisode (bps)**, côté **taker** (shadow), après frais + spread + slippage. Ce n'est PAS un livre paper en $ : aucun notionnel n'est appliqué, donc pas de PnL$/ROI$/équity — l'objet mesuré est l'**edge net en bps**.
- edge net holdout : meilleur **-10.15 bps** (TRADE_SWEEP_BURST) · pire **-12.88 bps** (QUEUE_MICROPRICE) — **tous négatifs** → aucun edge net à capturer.

## Métriques promises non émises par ce run (honnêteté, à instrumenter)
Le moteur de mesure de ce run a émis, par mécanisme et par phase : **n, net médian (bps), profit factor, Sharpe**. Les métriques suivantes n'ont **pas** été calculées par mesure — elles ne sont donc pas inventées ici, et devront être instrumentées avant tout ARM :
- **DD (drawdown)** : non émis (mesure par épisode, pas de courbe d'équity cumulée).
- **Capacité** : non émise (nécessite la profondeur exécutable par coin ; seul `n` = nb d'épisodes est connu).
- **Maker/taker** : non séparé (markouts pris côté **taker** ; la voie maker n'a pas été re-mesurée ici).
- **Stress coûts 50 %** : critère prévu, non appliqué par mesure (inutile ici — l'edge est déjà négatif à coût nominal, le stress ne peut qu'aggraver).
- **DSR / PBO par mécanisme** : non émis par mesure ; le verdict s'appuie sur PF + net (tous deux catastrophiques). DSR/PBO seraient requis pour ARMER un candidat — il n'y en a aucun.

## Verdict global
**Aucun candidat.** Tous les mécanismes mesurables sont **KILL** : PF ≪ 1.2 et net médian négatif au holdout. Après frais + spread + slippage, ces micro-signaux natifs n'ont **pas d'edge net**. C'est cohérent avec la loi mesurée du projet : ce qui ne survit pas aux coûts est écarté — **pas de faux gagnant**.

- **KILL** (7) : OFI_TOP1, OFI_TOP5, OFI_TOP20, QUEUE_MICROPRICE, LIQUIDITY_VACUUM, HL_ABSORPTION_NATIVE, TRADE_SWEEP_BURST
- **DATA_MISSING** (3, honnête, aucun chiffre inventé) : OI_VEL_ACCEL_PRICE_FUNDING, FUNDING_CLOCK_DIVERGENCE, LIQUIDATION_CASCADE_DEPTH

## Plan de demain
1) Ne PAS armer ces familles (mesurées KILL). 2) Chercher l'edge AILLEURS que dans la micro-structure native OFI/queue/absorption (déjà réfutée). 3) Compléter les 3 DATA_MISSING (OI/funding-clock/liquidation) — collecteur d'événements — avant de conclure sur eux.

---
**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
