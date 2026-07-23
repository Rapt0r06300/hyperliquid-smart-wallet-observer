# Rapport quotidien HyperSmart — 23/07/2026 10:55

_Chaque chiffre se remonte à un fichier (ledger, positions, journaux). Fenêtre : dernières 24 h._

## 1. PnL réalisé (dernières 24 h)

- `ARB_STOP_ECART_AGGRAVE` : **-3.1958 $** (×12)
- `ARB_CONVERGENCE_CAPTUREE` : **+0.0412 $** (×1)
- `ARB_AGE_MAX_SANS_CONVERGENCE` : **+0.4394 $** (×6)

**Total 24 h : -2.7152 $** · 19 fermeture(s)

Total historique (toutes époques, jamais maquillé) : **-8.1455 $** sur 76 fermetures.

## 2. Positions ouvertes (paper)

- **AVAX** : 229 $ à 2.0x · âge 42.7 h · funding accru +0.0000 $
- **AZTEC** : 78 $ à 1.5x · âge 66.9 h · funding accru +0.0641 $
- **BTC** : 1180 $ à 5.0x · âge 64.7 h · funding accru +0.6442 $
- **ETH** : 271 $ à 2.0x · âge 64.7 h · funding accru +0.1687 $
- **HYPE** : 105 $ à 1.5x · âge 86.9 h · funding accru +0.0961 $
- **MON** : 128 $ à 1.0x · âge 64.1 h · funding accru +0.1012 $
- **PURR** : 164 $ à 1.5x · âge 73.0 h · funding accru +0.1141 $
- **SOL** : 136 $ à 1.5x · âge 64.7 h · funding accru +0.0966 $
- **STABLE** : 189 $ à 1.5x · âge 61.4 h · funding accru +0.1451 $
- **VIRTUAL** : 174 $ à 1.5x · âge 64.5 h · funding accru +0.1031 $
- **XPL** : 77 $ à 1.0x · âge 64.7 h · funding accru +0.0540 $
- **ZEC** : 79 $ à 1.0x · âge 39.5 h · funding accru +0.0391 $

## 3. Santé du système

- Collecteurs : 4/4 vivants.
- Superviseur : relances cumulées {'carry-feeder': 1, 'marks-collector': 1, 'liq-collector': 1, 'venues-collector': 2, 'rapport-quotidien': 1}

## 4. Mesures en cours

- Cross-venue : **91.5 h / 72 h** (279050 observations) — verdict aux barres pré-écrites, jamais avant.
- Usine à données replay (24 h) : **57581 candidats** · **368505 marks** — c'est le carburant du replay A/B.

## 5. Refus dominants (24 h) — le bot explique pourquoi il n'ouvre pas

Aucun refus sur la fenêtre (ou aucune décision).

## 6. Leçons du ledger — aucune perte sans explication

