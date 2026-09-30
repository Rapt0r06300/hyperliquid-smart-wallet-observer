# HYPERSMART — OFI + MICROPRICE + DÉSÉQUILIBRE DE CARNET (carnet L2 RÉEL HL) — 2026-07-31

> Idées portées de la littérature microstructure (GitHub + papiers), implémentées proprement et **mesurées
> causalement sur ton carnet L2 réel** (`runtime/replay/l2_book.*.jsonl`, extraits `_ofi_{COIN}.csv`).
> Discipline dure : causalité stricte, DISCOVERY→FREEZE→OOS INTACT, votes rendus indépendants par bucket
> temporel (600 s), LCB bootstrap maison (`following/scoring_robuste`), coûts exécutables réels déduits.
> **Aucun vert fabriqué.** Module : `research/ofi_microprice.py` (9 tests verts). Commit `08c0ebf`.

## Sources d'idées
- **OFI** — Cont, Kukanov & Stoikov (2014), *The price impact of order book events*.
- **Microprice** — Stoikov (2018), *The micro-price: a high-frequency estimator of future prices*.
- **Déséquilibre de carnet** (queue L1 + profondeur USD) — prédicteur directionnel court terme classique.

## Données
Snapshots de carnet HL ~toutes les **17,8 s** (médiane), sur ~366 h (avec trous de collecte, gérés :
toute fenêtre enjambant un trou > 60 s est refusée). BTC 41 847 · ETH 41 456 · SOL 19 492 · HYPE 41 658.

## Le fait n°1 : l'effet OFI→prix est RÉEL… mais contemporain (donc NON tradable)
Régression `Δmid[t] ~ OFI[t]` (même pas) — **R² réel et fort**, confirme Cont-Kukanov-Stoikov sur HL :

| Coin | R² OFI→Δmid (contemporain) |
|---|---|
| BTC | 0.108 |
| ETH | 0.225 |
| SOL | 0.250 |
| HYPE | 0.150 |

C'est une **preuve que le signal existe** : le flux au carnet explique 11–25 % du mouvement de mid
**simultané**. Mais « simultané » = déjà arrivé quand on le voit → **on ne peut pas le trader**.

## Le fait n°2 : le pouvoir PRÉDICTIF (pas suivant) est réel mais minuscule → tué par les frais
`feature[t]` (causal) → markout `mid(t)→mid(t+h)` strictement futur, direction = signe(feature). Meilleure
cellule par coin (le GROSS est positif partout : le carnet prédit **bien** le sens — juste trop peu) :

| IDEA | DATA | N indép. | GROSS bps | COST bps | NET bps | LCB net | OOS | FORWARD | CAPACITY | VERDICT |
|---|---|---|---|---|---|---|---|---|---|---|
| Déséq. profondeur (BTC, h=2) | l2_book 41.8k | 389 votes | +1.51 | 9 + spread | **−7.67** | −7.97 | oui (net<0) | — | non mesurée | **KILL** |
| Déséq. queue L1 (ETH, h=2) | l2_book 41.5k | 460 votes | +1.90 | 9 + spread | **−7.65** | −7.91 | oui (net<0) | — | — | **KILL** |
| Déséq. profondeur (SOL, h=1) | l2_book 19.5k | 218 votes | +1.26 | 9 + spread | **−7.92** | −8.20 | oui (net<0) | — | — | **KILL** |
| Déséq. queue L1 (HYPE, h=3) | l2_book 41.7k | 540 votes | +1.62 | 9 + spread | **−7.63** | −8.27 | oui (net<0) | — | — | **KILL** |
| OFI L1 (tous coins, h=1–3) | l2_book | 245–597 votes | +0.71…+1.19 | 9 + spread | −8.0…−8.7 | <0 | oui | — | — | **KILL** |
| Tilt microprix (tous coins) | l2_book | 269–653 votes | +0.65…+1.42 | 9 + spread | −8.1…−8.8 | <0 | oui | — | — | **KILL** |

**48 cellules mesurées (4 coins × 4 features × 3 horizons) : 48 KILL au taker.** Le GROSS prédictif brut
plafonne à **~1–2 bps** ; le coût taker HL (≈ 9 bps frais + spread) l'écrase. LCB net < 0 partout.

### Sensibilité MAKER (optimiste, plancher) — reste négative
Même en supposant une exécution **maker** parfaite (3 bps de frais seuls, aucun spread payé, et — hypothèse
généreuse — **en ignorant la sélection adverse**), le net OOS reste **−1,1 à −2,3 bps**, LCB < 0. Or la
sélection adverse frappe précisément ces signaux (poster du côté que le signal favorise = se faire remplir
quand le marché tourne contre soi). Donc même le maker « meilleur cas plausible » **ne survit pas**.

## Conclusion honnête
Les trois idées (OFI, microprice, déséquilibre) sont **réelles et correctement orientées** (gross positif,
R² contemporain fort) mais, à la résolution disponible (~18 s), leur amplitude prédictive (~1–2 bps) est
**très inférieure aux frais HL**. Verdict : **KILL au taker, non viable même au maker optimiste.** Cela
**confirme et renforce** le constat du sprint lead-lag : le mur, c'est le coût par trade, pas l'absence de
signal.

## Ce que ça change pour la suite (constructif, non fabriqué)
1. **Ne pas trader ces signaux en standalone.** Aucune des 4 features n'est un edge net.
2. **Leur seule valeur = filtre d'EXÉCUTION** pour une stratégie qui a *déjà* une raison de trader et clôt
   déjà les coûts (ex. le wallet survivant `0x1e9b03ec06` s'il valide en forward) : utiliser le microprix /
   déséquilibre pour **temporiser l'entrée** de quelques secondes et grappiller un peu de sélection adverse.
   C'est un gain de 2ᵉ ordre, pas de l'alpha autonome — à mesurer seulement sur une stratégie déjà positive.
3. **Pour tester un vrai maker OFI, il faut de la donnée HAUTE FRÉQUENCE** avec tailles bid/ask séparées sur
   plusieurs niveaux. Aujourd'hui : `l2_book` = snapshots d'état à 18 s (trop lents pour capturer le flux) ;
   `bbo_synchro` = 275 ms mais une seule taille top agrégée (pas d'OFI vrai). **Reco data** : logger le L2
   multi-niveaux HL à haute cadence (tailles par côté) → seule voie pour trancher le maker OFI honnêtement.
4. **La vérité reste la vérité :** l'edge net-positif prouvé est toujours absent. Les deux seules pistes non
   fabriquées restent (a) lead-lag choc-fort **sous maker** (ETH, N trop faible → plus de data) et (b) le
   wallet survivant `0x1e9b03ec06` (**forward requis**). L'OFI/microprice ne les remplace pas ; il peut, au
   mieux, en améliorer l'exécution une fois l'une d'elles prouvée.
