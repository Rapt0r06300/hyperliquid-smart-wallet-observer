# Les lois mesurées — ce que NOS chiffres ont déjà tranché

> Généré depuis `src/hl_observer/research/lois_mesurees.py` (source unique).
> Une loi n'est pas un interdit de penser : c'est un **chiffre à battre**, avec la
> **donnée** qui justifierait de rouvrir le dossier. Un argument neuf ne suffit pas.

## 🔴 Réfuté par la mesure (14)

### Lead-lag cross-venue Binance→HL en TAKER scalp : aucun edge (le choc ne précède pas HL) — `cross_venue_leadlag_taker_no_edge`

- **le chiffre** : sur données RÉELLES live (bbo_tape : BIN bookTicker + aggTrades + HL BBO, horloge locale recu_ns) : gross markout ~0,2 bps/épisode (AGG_IMBALANCE/TAKER_BURST) à ~1,5 (PRICE_SHOCK) vs coût A/R HL ~10-14 bps (spread plein ask-entrée/bid-sortie + 9 bps taker) → net ~−10 à −11 bps/épisode sur les 3 familles ET les 5 horizons (250 ms-5 s) ; placebo directionnel ≈ net ⇒ aucune directionnalité (coût pur). Ratio signal:coût ≈ 1:50.
- **mesuré le** : 2026-07-25
- **pour rouvrir** : entrée MAKER (post-only, éviter le spread) — MAIS MM HL mesuré 0/29 la rend improbable ; OU un choc bien plus rare/extrême dont le markout dépasse le coût A/R HL.
- **où vérifier** : `tools/rapid_alpha_run.py · src/hl_observer/experimental/cross_venue_events.py`

### Un gros écart entre venues est une grosse opportunité — `arb_ecart_fige`

- **le chiffre** : MKR affichait 71,44 bps sur **208 observations avec un écart-type de 0,0000** (min = max). Le seau 40+ bps convergeait à **0 %** sur 176 observations, quand le seau 10-20 bps convergeait à 86 %. Le plus gros écart de l'univers était le seul à franchir le seuil — et le seul à ne jamais bouger
- **mesuré le** : 2026-07-21
- **pour rouvrir** : aucune pour un écart figé : sigma nul = prix périmé, contrat différent ou mauvais appariement. Un écart CAPTURABLE fluctue
- **où vérifier** : `funding/arb_cout_all_in.ecart_vivant + arb_dislocation_paper.tick`

### Un carry au plancher protocolaire vaut la peine d'être ouvert — `carry_plancher_domine`

- **le chiffre** : 12/12 positions ouvertes et 580/580 lectures de scan au plancher (0,125 bps/h) → **APR net 2,65 %** contre **15-30 %** pour le vault HLP. Il faut **0,2660 bps/h, soit 2,13 × le plancher**, juste pour égaler la borne basse. 1 343,61 $ de marge dormaient sous l'alternative
- **mesuré le** : 2026-07-21
- **pour rouvrir** : un funding durablement au-dessus de 0,266 bps/h — le journal de scans le dira. Positif ne suffit pas : il faut battre l'alternative disponible
- **où vérifier** : `funding/carry_benchmark_gate.py (branché sur porte_risque_ouverture)`

### Suivre les wallets « smart money » en moyenne — `copy_global`

