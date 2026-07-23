# Rapport quotidien HyperSmart — 23/07/2026 16:57

_Chaque chiffre se remonte à un fichier (ledger, positions, journaux). Fenêtre : dernières 24 h._

## 1. PnL réalisé (dernières 24 h)

- `MODULE_CARRY_DESACTIVE` : **-3.3242 $** (×6)
- `ARB_STOP_ECART_AGGRAVE` : **-3.1958 $** (×12)
- `DONNEE_ABSENTE_PROLONGEE` : **-1.4779 $** (×6)
- `ARB_AGE_MAX_SANS_CONVERGENCE` : **+0.6061 $** (×8)

**Total 24 h : -7.3918 $** · 32 fermeture(s)

Total historique (toutes époques, jamais maquillé) : **-12.7808 $** sur 90 fermetures.

## 2. Positions ouvertes (paper)

Aucune position ouverte.

## 3. Santé du système

- Collecteurs : **1 MUET(S)** — carry-feeder (silence 87.5 min)
- Superviseur : relances cumulées {'carry-feeder': 2, 'marks-collector': 2, 'liq-collector': 2, 'venues-collector': 3, 'rapport-quotidien': 1, 'carnet-collector': 1}

## 4. Mesures en cours

- Cross-venue : **97.5 h / 72 h** (341262 observations) — verdict aux barres pré-écrites, jamais avant.
- Usine à données replay (24 h) : **10 candidats** · **242128 marks** — c'est le carburant du replay A/B.

## 5. Refus dominants (24 h) — le bot explique pourquoi il n'ouvre pas

- ×10 `INPUTS_SPOT_PERIMES_NO_TRADE`

## 6. Leçons du ledger — aucune perte sans explication

28 perte(s), -8.2133 $ au total :
- 🔴 **RÉGRESSION** HYPE -0.1358 $ `DONNEE_ABSENTE_PROLONGEE` — cause reparee (e82dd4a+b6debb2) qui REVIENT apres le correctif : fermetures famine/rate-de-bougies : hors-shortlist gate par amortissement quand la donnee est vivante + cache pire-hausse 24 h. Le vrai blackout (0 mesure) reste une fermeture legitime -> demi-alarme seulement.
- 🔴 **RÉGRESSION** AZTEC -0.1070 $ `DONNEE_ABSENTE_PROLONGEE` — cause reparee (e82dd4a+b6debb2) qui REVIENT apres le correctif : fermetures famine/rate-de-bougies : hors-shortlist gate par amortissement quand la donnee est vivante + cache pire-hausse 24 h. Le vrai blackout (0 mesure) reste une fermeture legitime -> demi-alarme seulement.
- 🔴 **RÉGRESSION** VIRTUAL -0.2804 $ `DONNEE_ABSENTE_PROLONGEE` — cause reparee (e82dd4a+b6debb2) qui REVIENT apres le correctif : fermetures famine/rate-de-bougies : hors-shortlist gate par amortissement quand la donnee est vivante + cache pire-hausse 24 h. Le vrai blackout (0 mesure) reste une fermeture legitime -> demi-alarme seulement.
- 🔴 **RÉGRESSION** MON -0.1811 $ `DONNEE_ABSENTE_PROLONGEE` — cause reparee (e82dd4a+b6debb2) qui REVIENT apres le correctif : fermetures famine/rate-de-bougies : hors-shortlist gate par amortissement quand la donnee est vivante + cache pire-hausse 24 h. Le vrai blackout (0 mesure) reste une fermeture legitime -> demi-alarme seulement.
- 🔴 **RÉGRESSION** AVAX -0.5029 $ `DONNEE_ABSENTE_PROLONGEE` — cause reparee (e82dd4a+b6debb2) qui REVIENT apres le correctif : fermetures famine/rate-de-bougies : hors-shortlist gate par amortissement quand la donnee est vivante + cache pire-hausse 24 h. Le vrai blackout (0 mesure) reste une fermeture legitime -> demi-alarme seulement.
- 🔴 **RÉGRESSION** STABLE -0.2708 $ `DONNEE_ABSENTE_PROLONGEE` — cause reparee (e82dd4a+b6debb2) qui REVIENT apres le correctif : fermetures famine/rate-de-bougies : hors-shortlist gate par amortissement quand la donnee est vivante + cache pire-hausse 24 h. Le vrai blackout (0 mesure) reste une fermeture legitime -> demi-alarme seulement.
- 🔴 **INEXPLIQUÉE** PURR -0.4130 $ `MODULE_CARRY_DESACTIVE` — motif 'MODULE_CARRY_DESACTIVE' absent du registre : la leçon n'existe pas encore — autopsie due
- 🔴 **INEXPLIQUÉE** BTC -2.1315 $ `MODULE_CARRY_DESACTIVE` — motif 'MODULE_CARRY_DESACTIVE' absent du registre : la leçon n'existe pas encore — autopsie due
- 🔴 **INEXPLIQUÉE** ETH -0.2982 $ `MODULE_CARRY_DESACTIVE` — motif 'MODULE_CARRY_DESACTIVE' absent du registre : la leçon n'existe pas encore — autopsie due
- 🔴 **INEXPLIQUÉE** SOL -0.2138 $ `MODULE_CARRY_DESACTIVE` — motif 'MODULE_CARRY_DESACTIVE' absent du registre : la leçon n'existe pas encore — autopsie due
- 🔴 **INEXPLIQUÉE** XPL -0.1332 $ `MODULE_CARRY_DESACTIVE` — motif 'MODULE_CARRY_DESACTIVE' absent du registre : la leçon n'existe pas encore — autopsie due
- 🔴 **INEXPLIQUÉE** ZEC -0.1345 $ `MODULE_CARRY_DESACTIVE` — motif 'MODULE_CARRY_DESACTIVE' absent du registre : la leçon n'existe pas encore — autopsie due
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

