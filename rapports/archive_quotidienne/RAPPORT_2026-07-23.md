# Rapport quotidien HyperSmart — 23/07/2026 12:28

_Chaque chiffre se remonte à un fichier (ledger, positions, journaux). Fenêtre : dernières 24 h._

## 1. PnL réalisé (dernières 24 h)

- `ARB_STOP_ECART_AGGRAVE` : **-3.1958 $** (×12)
- `DONNEE_ABSENTE_PROLONGEE` : **-1.4779 $** (×6)
- `ARB_CONVERGENCE_CAPTUREE` : **+0.0412 $** (×1)
- `ARB_AGE_MAX_SANS_CONVERGENCE` : **+0.4394 $** (×6)

**Total 24 h : -4.1931 $** · 25 fermeture(s)

Total historique (toutes époques, jamais maquillé) : **-9.6234 $** sur 82 fermetures.

## 2. Positions ouvertes (paper)

- **BTC** : 1180 $ à 5.0x · âge 66.3 h · funding accru +0.6678 $
- **ETH** : 271 $ à 2.0x · âge 66.3 h · funding accru +0.1741 $
- **PURR** : 164 $ à 1.5x · âge 74.5 h · funding accru +0.1174 $
- **SOL** : 136 $ à 1.5x · âge 66.3 h · funding accru +0.0993 $
- **XPL** : 77 $ à 1.0x · âge 66.3 h · funding accru +0.0556 $
- **ZEC** : 79 $ à 1.0x · âge 41.1 h · funding accru +0.0407 $

## 3. Santé du système

- Collecteurs : 4/4 vivants.
- Superviseur : relances cumulées {'carry-feeder': 2, 'marks-collector': 2, 'liq-collector': 2, 'venues-collector': 3, 'rapport-quotidien': 1, 'carnet-collector': 1}

## 4. Mesures en cours

- Cross-venue : **93.0 h / 72 h** (288526 observations) — verdict aux barres pré-écrites, jamais avant.
- Usine à données replay (24 h) : **0 candidats** · **240716 marks** — c'est le carburant du replay A/B.

## 5. Refus dominants (24 h) — le bot explique pourquoi il n'ouvre pas

- ×10 `INPUTS_SPOT_PERIMES_NO_TRADE`

## 6. Leçons du ledger — aucune perte sans explication