- **le chiffre** : −7,97 bps sur 24 133 signaux hors échantillon, MÊME à coût zéro
- **mesuré le** : 2026-07-11
- **pour rouvrir** : un sous-ensemble de leaders au markout forward POSITIF, prouvé sur ≥ 30 fills chacun (c'est ce que fait la whitelist)
- **où vérifier** : `tools/ecrire_copy_whitelist.py + copy_wallet/leader_markout.py`

### La CAUSE du précédent : le leader moyen est contrarien — `copy_leader_contrarien`

- **le chiffre** : le prix court CONTRE le leader de −7,75 bps AVANT même son fill
- **mesuré le** : 2026-07-14
- **pour rouvrir** : mesurer un leader dont le markout AVANT fill est positif — sinon la vitesse ne sert à rien, le problème est le CONTENU
- **où vérifier** : `docs/audit/ — Q1→Q3 edge mesuré`

### Être plus rapide améliorerait le copy — `latence`

- **le chiffre** : sur les 24 133 signaux, la courbe edge/horizon est PLATE : raccourcir l'horizon ne fait pas remonter l'edge au-dessus de 0
- **mesuré le** : 2026-07-11
- **pour rouvrir** : une courbe edge/horizon en PENTE sur des données neuves
- **où vérifier** : `mémoire projet : courbe edge/horizon`

### Faire le marché à l'intérieur du spread (T1/T1b) — `market_making_spread`

- **le chiffre** : 0 gagnant sur 29 coins, mesuré à 100 % de fill (borne HAUTE, impossible en vrai) ; le prix bouge 5 à 30× le spread
- **mesuré le** : 2026-07-13
- **pour rouvrir** : un marché où le prix bouge MOINS que le spread — aucun de nos 29 coins n'était dans ce cas
- **où vérifier** : `mémoire projet : T1b fermé, 0/29`

### Le spread est un revenu à capter — `spread_prix_du_risque`

- **le chiffre** : corollaire du 0/29 de T1b : le spread n'est jamais un cadeau, c'est le PRIX du risque d'inventaire — le prix bouge 5 à 30× le spread encaissé
- **mesuré le** : 2026-07-13
- **pour rouvrir** : un modèle qui montre l'inventaire couvert à coût nul
- **où vérifier** : `mémoire projet : T1b`

### Arbitrer le funding entre deux perps (X-04) — `funding_perp_perp`

- **le chiffre** : 0 opportunité nette sur 120 mesurées
- **mesuré le** : 2026-07-13
- **pour rouvrir** : deux perps du MÊME actif (une couverture ne vaut que si c'est le même sous-jacent — loi `couverture_meme_actif`)
- **où vérifier** : `funding/funding_spread_perp_perp.py`

### Couvrir un actif par un actif corrélé — `couverture_meme_actif`

- **le chiffre** : corollaire du 0/120 de X-04 : une couverture ne vaut QUE si c'est le même actif — sinon la base résiduelle dépasse l'edge visé
- **mesuré le** : 2026-07-13
- **pour rouvrir** : jamais sur corrélation seule ; seulement sur identité d'actif
- **où vérifier** : `X-04 / #242`

### BTC mène, les alts suivent (tradeable) — `lead_lag`

- **le chiffre** : 0 sur 66 paires ; BNB : corrélation instantanée +0,83 vs corrélation à 2 h −0,03. Les alts bougent AVEC BTC, ils ne le SUIVENT pas
- **mesuré le** : 2026-07-14
- **pour rouvrir** : une corrélation DÉCALÉE significative, mesurée hors échantillon
- **où vérifier** : `mémoire projet : #549`

### Une stratégie à rendement négatif peut être sauvée par le sizing — `rendement_negatif_domine`

- **le chiffre** : arithmétique : −1 bps × n'importe quelle taille reste sous les 0 bps du cash — le sizing multiplie, il ne change pas le signe
- **mesuré le** : 2026-07-13
- **pour rouvrir** : aucune — c'est de l'arithmétique
- **où vérifier** : `mémoire projet : benchmark CASH`

### Le vault HLP comme référence à battre — `hlp_benchmark`

- **le chiffre** : 🔴 CORRIGÉ le 21/07 : notre mesure interne disait −0,01 % APR — elle portait sur une fenêtre trop courte. La donnée PUBLIQUE 2026 dit **15 à 30 % APR** sur la plupart des fenêtres trimestrielles (drawdowns 5-12 %). Notre carry vaut ~12,9 %/an : **un dépôt passif dans HLP nous bat**. La stratégie est DOMINÉE par une alternative sans code, sans surveillance et sans risque d'exécution
- **mesuré le** : 2026-07-21
- **pour rouvrir** : que le carry dépasse durablement 30 % APR net, OU que HLP s'effondre. Attention : HLP n'est PAS delta-neutre (il porte du risque directionnel et de liquidation) — la comparaison est brutale mais pas parfaitement égale à risque
- **où vérifier** : `defillama.com/protocol/hyperliquid-hlp (public) + carry_backtest`

### Le z-score du funding comme signal de taille — `zscore_au_plancher`

- **le chiffre** : corrélation −0,596 entre le facteur de taille et le rendement net : on finançait le PLUS les coins les MOINS rentables. Au plancher protocolaire, tous les coins sont au même taux par construction — le z-score y mesure du bruit
- **mesuré le** : 2026-07-21
- **pour rouvrir** : un funding franchement AU-DESSUS du plancher (le garde du plancher réactive alors le z-score automatiquement)
- **où vérifier** : `funding/carry_optimizer.py:facteur_zscore + carry_allocation_nette.py`

## 🟠 Réel mais insuffisant en l'état (2)

### Le coût all-in d'un aller-retour d'arbitrage vaut 16 bps, pas 8 — `arb_dislocation_cout_all_in`

- **le chiffre** : le forfait `COUT_AR_BPS = 8` ne comptait que 2 exécutions sur 4 et oubliait les frais de la 2ᵉ venue. Coût all-in réel : **16,0 bps** (13 de frais + 2 de spread + 1 d'adverse selection). C'est un FAIT de coût — le moteur price désormais juste. Ce que ce coût implique pour la RENTABILITÉ est une autre question, tranchée trade par trade par les portes (cf. `arbitrage_cross_venue`)
- **mesuré le** : 2026-07-22
- **pour rouvrir** : aucune — arithmétique de frais (doc HL tier 0). Si HL change ses frais, on re-mesure
- **où vérifier** : `funding/arb_cout_all_in.py`

### Arbitrer une dislocation de prix Hyperliquid ↔ Binance — `arbitrage_cross_venue`

- **le chiffre** : **réalisé PAPER : +0,54 $ sur 15 trades, 13 gagnants / 2 perdants** (les 2 perdants = MKR figé, désormais bloqué par la porte de vivacité). La population moyenne des signaux est négative (coût all-in 16 bps > convergence ~3,4 bps), MAIS le moteur ne trade que le sous-ensemble filtré (vivacité + convergence capturée) et ce sous-ensemble est positif. Échantillon petit — à confirmer
- **mesuré le** : 2026-07-22
- **pour rouvrir** : RESTE OUVERTE : accumuler plus de trades GATÉS (pas la population) et vérifier que le profit factor tient au-dessus de 1 sur ≥ 50 trades. Le sous-ensemble filtré est ce qui compte, jamais la population brute que le moteur refuse
- **où vérifier** : `ledger arbitrage (13/15 gagnants) + backtesting/arb_backtest.py`

## 🟢 Confirmé — en production (1)

### Carry delta-neutre (long spot + short perp) sur Hyperliquid — `carry_delta_neutre`

- **le chiffre** : le SEUL chiffre positif du projet : ~2 % APR mesuré sur HYPE (13/07) ; +0,35 $/j sur 11 positions au 21/07, coûts payés
- **mesuré le** : 2026-07-13
- **pour rouvrir** : —  c'est la stratégie en production ; à re-mesurer si le funding quitte le plancher protocolaire
- **où vérifier** : `funding/delta_neutral_carry.py + backtesting/carry_backtest.py`

---

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