16 perte(s), -3.4112 $ au total :
- ✔ BADGER -0.0800 $ `ARB_AGE_MAX_SANS_CONVERGENCE` (attendu : l'ecart n'a pas converge avant l'age max -> on coupe, on paie le cout )
- ✔ BNT -0.5008 $ `ARB_STOP_ECART_AGGRAVE` (attendu : l'ecart s'est ELARGI dans notre dos (>= entree + 25 bps) -> on coupe p)
- ✔ ARK -0.2066 $ `ARB_STOP_ECART_AGGRAVE` (attendu : l'ecart s'est ELARGI dans notre dos (>= entree + 25 bps) -> on coupe p)
- ✔ ARK -0.2299 $ `ARB_STOP_ECART_AGGRAVE` (attendu : l'ecart s'est ELARGI dans notre dos (>= entree + 25 bps) -> on coupe p)
- ✔ BNT -0.2212 $ `ARB_STOP_ECART_AGGRAVE` (attendu : l'ecart s'est ELARGI dans notre dos (>= entree + 25 bps) -> on coupe p)
- ✔ BNT -0.2922 $ `ARB_STOP_ECART_AGGRAVE` (attendu : l'ecart s'est ELARGI dans notre dos (>= entree + 25 bps) -> on coupe p)
- ✔ ARK -0.2229 $ `ARB_STOP_ECART_AGGRAVE` (attendu : l'ecart s'est ELARGI dans notre dos (>= entree + 25 bps) -> on coupe p)
- ✔ BNT -0.3000 $ `ARB_STOP_ECART_AGGRAVE` (attendu : l'ecart s'est ELARGI dans notre dos (>= entree + 25 bps) -> on coupe p)
- ✔ ARK -0.0289 $ `ARB_AGE_MAX_SANS_CONVERGENCE` (attendu : l'ecart n'a pas converge avant l'age max -> on coupe, on paie le cout )
- ✔ BNT -0.0555 $ `ARB_AGE_MAX_SANS_CONVERGENCE` (attendu : l'ecart n'a pas converge avant l'age max -> on coupe, on paie le cout )
- ✔ ARK -0.2784 $ `ARB_STOP_ECART_AGGRAVE` (attendu : l'ecart s'est ELARGI dans notre dos (>= entree + 25 bps) -> on coupe p)
- ✔ BNT -0.2134 $ `ARB_STOP_ECART_AGGRAVE` (attendu : l'ecart s'est ELARGI dans notre dos (>= entree + 25 bps) -> on coupe p)
- ✔ ARK -0.0510 $ `ARB_AGE_MAX_SANS_CONVERGENCE` (attendu : l'ecart n'a pas converge avant l'age max -> on coupe, on paie le cout )
- ✔ ARK -0.2351 $ `ARB_STOP_ECART_AGGRAVE` (attendu : l'ecart s'est ELARGI dans notre dos (>= entree + 25 bps) -> on coupe p)
- ✔ BNT -0.2833 $ `ARB_STOP_ECART_AGGRAVE` (attendu : l'ecart s'est ELARGI dans notre dos (>= entree + 25 bps) -> on coupe p)
- ✔ BNT -0.2121 $ `ARB_STOP_ECART_AGGRAVE` (attendu : l'ecart s'est ELARGI dans notre dos (>= entree + 25 bps) -> on coupe p)

## 7. PnL des refus (hebdo) — combien coûtent nos portes ?

_Calculé il y a 2.1 j (cadence : hebdo). Simulation sur candidats refusés enregistrés — pas une promesse._

- `?` : ×435768 refus, 189688 mesurés, PnL simulé si on avait ouvert : -21388.03 $
- non mesurables (pas de marks sur la fenêtre) : ×246080 — comptés, jamais inventés

> PnL SIMULE de trades qu'on n'a PAS pris ; un refus couteux = re-mesurer la porte au replay complet, jamais l'ouvrir sur ce chiffre

## 8. Carry — l'économie de chaque position ($/jour, amortissement)

| coin | marge | notional | funding b/h | $/jour | accru | coût d'entrée | amortie ? |
|---|---|---|---|---|---|---|---|
| AVAX | 114$ | 229$ | 0.125 | 0.0686$ | 0.0000$ | 0.3262$ | dans ~114 h |
| AZTEC | 52$ | 78$ | 0.125 | 0.0233$ | 0.0641$ | 0.1277$ | dans ~65 h |
| BTC | 236$ | 1180$ | 0.125 | 0.3539$ | 0.6442$ | 1.3376$ | dans ~47 h |
| ETH | 135$ | 271$ | 0.125 | 0.0812$ | 0.1687$ | 0.2062$ | dans ~11 h |
| HYPE | 70$ | 105$ | 0.125 | 0.0316$ | 0.0961$ | 0.1322$ | dans ~27 h |
| MON | 128$ | 128$ | 0.125 | 0.0385$ | 0.1012$ | 0.1731$ | dans ~45 h |
| PURR | 109$ | 164$ | 0.125 | 0.0492$ | 0.1141$ | 0.1567$ | dans ~21 h |
| SOL | 90$ | 136$ | 0.125 | 0.0407$ | 0.0966$ | 0.1539$ | dans ~34 h |
| STABLE | 126$ | 189$ | 0.125 | 0.0567$ | 0.1451$ | 0.5549$ | dans ~173 h |
| VIRTUAL | 116$ | 174$ | 0.125 | 0.0523$ | 0.1031$ | 0.3767$ | dans ~126 h |
| XPL | 77$ | 77$ | 0.125 | 0.0230$ | 0.0540$ | 0.0993$ | dans ~47 h |
| ZEC | 79$ | 79$ | 0.125 | 0.0238$ | 0.0391$ | 0.0605$ | dans ~22 h |

**Total : 0.8429 $/jour au taux courant · marge engagée 1334 $** (déploiement à comparer au capital — la réserve de 20 % est voulue).

## 9. Scan carry — univers, viables, et presque-viables (avec leur verrou)

_20 coin(s) perp∩spot, 6 VIABLE(S) (top-6 retenus par carry net)._

**Viables (6)** : BTC (+0.125b, liq 489k) · ETH (+0.125b, liq 386k) · PURR (+0.125b, liq 22k) · XPL (+0.125b, liq 40k) · ZEC (+0.125b, liq 63k) · SOL (+0.054b, liq 100k)

**Bloqués — et par QUOI (le verrou est une info, pas une fatalité) :**

- `STABLE` (+1.794b, liq 0k) → spot HL trop mince : 319 $ < 2500 $ (notionnel cible 500 x securite 5.0)
- `AZTEC` (+0.125b, liq 3k) → break-even trop lent (356 h > 235 h) : le funding ne rembourse pas le cout d'entree assez vite -> on ATTEND (aucune saignee de couts)
- `BERA` (+0.125b, liq 0k) → base aberrante: perp 0.1941$ vs spot @117 0.001335$ (x145 -> pas de vrai spot jumelable)
- `ENA` (+0.125b, liq 1k) → spot HL trop mince : 955 $ < 2500 $ (notionnel cible 500 x securite 5.0)
- `ETHFI` (+0.125b, liq 381k) → refuse jusqu'au levier le plus bas (1.0x) : LA_BASE_COUTE_PLUS_QUE_LE_FUNDING_NE_RAPPORTE
- `FARTCOIN` (+0.125b, liq 73k) → refuse jusqu'au levier le plus bas (1.0x) : LE_PIRE_MOUVEMENT_OBSERVE_AURAIT_LIQUIDE_LA_JAMBE_PERP [levier max venue 10x -> marge de maintenance 5.0 % ; pire hausse stressee 97 %]
- `MEGA` (+0.125b, liq 0k) → spot HL trop mince : 0 $ < 2500 $ (notionnel cible 500 x securite 5.0)
- `MON` (+0.125b, liq 1k) → spot HL trop mince : 1286 $ < 2500 $ (notionnel cible 500 x securite 5.0)
- `PUMP` (+0.125b, liq 30k) → refuse jusqu'au levier le plus bas (1.0x) : LE_PIRE_MOUVEMENT_OBSERVE_AURAIT_LIQUIDE_LA_JAMBE_PERP [levier max venue 10x -> marge de maintenance 5.0 % ; pire hausse stressee 123 %]
- `TRUMP` (+0.125b, liq 0k) → base aberrante: perp 1.636$ vs spot @9 0.0004553$ (x3594 -> pas de vrai spot jumelable)
- `WLD` (+0.125b, liq 0k) → spot HL trop mince : 0 $ < 2500 $ (notionnel cible 500 x securite 5.0)
- `AVAX` (+0.062b, liq 23k) → break-even trop lent (573 h > 235 h) : le funding ne rembourse pas le cout d'entree assez vite -> on ATTEND (aucune saignee de couts)

## 10. Où va le capital (allocation)

- règle : `marge ∝ gain_net_24h_bps ** 3, plafond 40 % par coin, plancher 25 $`
- capital alloué : **799.99 $** sur 7 coin(s) financé(s)
- rendement pondéré : **1.8411 bps/j** (part égale : 1.6704 bps/j -> **10.22 %** de mieux)
- meilleur coin : **BTC**

| coin | rendement net (bps/j) | marge cible ($) |
|---|---:|---:|
| BTC | 2.266 | 259.4 |
| PURR | 1.869 | 145.55 |
| ETH | 1.756 | 120.71 |
| SOL | 1.536 | 80.79 |
| STABLE | 1.513 | 77.21 |
| ZEC | 1.392 | 60.13 |
| XPL | 1.361 | 56.2 |

## 11. Qui sort du plancher de funding

- part globale du temps passé **au-dessus** du plancher : **0.0 %** (sur 15 coin(s) exploitables)
- meilleur coin : **AVAX**

| coin | temps hors plancher |
|---|---:|
| AVAX | 0.0 % |
| AZTEC | 0.0 % |
| BTC | 0.0 % |
| ETH | 0.0 % |
| ETHFI | 0.0 % |
| FARTCOIN | 0.0 % |
| HYPE | 0.0 % |
| MON | 0.0 % |
| PUMP | 0.0 % |
| PURR | 0.0 % |

_statistique DESCRIPTIVE d'un passé — jamais une probabilité de sortir demain._

## 12. Ce qui est déjà tranché (lois mesurées)

_16 loi(s) : 13 réfutée(s), 2 limite(s), 1 confirmée(s). Détail complet : `docs/LOIS_MESUREES.md`. Une loi se rouvre avec une DONNÉE neuve, pas un argument neuf._

- 🟢 **Carry delta-neutre (long spot + short perp) sur Hyperliquid** — le SEUL chiffre positif du projet : ~2 % APR mesuré sur HYPE (13/07) ; +0,35 $/j sur 11 positions au 21/07, coûts payés
- 🟠 **Le coût all-in d'un aller-retour d'arbitrage vaut 16 bps, pas 8** — le forfait `COUT_AR_BPS = 8` ne comptait que 2 exécutions sur 4 et oubliait les frais de la 2ᵉ venue. Coût all-in réel : **16,0 bps** (13 de frais + 2 de spread + 1 d'adverse selection). C'est un FAIT de coût — le moteur price désormais juste. Ce que ce coût implique pour la RENTABILITÉ est une autre question, tranchée trade par trade par les portes (cf. `arbitrage_cross_venue`)
- 🟠 **Arbitrer une dislocation de prix Hyperliquid ↔ Binance** — **réalisé PAPER : +0,54 $ sur 15 trades, 13 gagnants / 2 perdants** (les 2 perdants = MKR figé, désormais bloqué par la porte de vivacité). La population moyenne des signaux est négative (coût all-in 16 bps > convergence ~3,4 bps), MAIS le moteur ne trade que le sous-ensemble filtré (vivacité + convergence capturée) et ce sous-ensemble est positif. Échantillon petit — à confirmer

🔴 Réfutées (ne pas ré-ouvrir sans donnée neuve) : `arb_ecart_fige`, `carry_plancher_domine`, `copy_global`, `copy_leader_contrarien`, `latence`, `market_making_spread`, `spread_prix_du_risque`, `funding_perp_perp`, `couverture_meme_actif`, `lead_lag`, `rendement_negatif_domine`, `hlp_benchmark`, `zscore_au_plancher`

## 13. À FAIRE — ce que les données d'aujourd'hui désignent

- **Cross-venue : 72 h atteintes (91 h)** → lancer `python tools/mesurer_dispersion_venues.py` pour LE verdict (#178).
- Relances de collecteurs au compteur : {'carry-feeder': 1, 'marks-collector': 1, 'liq-collector': 1, 'venues-collector': 2, 'rapport-quotidien': 1} — si un compteur grimpe SEUL demain, c'est lui le malade (doc R5).
- Copy-whitelist : 3 leader(s) prouvé(s) → copy peut suivre CES leaders uniquement.
- Markout copy : 90.0% des fills mesures (25154/27951) — le pipeline nourrit la whitelist.
- Replay : 592377 candidats consolidés → `RECHERCHE-SCENARIO-REPLAY.cmd` a de quoi travailler (porte deux-moitiés + plateau).

---
**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**