22 perte(s), -4.8891 $ au total :
- 🔴 **RÉGRESSION** HYPE -0.1358 $ `DONNEE_ABSENTE_PROLONGEE` — cause reparee (e82dd4a+b6debb2) qui REVIENT apres le correctif : fermetures famine/rate-de-bougies : hors-shortlist gate par amortissement quand la donnee est vivante + cache pire-hausse 24 h. Le vrai blackout (0 mesure) reste une fermeture legitime -> demi-alarme seulement.
- 🔴 **RÉGRESSION** AZTEC -0.1070 $ `DONNEE_ABSENTE_PROLONGEE` — cause reparee (e82dd4a+b6debb2) qui REVIENT apres le correctif : fermetures famine/rate-de-bougies : hors-shortlist gate par amortissement quand la donnee est vivante + cache pire-hausse 24 h. Le vrai blackout (0 mesure) reste une fermeture legitime -> demi-alarme seulement.
- 🔴 **RÉGRESSION** VIRTUAL -0.2804 $ `DONNEE_ABSENTE_PROLONGEE` — cause reparee (e82dd4a+b6debb2) qui REVIENT apres le correctif : fermetures famine/rate-de-bougies : hors-shortlist gate par amortissement quand la donnee est vivante + cache pire-hausse 24 h. Le vrai blackout (0 mesure) reste une fermeture legitime -> demi-alarme seulement.
- 🔴 **RÉGRESSION** MON -0.1811 $ `DONNEE_ABSENTE_PROLONGEE` — cause reparee (e82dd4a+b6debb2) qui REVIENT apres le correctif : fermetures famine/rate-de-bougies : hors-shortlist gate par amortissement quand la donnee est vivante + cache pire-hausse 24 h. Le vrai blackout (0 mesure) reste une fermeture legitime -> demi-alarme seulement.
- 🔴 **RÉGRESSION** AVAX -0.5029 $ `DONNEE_ABSENTE_PROLONGEE` — cause reparee (e82dd4a+b6debb2) qui REVIENT apres le correctif : fermetures famine/rate-de-bougies : hors-shortlist gate par amortissement quand la donnee est vivante + cache pire-hausse 24 h. Le vrai blackout (0 mesure) reste une fermeture legitime -> demi-alarme seulement.
- 🔴 **RÉGRESSION** STABLE -0.2708 $ `DONNEE_ABSENTE_PROLONGEE` — cause reparee (e82dd4a+b6debb2) qui REVIENT apres le correctif : fermetures famine/rate-de-bougies : hors-shortlist gate par amortissement quand la donnee est vivante + cache pire-hausse 24 h. Le vrai blackout (0 mesure) reste une fermeture legitime -> demi-alarme seulement.
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
| BTC | 236$ | 1180$ | 0.125 | 0.3539$ | 0.6678$ | 1.3376$ | dans ~45 h |
| ETH | 135$ | 271$ | 0.125 | 0.0812$ | 0.1741$ | 0.2062$ | dans ~9 h |
| PURR | 109$ | 164$ | 0.125 | 0.0492$ | 0.1174$ | 0.1567$ | dans ~19 h |
| SOL | 90$ | 136$ | 0.125 | 0.0407$ | 0.0993$ | 0.1539$ | dans ~32 h |
| XPL | 77$ | 77$ | 0.125 | 0.0230$ | 0.0556$ | 0.0993$ | dans ~46 h |
| ZEC | 79$ | 79$ | 0.125 | 0.0238$ | 0.0407$ | 0.0605$ | dans ~20 h |

**Total : 0.5719 $/jour au taux courant · marge engagée 727 $** (déploiement à comparer au capital — la réserve de 20 % est voulue).

## 9. Scan carry — univers, viables, et presque-viables (avec leur verrou)

Univers introuvable dans le log feeder (collecteur pas encore passé ?).

## 10. Où va le capital (allocation)

- règle : `marge ∝ gain_net_24h_bps ** 3, plafond 40 % par coin, plancher 25 $`
- capital alloué : **800.0 $** sur 6 coin(s) financé(s)
- rendement pondéré : **2.4834 bps/j** (part égale : 1.9377 bps/j -> **28.16 %** de mieux)
- meilleur coin : **PURR**

| coin | rendement net (bps/j) | marge cible ($) |
|---|---:|---:|
| PURR | 3.417 | 320.0 |
| BTC | 2.228 | 211.31 |
| ETH | 1.794 | 110.32 |
| SOL | 1.514 | 66.3 |
| ZEC | 1.411 | 53.67 |
| XPL | 1.262 | 38.4 |

**Positions sous-financées** (le renfort les comblera, une par jour et par position, sans jamais fermer) :

- PURR : 109.24 $ -> 320.00 $ (**+210.76 $**)

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

- **Cross-venue : 72 h atteintes (93 h)** → lancer `python tools/mesurer_dispersion_venues.py` pour LE verdict (#178).
- Relances de collecteurs au compteur : {'carry-feeder': 2, 'marks-collector': 2, 'liq-collector': 2, 'venues-collector': 3, 'rapport-quotidien': 1, 'carnet-collector': 1} — si un compteur grimpe SEUL demain, c'est lui le malade (doc R5).
- Copy-whitelist : 3 leader(s) prouvé(s) → copy peut suivre CES leaders uniquement.
- Markout copy : 90.6% des fills mesures (27810/30703) — le pipeline nourrit la whitelist.
- Replay : 594692 candidats consolidés → `RECHERCHE-SCENARIO-REPLAY.cmd` a de quoi travailler (porte deux-moitiés + plateau).

---
**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**