_Calculé il y a 2.3 j (cadence : hebdo). Simulation sur candidats refusés enregistrés — pas une promesse._

- `?` : ×435768 refus, 189688 mesurés, PnL simulé si on avait ouvert : -21388.03 $
- non mesurables (pas de marks sur la fenêtre) : ×246080 — comptés, jamais inventés

> PnL SIMULE de trades qu'on n'a PAS pris ; un refus couteux = re-mesurer la porte au replay complet, jamais l'ouvrir sur ce chiffre

## 8. Carry — l'économie de chaque position ($/jour, amortissement)

Aucune position carry ouverte.

## 9. Scan carry — univers, viables, et presque-viables (avec leur verrou)

_20 coin(s) perp∩spot, 6 VIABLE(S) (top-6 retenus par carry net)._

**Viables (6)** : BTC (+0.125b, liq 473k) · HYPE (+0.125b, liq 186k) · XPL (+0.125b, liq 49k) · ZEC (+0.125b, liq 69k) · ETH (+0.102b, liq 334k) · SOL (-0.087b, liq 150k)

**Bloqués — et par QUOI (le verrou est une info, pas une fatalité) :**

- `AZTEC` (+0.125b, liq 3k) → break-even trop lent (305 h > 235 h) : le funding ne rembourse pas le cout d'entree assez vite -> on ATTEND (aucune saignee de couts)
- `BERA` (+0.125b, liq 0k) → base aberrante: perp 0.1901$ vs spot @117 0.001335$ (x142 -> pas de vrai spot jumelable)
- `ETHFI` (+0.125b, liq 343k) → refuse jusqu'au levier le plus bas (1.0x) : LA_BASE_COUTE_PLUS_QUE_LE_FUNDING_NE_RAPPORTE
- `FARTCOIN` (+0.125b, liq 32k) → refuse jusqu'au levier le plus bas (1.0x) : LE_PIRE_MOUVEMENT_OBSERVE_AURAIT_LIQUIDE_LA_JAMBE_PERP [levier max venue 10x -> marge de maintenance 5.0 % ; pire hausse stressee 97 %]
- `MEGA` (+0.125b, liq 0k) → spot HL trop mince : 0 $ < 2500 $ (notionnel cible 500 x securite 5.0)
- `MON` (+0.125b, liq 5k) → break-even trop lent (433 h > 235 h) : le funding ne rembourse pas le cout d'entree assez vite -> on ATTEND (aucune saignee de couts)
- `PUMP` (+0.125b, liq 32k) → refuse jusqu'au levier le plus bas (1.0x) : LE_PIRE_MOUVEMENT_OBSERVE_AURAIT_LIQUIDE_LA_JAMBE_PERP [levier max venue 10x -> marge de maintenance 5.0 % ; pire hausse stressee 123 %]
- `PURR` (+0.125b, liq 15k) → break-even trop lent (318 h > 235 h) : le funding ne rembourse pas le cout d'entree assez vite -> on ATTEND (aucune saignee de couts)
- `STABLE` (+0.125b, liq 27k) → break-even trop lent (282 h > 235 h) : le funding ne rembourse pas le cout d'entree assez vite -> on ATTEND (aucune saignee de couts)
- `TRUMP` (+0.125b, liq 0k) → base aberrante: perp 1.635$ vs spot @9 0.0004553$ (x3592 -> pas de vrai spot jumelable)
- `AVAX` (+0.091b, liq 22k) → break-even trop lent (589 h > 235 h) : le funding ne rembourse pas le cout d'entree assez vite -> on ATTEND (aucune saignee de couts)
- `ENA` (+0.001b, liq 1k) → spot HL trop mince : 1307 $ < 2500 $ (notionnel cible 500 x securite 5.0)

## 10. Où va le capital (allocation)

- règle : `marge ∝ gain_net_24h_bps ** 3, plafond 40 % par coin, plancher 25 $`
- capital alloué : **800.0 $** sur 6 coin(s) financé(s)
- rendement pondéré : **1.8163 bps/j** (part égale : 1.6043 bps/j -> **13.21 %** de mieux)
- meilleur coin : **BTC**

| coin | rendement net (bps/j) | marge cible ($) |
|---|---:|---:|
| BTC | 2.241 | 320.0 |
| ETH | 1.732 | 158.2 |
| SOL | 1.598 | 93.35 |
| HYPE | 1.465 | 95.74 |
| ZEC | 1.339 | 73.1 |
| XPL | 1.251 | 59.61 |

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

- **Cross-venue : 72 h atteintes (97 h)** → lancer `python tools/mesurer_dispersion_venues.py` pour LE verdict (#178).
- Relances de collecteurs au compteur : {'carry-feeder': 2, 'marks-collector': 2, 'liq-collector': 2, 'venues-collector': 3, 'rapport-quotidien': 1, 'carnet-collector': 1} — si un compteur grimpe SEUL demain, c'est lui le malade (doc R5).
- Copy-whitelist : 4 leader(s) prouvé(s) → copy peut suivre CES leaders uniquement.
- Markout copy : 88.6% des fills mesures (29211/32957) — le pipeline nourrit la whitelist.
- Replay : 603097 candidats consolidés → `RECHERCHE-SCENARIO-REPLAY.cmd` a de quoi travailler (porte deux-moitiés + plateau).

---
**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**