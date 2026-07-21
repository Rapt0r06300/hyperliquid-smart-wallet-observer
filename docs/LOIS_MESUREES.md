# Les lois mesurées — ce que NOS chiffres ont déjà tranché

> Généré depuis `src/hl_observer/research/lois_mesurees.py` (source unique).
> Une loi n'est pas un interdit de penser : c'est un **chiffre à battre**, avec la
> **donnée** qui justifierait de rouvrir le dossier. Un argument neuf ne suffit pas.

## 🔴 Réfuté par la mesure (10)

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

### Le z-score du funding comme signal de taille — `zscore_au_plancher`

- **le chiffre** : corrélation −0,596 entre le facteur de taille et le rendement net : on finançait le PLUS les coins les MOINS rentables. Au plancher protocolaire, tous les coins sont au même taux par construction — le z-score y mesure du bruit
- **mesuré le** : 2026-07-21
- **pour rouvrir** : un funding franchement AU-DESSUS du plancher (le garde du plancher réactive alors le z-score automatiquement)
- **où vérifier** : `funding/carry_optimizer.py:facteur_zscore + carry_allocation_nette.py`

## 🟠 Réel mais insuffisant en l'état (2)

### Le vault HLP comme référence à battre — `hlp_benchmark`

- **le chiffre** : mesuré à −0,01 % APR sur notre fenêtre : le battre ne prouve pas grand-chose, mais faire MOINS bien qu'un dépôt passif reste dominé
- **mesuré le** : 2026-07-14
- **pour rouvrir** : re-mesurer HLP sur une fenêtre plus longue
- **où vérifier** : `mémoire projet : benchmark HLP`

### Arbitrer une dislocation de prix Hyperliquid ↔ Binance — `arbitrage_cross_venue`

- **le chiffre** : l'écart CONVERGE (−2,26 bps à 30 min, 64,9 % des cas) mais MOINS que les 8 bps d'aller-retour : edge net négatif en moyenne. Seuls les écarts extrêmes paient — à 8 bps d'ouverture : 19 entrées, capture moyenne 8,53 bps
- **mesuré le** : 2026-07-21
- **pour rouvrir** : la même mesure sur ≥ 5 000 écarts (la cadence est passée à 60 s le 21/07 pour ça) — si la capture tient au-dessus de 8 bps, le seuil descend de 15 à ~8
- **où vérifier** : `backtesting/arb_backtest.py + runtime/replay/BACKTEST_ARBITRAGE.md`

## 🟢 Confirmé — en production (1)

### Carry delta-neutre (long spot + short perp) sur Hyperliquid — `carry_delta_neutre`

- **le chiffre** : le SEUL chiffre positif du projet : ~2 % APR mesuré sur HYPE (13/07) ; +0,35 $/j sur 11 positions au 21/07, coûts payés
- **mesuré le** : 2026-07-13
- **pour rouvrir** : —  c'est la stratégie en production ; à re-mesurer si le funding quitte le plancher protocolaire
- **où vérifier** : `funding/delta_neutral_carry.py + backtesting/carry_backtest.py`

---

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
